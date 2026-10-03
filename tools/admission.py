"""Data-only GitHub admission for CRL 0.3 index entries.

Run only from a trusted base checkout. A passing entry is structurally indexable,
not scientifically accepted. Applying admission requires bounded anonymous archive
verification. Contributor code is never checked out or executed.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path

from jsonschema import ValidationError

from crl import (
    MAX_INDEX_BYTES,
    index_path,
    load_index,
    load_registry,
    loads,
    require,
    validate_index_graph,
)
from archive import verify as verify_archive

PATH = re.compile(r"index/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{64}\.json\Z")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("unexpected API redirect")


class API:
    def __init__(self, token: str):
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect())

    def __call__(self, path: str, method: str = "GET", data: dict | None = None):
        require(path.startswith("/repos/") and "://" not in path, "invalid API path")
        body = None if data is None else json.dumps(data).encode()
        req = urllib.request.Request(
            "https://api.github.com" + path,
            data=body,
            method=method,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "CRL-index-admission/0.3",
            },
        )
        with self.opener.open(req, timeout=30) as response:
            raw = response.read(2_000_001)
        return loads(raw, 2_000_000) if raw else None


def inspect(api, repo: str, number: int, root: Path, expected_head: str | None = None,
            archive_verifier=None, allow_merged: bool = False) -> dict:
    require(bool(REPO.fullmatch(repo)) and number > 0, "invalid repository or PR")
    prefix = "/repos/" + repo
    pr = api(f"{prefix}/pulls/{number}")
    already_merged = pr["state"] == "closed" and pr.get("merged") is True
    require((pr["state"] == "open" or (allow_merged and already_merged)) and not pr["draft"],
            "PR is closed or draft")
    require(
        pr["base"]["ref"] == "main" and pr["base"]["repo"]["full_name"] == repo,
        "wrong base repository/branch",
    )
    head = pr["head"]["sha"]
    require(bool(re.fullmatch(r"[0-9a-f]{40}", head)), "invalid head SHA")
    require(expected_head is None or head == expected_head, "PR changed; rerun validation")

    if pr["changed_files"] != 1:
        return {"eligible": False, "reason": "governance-or-multi-file-change", "head": head}

    files = api(f"{prefix}/pulls/{number}/files?per_page=2")
    require(len(files) == 1, "file-list mismatch")
    changed = files[0]
    if changed["status"] != "added" or not PATH.fullmatch(changed["filename"]):
        return {
            "eligible": False,
            "reason": "only-one-new-index-entry-is-auto-admissible",
            "head": head,
        }
    require(already_merged or not (root / changed["filename"]).exists(), "cannot replace an admitted index entry")

    head_repo = pr["head"]["repo"]["full_name"]
    require(bool(REPO.fullmatch(head_repo)), "invalid fork repository")
    remote = "/repos/" + head_repo
    tree = api(f"{remote}/git/trees/{head}?recursive=1")
    require(not tree.get("truncated", False), "head tree is truncated")
    entries = [e for e in tree["tree"] if e["path"] == changed["filename"]]
    require(len(entries) == 1, "missing tree entry")
    item = entries[0]
    require(item["type"] == "blob" and item["mode"] == "100644",
            "only regular non-executable index files are accepted")
    require(
        bool(re.fullmatch(r"[0-9a-f]{40}", item["sha"])) and item["sha"] == changed["sha"]
        and type(item.get("size")) is int and 0 < item["size"] <= MAX_INDEX_BYTES,
        "blob mismatch or oversize",
    )

    blob = api(f"{remote}/git/blobs/{item['sha']}")
    require(blob["encoding"] == "base64" and blob["size"] <= MAX_INDEX_BYTES,
            "invalid blob encoding or size")
    raw = base64.b64decode("".join(blob["content"].split()), validate=True)
    require(len(raw) == blob["size"], "blob length mismatch")
    require(hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == item["sha"],
            "Git blob content hash mismatch")
    entry = loads(raw, MAX_INDEX_BYTES)
    rid = entry.get("payload", {}).get("record_id", "")
    require("index/" + index_path(rid).as_posix() == changed["filename"], "filename mismatch")

    index = load_index(root / "index")
    require(rid not in index or (already_merged and index[rid] == entry), "duplicate indexed record")
    index[rid] = entry
    validate_index_graph(index, load_registry(root / "registry" / "problems.json"))
    archive_report = archive_verifier(entry) if archive_verifier else {"zenodo_fetched": False, "archive_verified": False}

    fresh = api(f"{prefix}/pulls/{number}")
    require(fresh["head"]["sha"] == head and fresh["base"]["ref"] == "main"
            and fresh["base"]["repo"]["full_name"] == repo and fresh["changed_files"] == 1
            and not fresh["draft"] and (fresh["state"] == "open" or (allow_merged and fresh.get("merged") is True)),
            "PR changed during validation")
    return {
        "eligible": True,
        "head": head,
        "record_id": rid,
        "path": changed["filename"],
        "blob_sha": item["sha"],
        "already_merged": already_merged,
        "scientific_validity": "not-assessed",
        **archive_report,
    }


def admitted_on_main(api, repo, report):
    """Read the exact checked regular blob at a pinned current default-branch commit."""
    commit = api(f"/repos/{repo}/git/ref/heads/main")["object"]["sha"]
    require(bool(re.fullmatch(r"[0-9a-f]{40}", commit)), "invalid admission commit")
    tree = api(f"/repos/{repo}/git/trees/{commit}?recursive=1")
    require(not tree.get("truncated", False), "admission tree is truncated")
    matches = [x for x in tree["tree"] if x["path"] == report["path"]]
    require(len(matches) == 1 and matches[0]["type"] == "blob" and matches[0]["mode"] == "100644"
            and matches[0]["sha"] == report["blob_sha"], "admitted header missing or differs on main")
    return commit


def apply(api, repo, number, root, expected_head=None, archive_verifier=verify_archive, local_head=None):
    # Archive checks cannot be turned off for a write-capable operation.
    require(archive_verifier is not None, "archive verifier required for admission")
    report = inspect(api, repo, number, root, expected_head, archive_verifier, allow_merged=True)
    if not report["eligible"]:
        return report
    require(report.get("archive_verified") is True, "published archive was not verified")
    if not report["already_merged"]:
        local = local_head or subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        live = api(f"/repos/{repo}/git/ref/heads/main")["object"]["sha"]
        require(local == live, "base changed; rerun against the new trusted main")
        # The API fixes the checked PR head. Main is serialized within this workflow,
        # but GitHub provides no expected-base parameter; maintainers may still race it.
        try:
            result = api(f"/repos/{repo}/pulls/{number}/merge", "PUT", {
                "sha": report["head"], "merge_method": "squash",
                "commit_title": "Index CRL publication " + report["record_id"].split(":")[-1][:12],
            })
        except OSError:
            result = None  # Unknown write outcome: read back, never repeat PUT here.
        fresh = api(f"/repos/{repo}/pulls/{number}")
        require(fresh.get("merged") is True and fresh["state"] == "closed"
                and fresh["head"]["sha"] == report["head"],
                "merge not confirmed; read back before any retry")
        require(result is None or result.get("merged") is True, "merge response disagrees with read-back")
    commit = admitted_on_main(api, repo, report)
    return {**report, "merged": True, "admission_commit": commit,
            "board_rebuild": "admission-workflow-completion",
            "scientific_validity": "not-assessed"}


def recover(api, repo, root, archive_verifier=verify_archive, local_head=None, slot=None):
    """Bounded hourly recovery for missed events, stale-base jobs or uncertain outcomes.

    At most 100 open PRs, 20 inspections and one merge per run. Rotating windows
    prevent invalid early PRs from permanently blocking later valid submissions.
    """
    require(bool(REPO.fullmatch(repo)), "invalid repository")
    pending = api(f"/repos/{repo}/pulls?state=open&base=main&per_page=100&page=1")
    require(isinstance(pending, list) and len(pending) <= 100, "invalid recovery PR list")
    if len(pending) == 100:
        extra = api(f"/repos/{repo}/pulls?state=open&base=main&per_page=100&page=2")
        require(not extra, "more than 100 open PRs; bounded recovery requires maintainer triage")
    numbers = sorted({p["number"] for p in pending if not p["draft"]})
    require(all(type(n) is int and n > 0 for n in numbers), "invalid recovery PR number")
    if not numbers:
        return {"recovery": [], "merged": False, "scientific_validity": "not-assessed"}
    offset = ((int(time.time() // 3600) if slot is None else slot) * 20) % len(numbers)
    numbers = (numbers[offset:] + numbers[:offset])[:20]
    reports, deadline = [], time.monotonic() + 240
    for number in numbers:
        if time.monotonic() >= deadline:
            break
        try:
            report = apply(api, repo, number, root, archive_verifier=archive_verifier, local_head=local_head)
            reports.append({"pr": number, **report})
            if report.get("merged"):
                break  # Re-checkout trusted main before any subsequent merge.
        except (KeyError, ValueError, OSError, ValidationError) as exc:
            reports.append({"pr": number, "eligible": False, "error_type": type(exc).__name__})
    return {"recovery": reports, "merged": any(r.get("merged", False) for r in reports),
            "scientific_validity": "not-assessed"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    choose = parser.add_mutually_exclusive_group(required=True)
    choose.add_argument("--pr", type=int)
    choose.add_argument("--scan", action="store_true")
    parser.add_argument("--head")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify-archive", action="store_true")
    args = parser.parse_args()
    try:
        root = Path(__file__).resolve().parents[1]
        repo = os.environ["GITHUB_REPOSITORY"]
        api = API(os.environ["GH_TOKEN"])
        if args.apply:
            require(os.environ.get("CRL_AUTO_ADMIT") == "true",
                    "automatic admission is not enabled")
            report = recover(api, repo, root) if args.scan else apply(api, repo, args.pr, root, args.head)
        else:
            require(not args.scan, "recovery scan requires the explicit enabled --apply lane")
            report = inspect(api, repo, args.pr, root, args.head,
                             verify_archive if args.verify_archive else None)
        print(json.dumps(report))
        return 0
    except (KeyError, ValueError, OSError, ValidationError) as exc:
        print(json.dumps({"error": str(exc)[:1500]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
