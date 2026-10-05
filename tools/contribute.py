"""Small resumable GitHub contributor bridge; CRL wire format remains in crl.py.

Requires an already signed, approved package and existing git/gh access. This
client never creates identities, forks, releases, deposits, or merges PRs.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request

import archive
import crl
from jsonschema.exceptions import ValidationError

VERSION = "commons-contribute/1"
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
STAGES = ["prepared", "archived", "header-signed", "PR-open", "admitted", "board-visible"]


class Pending(ValueError):
    """External state needs read-back; do not infer failure or retry a POST."""


def regular(path):
    path = Path(path).absolute()
    crl.require(all(not p.is_symlink() for p in (path, *path.parents)), "symlink rejected")
    return path


def repository(value):
    value = value.removeprefix("https://github.com/").removesuffix(".git")
    crl.require(bool(REPO.fullmatch(value)) and all(p not in {".", ".."} for p in value.split("/")),
                "expected an exact GitHub owner/repository")
    return value


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def atomic(path, raw):
    regular(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    regular(temporary)
    with temporary.open("wb") as stream:
        os.chmod(temporary, 0o600)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextlib.contextmanager
def journal(work):
    work = regular(work)
    work.mkdir(parents=True, exist_ok=True)
    lock = regular(work / "lock")
    with lock.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("another contributor process owns this journal") from exc
        yield work


def package(directory):
    directory = regular(directory)
    manifest = regular(directory / "crl-publication.json")
    publication = crl.read_json(manifest, crl.MAX_PUBLICATION_BYTES)
    crl.validate_publication(publication)
    files = {"crl-publication.json": manifest.read_bytes()}
    for artifact in publication["payload"]["artifacts"]:
        name = archive.file_key(artifact["path"])
        crl.require(name not in files, "duplicate/circular artifact path")
        path = regular(directory / name)
        crl.require(path.is_file() and path.stat().st_size <= archive.MAX_FILE_BYTES,
                    "artifact absent or outside small-package lane")
        raw = path.read_bytes()
        crl.require(hashlib.sha256(raw).hexdigest() == artifact["sha256"], "artifact hash differs")
        files[name] = raw
    actual = set()
    for current, directories, names in os.walk(directory, followlinks=False):
        for name in directories + names:
            regular(Path(current) / name)
        actual.update((Path(current) / n).relative_to(directory).as_posix() for n in names)
    crl.require(actual == set(files), "staging must contain exactly the manifest and declared artifacts")
    crl.require(len(files) <= 33 and sum(map(len, files.values())) <= archive.MAX_TOTAL_BYTES,
                "package outside small-package lane")
    hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(files.items())}
    return publication, files, hashes


def prepare(work, directory, archive_repo, index_repo, contributor_repo=None, manifest_path=None, archive_commit=None):
    directory = regular(directory)
    crl.require(not work.is_relative_to(directory) and not directory.is_relative_to(work),
                "journal and staging must be separate")
    publication, _, hashes = package(directory)
    digest = publication["id"].split(":")[-1]
    manifest_path = archive.file_key(manifest_path or f"publications/{digest}/crl-publication.json")
    crl.require(manifest_path.endswith("/crl-publication.json"), "use a dedicated package directory")
    crl.require(archive_commit is None or bool(SHA.fullmatch(archive_commit)), "archive commit must be a full SHA")
    config = {"package": str(directory), "archive_repository": repository(archive_repo),
              "index_repository": repository(index_repo),
              "contributor_repository": repository(contributor_repo or index_repo),
              "manifest_path": manifest_path, "existing_archive_commit": archive_commit,
              "record_id": publication["id"], "files": hashes}
    state_path = work / "state.json"
    if state_path.exists():
        state = crl.read_json(state_path, archive.MAX_METADATA_BYTES)
        crl.require(state["version"] == VERSION and state["config"] == config,
                    "journal already pins a different version/package/destination")
        return state
    state = {"version": VERSION, "config": config, "stage": "prepared", "operations": {},
             "scientific_validity": "not-assessed"}
    atomic(state_path, encode(state))
    return state


class GitHub:
    """Controlled existing gh; no token extraction or account configuration."""
    def __init__(self, work):
        self.work = work

    def call(self, path, data=None, missing=False):
        argv = ["gh", "api", "--hostname", "github.com", path]
        if data is not None:
            request = self.work / "request.json"
            atomic(request, encode(data))
            argv += ["--method", "POST", "--input", str(request)]
        try:
            result = subprocess.run(argv, capture_output=True, timeout=120)
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise Pending("GitHub operation uncertain; resume by read-back") from exc
        if result.returncode:
            if missing and b"HTTP 404" in result.stderr:
                return None
            # Do not print credential-helper output or raw server messages.
            raise Pending("GitHub action failed or uncertain; inspect connection and resume by read-back")
        return crl.loads(result.stdout, archive.MAX_METADATA_BYTES)

    def pages(self, path):
        rows = []
        for page in range(1, 11):
            response = self.call(path + ("&" if "?" in path else "?") + f"per_page=100&page={page}")
            crl.require(isinstance(response, list), "unexpected paginated response")
            rows.extend(response)
            if len(response) < 100:
                return rows
        raise ValueError("discovery exceeds bounded client lane; narrow/review separately")

    def blob(self, repo, sha, cap=crl.MAX_INDEX_BYTES):
        item = self.call(f"repos/{repo}/git/blobs/{sha}")
        crl.require(item["encoding"] == "base64" and 0 <= item["size"] <= cap, "Git blob outside byte bound")
        raw = base64.b64decode("".join(item["content"].split()), validate=True)
        crl.require(len(raw) == item["size"] and git_hash("blob", raw) == sha, "Git blob mismatch")
        return raw

    def main(self, repo):
        metadata = self.call(f"repos/{repo}")
        crl.require(metadata.get("private") is False and metadata["full_name"].lower() == repo.lower(),
                    "exact public repository required")
        branch = metadata["default_branch"]
        crl.require(bool(re.fullmatch(r"[A-Za-z0-9_./-]+", branch)), "unexpected default branch")
        commit = self.call(f"repos/{repo}/git/ref/heads/{branch}")["object"]["sha"]
        crl.require(bool(SHA.fullmatch(commit)), "invalid default-branch commit")
        tree = self.call(f"repos/{repo}/git/trees/{commit}?recursive=1")
        crl.require(not tree.get("truncated"), "default branch inventory truncated")
        return metadata, branch, commit, tree["tree"]


def git_hash(kind, raw):
    return hashlib.sha1(kind.encode() + b" " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def git(directory, arguments, raw=None, environment=None):
    argv = ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
            "-c", "protocol.file.allow=never", "--git-dir=" + str(directory), *arguments]
    try:
        result = subprocess.run(argv, input=raw, capture_output=True, timeout=120, env=environment)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise Pending("git operation uncertain; resume by exact ref read-back") from exc
    if result.returncode:
        raise Pending("git operation failed/uncertain; resume by exact ref read-back")
    return result.stdout.decode().strip()


def local_commit(work, lane, repo, parent, files, state, save):
    objects = regular(work / (lane + ".git"))
    if not objects.exists():
        git(objects, ["init", "--bare", str(objects)])
    source_repo = state["config"]["index_repository"] if lane == "index" else repo
    git(objects, ["fetch", "--no-tags", "https://github.com/" + source_repo + ".git", parent])
    git(objects, ["read-tree", parent])
    for path, raw in files.items():
        sha = git(objects, ["hash-object", "-w", "--stdin"], raw)
        crl.require(sha == git_hash("blob", raw), "local blob hash mismatch")
        git(objects, ["update-index", "--add", "--cacheinfo", "100644," + sha + "," + path])
    tree = git(objects, ["write-tree"])
    stamp = state.setdefault("commit_date", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    save()
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for prefix in ("GIT_AUTHOR_", "GIT_COMMITTER_"):
        env[prefix + "NAME"] = "CRL contributor client"
        env[prefix + "EMAIL"] = "crl-client@example.invalid"
        env[prefix + "DATE"] = stamp
    return git(objects, ["commit-tree", tree, "-p", parent],
               ("CRL " + lane + " " + state["config"]["record_id"] + "\n").encode(), env)


class Submission:
    def __init__(self, work, state, api=None, archive_verify=None, make_commit=None, push=None, board_read=None):
        self.work, self.state = work, state
        self.api = api or GitHub(work)
        self.archive_verify = archive_verify or archive.verify
        self.make_commit = make_commit or local_commit
        self.push = push or self.git_push
        self.board_read = board_read or self.public_board
        self.config = state["config"]
        self.publication, self.files, hashes = package(self.config["package"])
        crl.require(hashes == self.config["files"] and self.publication["id"] == self.config["record_id"],
                    "frozen package changed")
        self.path = "index/" + crl.index_path(self.config["record_id"]).as_posix()
        self.record = self.config["record_id"].split(":")[-1]

    def save(self):
        atomic(self.work / "state.json", encode(self.state))

    def stage(self, name):
        if STAGES.index(name) > STAGES.index(self.state["stage"]):
            self.state["stage"] = name
            self.state.setdefault("history", []).append({"stage": name, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        self.save()

    def compatible(self, raw):
        entry = crl.loads(raw, crl.MAX_INDEX_BYTES)
        crl.validate_index(entry)
        a = entry["payload"]["archive"]
        crl.require(a.get("provider") == "github-commit", "record already indexed with another archive provider")
        expected = crl.make_github_index_payload(self.publication,
                   "https://github.com/" + self.config["archive_repository"], a["commit"], self.config["manifest_path"])
        crl.require(entry["payload"] == expected, "same record has a different frozen archive/header; reconcile")
        if "archive_commit" in self.state:
            crl.require(a["commit"] == self.state["archive_commit"], "archive commit differs from journal")
        if "header_sha256" in self.state:
            crl.require(hashlib.sha256(raw).hexdigest() == self.state["header_sha256"], "signed header bytes differ")
        return entry

    def adopt(self, raw):
        entry = self.compatible(raw)
        self.state["archive_verification"] = self.archive_verify(entry)
        self.state["archive_commit"] = entry["payload"]["archive"]["commit"]
        self.state["header_sha256"] = hashlib.sha256(raw).hexdigest()
        atomic(self.work / "header.json", raw)
        self.stage("header-signed")
        return entry

    def graph(self, repo, tree):
        index = {}
        registry = None
        for row in tree:
            path = row["path"]
            if path == "registry/problems.json" or (path.startswith("index/") and path.endswith(".json")):
                crl.require(row["type"] == "blob" and row["mode"] == "100644", "unsafe registry/index mode")
                raw = self.api.blob(repo, row["sha"])
                if path == "registry/problems.json":
                    data = crl.loads(raw, crl.MAX_INDEX_BYTES)
                    roots = [p for group in data["programs"] for p in group["problems"]]
                    registry = {p["id"]: p for p in roots}
                    crl.require(len(roots) == len(registry), "duplicate root problem")
                else:
                    entry = crl.loads(raw, crl.MAX_INDEX_BYTES)
                    crl.validate_index(entry)
                    rid = entry["payload"]["record_id"]
                    crl.require(path == "index/" + crl.index_path(rid).as_posix() and rid not in index,
                                "index path or record duplication")
                    index[rid] = entry
        crl.require(registry is not None and self.publication["payload"]["problem"] in registry,
                    "root missing in target index; preparation preserved; request separate registry review")
        return index, registry

    def existing_pr(self):
        repo = self.config["index_repository"]
        matches = []
        for pr in self.api.pages(f"repos/{repo}/pulls?state=all"):
            files = self.api.pages(f"repos/{repo}/pulls/{pr['number']}/files")
            if any(f["filename"] == self.path for f in files):
                crl.require(len(files) == 1 and files[0]["status"] == "added", "matching PR is not a one-file addition")
                detail = self.api.call(f"repos/{repo}/pulls/{pr['number']}")
                crl.require(detail["changed_files"] == 1 and detail["base"]["repo"]["full_name"] == repo,
                            "matching PR changed scope")
                raw = self.api.blob(detail["head"]["repo"]["full_name"], files[0]["sha"])
                self.compatible(raw)
                matches.append((detail, raw))
        crl.require(len(matches) <= 1, "multiple PRs for this record; reconcile without posting")
        if not matches:
            return None
        pr, raw = matches[0]
        prior = self.state.get("pr")
        intent = self.state["operations"].get("pr")
        crl.require(not prior or (prior["number"] == pr["number"] and prior["head"] == pr["head"]["sha"]),
                    "recorded PR number/head changed; reconcile")
        crl.require(not intent or intent["head"] == pr["head"]["sha"], "PR differs from write-ahead head")
        crl.require(not pr.get("draft"), "matching draft PR awaits contributor review; do not recreate")
        crl.require(pr["state"] == "open" or pr.get("merged") is True,
                    "matching PR is closed without admission; reconcile without recreating")
        self.adopt(raw)
        self.state["pr"] = {"number": pr["number"], "head": pr["head"]["sha"], "url": pr["html_url"]}
        if intent:
            intent["phase"] = "confirmed"
        self.stage("PR-open")
        return pr

    def git_push(self, lane, repo, commit, branch):
        git(self.work / (lane + ".git"), ["push", "--force-with-lease=refs/heads/" + branch + ":",
            "https://github.com/" + repo + ".git", commit + ":refs/heads/" + branch])

    def publish_ref(self, lane, repo, parent, files):
        branch = "commons/" + lane + "-" + self.record
        operation = self.state["operations"].get(lane)
        ref = self.api.call(f"repos/{repo}/git/ref/heads/{branch}", missing=True)
        if ref:
            sha = ref["object"]["sha"]
            crl.require(operation and sha == operation["commit"], "pre-existing branch lacks an exact journal match; reconcile")
            operation["phase"] = "confirmed"
            self.save()
            return sha
        if operation:
            if not getattr(self, "retry_absent_ref", False):
                raise Pending("prior branch push has no confirmed ref; inspect before retrying; no repeated push")
            crl.require(operation["repository"] == repo and operation["branch"] == branch
                        and bool(SHA.fullmatch(operation["commit"])) and operation.get("attempt", 1) < 2,
                        "retry must use the original exact ref/commit and is limited to one")
            # Explicit retry only of a freshly absent, fixed ref. The empty-ref
            # lease prevents replacing a concurrently created/reflected branch.
            operation.update(phase="retry-intent", attempt=2)
            self.save()
            try:
                self.push(lane, repo, operation["commit"], branch)
            except Pending:
                pass
            ref = self.api.call(f"repos/{repo}/git/ref/heads/{branch}", missing=True)
            if not ref:
                raise Pending("same-ref retry still unconfirmed; inspect original operation")
            crl.require(ref["object"]["sha"] == operation["commit"], "retried remote ref differs")
            operation["phase"] = "confirmed"
            self.save()
            return operation["commit"]
        sha = self.make_commit(self.work, lane, repo, parent, files, self.state, self.save)
        crl.require(bool(SHA.fullmatch(sha)), "invalid locally fixed commit")
        self.state["operations"][lane] = {"phase": "intent", "attempt": 1, "commit": sha, "branch": branch, "repository": repo}
        self.save()  # Write-ahead before the sole external mutation.
        try:
            self.push(lane, repo, sha, branch)
        except Pending:
            pass
        ref = self.api.call(f"repos/{repo}/git/ref/heads/{branch}", missing=True)
        if not ref:
            raise Pending("branch push result unknown/absent; resume read-back, never repeat blindly")
        crl.require(ref["object"]["sha"] == sha, "remote branch differs from frozen commit")
        self.state["operations"][lane]["phase"] = "confirmed"
        self.save()
        return sha

    def public_board(self, repo, commit):
        owner, name = repo.split("/")
        base = f"https://{owner.lower()}.github.io/{name}/"
        opener = urllib.request.build_opener(archive.NoRedirect())
        values = {}
        for name, limit in (("board.json", archive.MAX_METADATA_BYTES), ("source-commit.txt", 256)):
            url = base + name + "?commit=" + commit
            request = urllib.request.Request(url, headers={"Accept-Encoding": "identity", "User-Agent": VERSION})
            try:
                with opener.open(request, timeout=20) as response:
                    crl.require(response.status == 200 and response.geturl() == url
                                and response.headers.get("Content-Encoding", "identity") == "identity", "unexpected board response")
                    values[name] = response.read(limit + 1)
                crl.require(len(values[name]) <= limit, "board response outside byte bound")
            except OSError as exc:
                raise Pending("admitted; public board unavailable/delayed") from exc
        return crl.loads(values["board.json"], archive.MAX_METADATA_BYTES), values["source-commit.txt"].decode().strip()

    def check_admission(self, main, tree, index, registry):
        repo = self.config["index_repository"]
        row = next((r for r in tree if r["path"] == self.path), None)
        if row is None:
            return False
        entry = self.adopt(self.api.blob(repo, row["sha"]))
        crl.validate_index_graph(index, registry)
        if "pr" in self.state:
            actual = self.api.call(f"repos/{repo}/pulls/{self.state['pr']['number']}")
            crl.require(actual["head"]["sha"] == self.state["pr"]["head"], "admitted PR head changed")
            if not actual.get("merged") or actual.get("merged_by", {}).get("login") != "github-actions[bot]":
                raise Pending("header observed on main; automatic PR admission not confirmed")
            self.state["admission_mechanism"] = "verified-bot-pr"
        else:
            self.state["admission_mechanism"] = "observed-on-main"
        self.state["admission_commit"] = main
        self.stage("admitted")
        board, source = self.board_read(repo, main)
        if source != main or board != crl.board(index, registry):
            raise Pending("admitted; public board snapshot/source differs or is delayed")
        crl.require(entry in board["entries"] and all(q["acceptance"] == "not-assessed" for q in board["questions"]),
                    "public board header/scientific status differs")
        self.state["board_source_commit"] = source
        self.state["snapshot"] = board["snapshot"]["id"]
        self.stage("board-visible")
        return True

    def run(self, key_path=None, read_only=False, retry_absent_ref=False):
        self.retry_absent_ref = retry_absent_ref
        repo = self.config["index_repository"]
        metadata, base, main, tree = self.api.main(repo)
        index, registry = self.graph(repo, tree)
        if self.check_admission(main, tree, index, registry):
            return self.state
        pr = self.existing_pr()  # All states, actual file paths, before any archive write.
        if pr:
            raise Pending("PR-open; await repository admission, then resume the same journal")
        if "pr" in self.state or "pr" in self.state["operations"]:
            raise Pending("recorded PR outcome unconfirmed; no repeated POST")
        if read_only:
            raise Pending("read-only: no admitted record or existing matching PR; preparation preserved")
        contributor = self.config["contributor_repository"]
        fork = self.api.call(f"repos/{contributor}")
        crl.require(fork.get("private") is False and fork.get("permissions", {}).get("push") is True,
                    "existing public contributor repository with push access required")
        crl.require(contributor == repo or (fork.get("fork") is True and fork.get("parent", {}).get("full_name") == repo),
                    "contributor repository must be the index or its existing authorized fork")
        archive_repo = self.config["archive_repository"]
        ameta, _, aparent, atree = self.api.main(archive_repo)
        known_archive = self.config.get("existing_archive_commit")
        crl.require(known_archive or ameta.get("permissions", {}).get("push") is True, "existing archive push authorization required")
        if (self.work / "header.json").exists():
            raw = regular(self.work / "header.json").read_bytes()
            entry = self.adopt(raw)
        else:
            crl.require(key_path is not None, "existing authorized local signer required; preparation preserved")
            key_path = regular(key_path)
            crl.require(not key_path.is_relative_to(self.work) and not key_path.is_relative_to(Path(self.config["package"]))
                        and not any((p / ".git").exists() for p in key_path.parents), "signer must stay outside journals/repositories/packages")
            key = crl._private_key(key_path)
            crl.require(key.public_key().public_bytes_raw().hex() == self.publication["payload"]["actor"]["public_key"],
                        "publication and index must use the same existing signer")
            # Validate the candidate's typed relations before any archive write.
            # This projection uses the observed parent only in memory; it is not
            # persisted, submitted, or claimed as a published package.
            provisional = crl.sign_index(crl.make_github_index_payload(self.publication,
                          "https://github.com/" + archive_repo, aparent, self.config["manifest_path"]), key)
            candidate_graph = dict(index)
            candidate_graph[self.config["record_id"]] = provisional
            crl.validate_index_graph(candidate_graph, registry)
            crl.require(len(encode(provisional)) <= crl.MAX_INDEX_BYTES, "serialized index header too large")
            prefix = self.config["manifest_path"].rsplit("/", 1)[0] + "/"
            crl.require(known_archive or not any(r["path"].startswith(prefix) for r in atree), "package directory already exists; reconcile fixed archive")
            commit = self.state.get("archive_commit") or known_archive or self.publish_ref("archive", archive_repo, aparent,
                                             {prefix + p: raw for p, raw in self.files.items()})
            entry = crl.sign_index(crl.make_github_index_payload(self.publication,
                       "https://github.com/" + archive_repo, commit, self.config["manifest_path"]), key)
            crl.validate_index(entry)
            self.archive_verify(entry)  # Actual public bytes, not local staging.
            self.state["archive_commit"] = commit
            self.stage("archived")
            self.adopt(encode(entry))
        index[self.config["record_id"]] = entry
        crl.validate_index_graph(index, registry)
        raw = (self.work / "header.json").read_bytes()
        head = self.publish_ref("index", contributor, main, {self.path: raw})
        comparison = self.api.call(f"repos/{repo}/compare/{main}...{contributor.split('/')[0]}:{head}")
        crl.require(comparison["ahead_by"] == 1 and len(comparison["files"]) == 1
                    and comparison["files"][0]["filename"] == self.path
                    and comparison["files"][0]["status"] == "added", "PR diff is not exactly one new header")
        branch = self.state["operations"]["index"]["branch"]
        request = {"base": base, "head": contributor.split("/")[0] + ":" + branch,
                   "title": "Index CRL " + self.record[:12], "body": "One signed discovery header. Public archive bytes verified. Scientific validity: not-assessed.",
                   "draft": False}
        self.state["operations"]["pr"] = {"phase": "intent", "head": head, "request": request}
        self.save()
        try:
            created = self.api.call(f"repos/{repo}/pulls", request)
            self.state["pr"] = {"number": created["number"], "head": head, "url": created["html_url"]}
            self.save()
        except Pending:
            pass
        pr = self.existing_pr()
        if not pr:
            raise Pending("PR creation result unknown/absent; resume read-back; no repeated POST")
        crl.require(pr["head"]["sha"] == head, "PR does not have the exact fixed head")
        self.state["operations"]["pr"]["phase"] = "confirmed"
        self.stage("PR-open")
        raise Pending("PR-open; await repository admission, then resume the same journal")


def safe_error(exc):
    if isinstance(exc, ValidationError):
        return "schema check failed; inspect the pinned public schema"
    return str(exc)[:1200] if isinstance(exc, ValueError) else type(exc).__name__


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare", help="local only; signed approved package")
    prep.add_argument("--package", type=Path, required=True)
    prep.add_argument("--archive-repository", required=True)
    prep.add_argument("--index-repository", required=True)
    prep.add_argument("--contributor-repository")
    prep.add_argument("--manifest-path")
    prep.add_argument("--archive-commit", help="reuse this existing public full commit; no archive push")
    submit = commands.add_parser("submit", help="authorized writes through existing git/gh; resume same journal")
    submit.add_argument("--key", type=Path)
    submit.add_argument("--read-only", action="store_true", help="only adopt/read existing archive-index-admission; no signing or remote writes")
    submit.add_argument("--retry-absent-ref", action="store_true", help="one explicit retry of a freshly absent original ref/commit; never repeats a PR POST")
    commands.add_parser("status", help="local state; no key/network required")
    args = parser.parse_args(argv)
    try:
        with journal(args.work) as work:
            if args.command == "prepare":
                state = prepare(work, args.package, args.archive_repository, args.index_repository,
                                args.contributor_repository, args.manifest_path, args.archive_commit)
            else:
                state = crl.read_json(work / "state.json", archive.MAX_METADATA_BYTES)
                crl.require(state["version"] == VERSION, "journal version differs")
                if args.command == "submit":
                    try:
                        submission = Submission(work, state)
                        state = submission.run(args.key, args.read_only, args.retry_absent_ref)
                        state.pop("pending", None)
                        state.pop("stopped", None)
                        submission.save()
                    except Pending as exc:
                        state["pending"] = str(exc)
                        state.pop("stopped", None)
                        atomic(work / "state.json", encode(state))
                        raise
                    except (ValueError, KeyError, OSError, ValidationError) as exc:
                        state.pop("pending", None)
                        state["stopped"] = safe_error(exc)
                        atomic(work / "state.json", encode(state))
                        raise
            print(json.dumps(state, ensure_ascii=False))
        return 0
    except Pending as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (ValueError, KeyError, OSError, ValidationError) as exc:
        # Do not expose key paths/private parser material in errors.
        print("Contribution stopped: " + safe_error(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
