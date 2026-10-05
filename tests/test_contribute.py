"""Isolated contributor boundary tests; not production/fork identity E2E."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_crl import make_publication
import crl
import contribute as client


class FakeGitHub:
    def __init__(self):
        self.refs, self.blobs, self.prs, self.writes = {}, {}, [], []
        self.index, self.registry = {}, crl.load_registry()
        self.main_sha = "a" * 40
        self.lose_pr = False
        self.lose_push = False
        self.fork = "contributor/commons"
        self.last_header = None

    def add_blob(self, raw):
        sha = client.git_hash("blob", raw)
        self.blobs[sha] = raw
        return sha

    def main(self, repo):
        metadata = {"private": False, "full_name": repo, "permissions": {"push": True}}
        tree = []
        if repo == "owner/commons":
            raw = (crl.ROOT / "registry/problems.json").read_bytes()
            tree.append({"path": "registry/problems.json", "type": "blob", "mode": "100644", "sha": self.add_blob(raw)})
            for rid, raw in self.index.items():
                tree.append({"path": "index/" + crl.index_path(rid).as_posix(), "type": "blob", "mode": "100644", "sha": self.add_blob(raw)})
        return metadata, "main", self.main_sha, tree

    def blob(self, repo, sha, cap=crl.MAX_INDEX_BYTES):
        return self.blobs[sha]

    def pages(self, path):
        if "/files" in path:
            number = int(path.split("/pulls/")[1].split("/")[0])
            pr = next(p for p in self.prs if p["number"] == number)
            return pr["files"]
        return self.prs

    def call(self, path, data=None, missing=False):
        if data is not None:
            self.writes.append((path, copy.deepcopy(data)))
            if path.endswith("/pulls"):
                pr = {"number": 1, "state": "open", "merged": False, "changed_files": 1,
                      "html_url": "https://github.com/owner/commons/pull/1",
                      "base": {"repo": {"full_name": "owner/commons"}},
                      "head": {"sha": self.refs[(self.fork, data["head"].split(":", 1)[1])], "repo": {"full_name": self.fork}},
                      "files": [{"filename": self.last_path, "status": "added", "sha": self.add_blob(self.last_header)}]}
                self.prs.append(pr)
                if self.lose_pr:
                    raise client.Pending("lost PR response")
                return pr
            raise AssertionError(path)
        if "/git/ref/heads/" in path:
            repo, branch = path.removeprefix("repos/").split("/git/ref/heads/")
            sha = self.refs.get((repo, branch))
            return {"object": {"sha": sha}} if sha else None
        if "/pulls/" in path:
            return self.prs[0]
        if path == "repos/" + self.fork:
            return {"private": False, "permissions": {"push": True}, "fork": True, "parent": {"full_name": "owner/commons"}}
        if "/compare/" in path:
            return {"ahead_by": 1, "files": [{"filename": self.last_path, "status": "added"}]}
        raise AssertionError(path)

    def commit(self, work, lane, repo, parent, files, state, save):
        if lane == "index":
            self.last_path, self.last_header = next(iter(files.items()))
        return hashlib.sha1((lane + parent).encode() + b"".join(files.values())).hexdigest()

    def push(self, lane, repo, commit, branch):
        self.writes.append(("push", (lane, repo, commit, branch)))
        self.refs[(repo, branch)] = commit
        if self.lose_push:
            raise client.Pending("lost push response")

    def board(self, repo, commit):
        entries = {rid: crl.loads(raw, crl.MAX_INDEX_BYTES) for rid, raw in self.index.items()}
        return crl.board(entries, self.registry), commit

    def admit(self):
        entry = crl.loads(self.last_header, crl.MAX_INDEX_BYTES)
        self.index[entry["payload"]["record_id"]] = self.last_header
        self.prs[0].update(state="closed", merged=True, merged_by={"login": "github-actions[bot]"})
        self.main_sha = "f" * 40


class ContributionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.package = self.root / "package"
        self.package.mkdir()
        self.publication, self.key = make_publication()
        (self.package / "crl-publication.json").write_bytes(client.encode(self.publication))
        self.key_path = self.root / "authorized.key"
        self.key_path.write_text(self.key.private_bytes_raw().hex())  # Synthetic fixture only.
        self.work = self.root / "journal"
        self.work.mkdir()
        self.state = client.prepare(self.work, self.package, "owner/archive", "owner/commons", "contributor/commons")
        self.api = FakeGitHub()
        self.verified = []

    def verify(self, entry):
        crl.validate_index(entry)
        self.verified.append(copy.deepcopy(entry))
        return {"archive_verified": True, "scientific_validity": "not-assessed"}

    def submission(self, board=None):
        return client.Submission(self.work, self.state, self.api, self.verify, self.api.commit, self.api.push, board or self.api.board)

    def open(self):
        with self.assertRaisesRegex(client.Pending, "PR-open"):
            self.submission().run(self.key_path)

    def test_complete_fork_flow_and_repeat_has_no_writes(self):
        self.open()
        self.assertEqual(self.state["stage"], "PR-open")
        self.assertEqual(len(self.api.writes), 3)
        self.assertTrue(self.verified)
        self.api.admit()
        self.submission().run()
        self.assertEqual(self.state["stage"], "board-visible")
        writes = copy.deepcopy(self.api.writes)
        self.submission().run()
        self.assertEqual(self.api.writes, writes)
        self.assertEqual(self.state["scientific_validity"], "not-assessed")

    def test_lost_push_response_adopts_exact_ref(self):
        self.api.lose_push = True
        self.open()
        self.assertEqual(len(self.api.writes), 3)
        self.assertEqual(self.state["operations"]["archive"]["phase"], "confirmed")

    def test_lost_pr_response_is_read_back_without_repeat(self):
        self.api.lose_pr = True
        self.open()
        before = copy.deepcopy(self.api.writes)
        with self.assertRaises(client.Pending):
            self.submission().run()
        self.assertEqual(self.api.writes, before)
        self.assertEqual(self.state["operations"]["pr"]["phase"], "confirmed")

    def test_unknown_absent_push_stops_without_retry(self):
        def absent(lane, repo, commit, branch):
            self.api.writes.append(("unconfirmed push", commit))
            raise client.Pending("connection dropped")
        submission = self.submission()
        submission.push = absent
        with self.assertRaisesRegex(client.Pending, "unknown/absent"):
            submission.run(self.key_path)
        before = copy.deepcopy(self.api.writes)
        with self.assertRaisesRegex(client.Pending, "no repeated push"):
            self.submission().run(self.key_path)
        self.assertEqual(self.api.writes, before)

    def test_explicit_absent_ref_retry_keeps_original_commit_and_ref(self):
        attempts = []
        def absent(lane, repo, commit, branch):
            attempts.append((lane, repo, commit, branch))
            raise client.Pending("transport dropped before ref")
        submission = self.submission()
        submission.push = absent
        with self.assertRaises(client.Pending):
            submission.run(self.key_path)
        with self.assertRaisesRegex(client.Pending, "PR-open"):
            self.submission().run(self.key_path, retry_absent_ref=True)
        self.assertEqual(self.api.writes[0][1], attempts[0])
        self.assertEqual(self.state["operations"]["archive"]["attempt"], 2)

    def test_existing_admitted_record_adopted_without_key_or_write(self):
        entry = crl.sign_index(crl.make_github_index_payload(self.publication, "https://github.com/owner/archive", "c" * 40, self.state["config"]["manifest_path"]), self.key)
        self.api.index[self.publication["id"]] = client.encode(entry)
        self.submission().run()
        self.assertEqual(self.api.writes, [])
        self.assertEqual(self.state["stage"], "board-visible")

    def test_board_delay_does_not_claim_visibility(self):
        self.open()
        self.api.admit()
        def delayed(repo, commit):
            board, source = self.api.board(repo, commit)
            return board, "b" * 40
        with self.assertRaisesRegex(client.Pending, "delayed"):
            self.submission(delayed).run()
        self.assertEqual(self.state["stage"], "admitted")
        self.submission().run()
        self.assertEqual(self.state["stage"], "board-visible")

    def test_closed_unmerged_pr_blocks_republication(self):
        self.open()
        self.api.prs[0]["state"] = "closed"
        before = copy.deepcopy(self.api.writes)
        with self.assertRaisesRegex(ValueError, "closed without admission"):
            self.submission().run()
        self.assertEqual(self.api.writes, before)

    def test_wrong_key_stops_before_any_write(self):
        _, other = make_publication()
        self.key_path.write_text(other.private_bytes_raw().hex())
        with self.assertRaisesRegex(ValueError, "same existing signer"):
            self.submission().run(self.key_path)
        self.assertEqual(self.api.writes, [])

    def test_secret_and_key_path_never_persist(self):
        self.open()
        for path in self.work.glob("*.json"):
            text = path.read_text()
            self.assertNotIn(self.key.private_bytes_raw().hex(), text)
            self.assertNotIn(str(self.key_path), text)

    def test_package_changes_or_extra_files_rejected(self):
        (self.package / "private-note.txt").write_text("not approved")
        with self.assertRaisesRegex(ValueError, "exactly"):
            self.submission()
        self.assertEqual(self.api.writes, [])

    def test_destination_and_version_are_immutable(self):
        with self.assertRaisesRegex(ValueError, "different version/package/destination"):
            client.prepare(self.work, self.package, "other/archive", "owner/commons", "contributor/commons")

    def test_symlink_package_rejected(self):
        path = self.root / "link"
        path.symlink_to(self.package, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            client.package(path)

    def test_missing_root_preserves_preparation_and_stops_before_write(self):
        original = self.api.main
        def missing_root(repo):
            metadata, base, sha, tree = original(repo)
            return metadata, base, sha, [] if repo == "owner/commons" else tree
        self.api.main = missing_root
        with self.assertRaisesRegex(ValueError, "root missing"):
            self.submission().run(self.key_path)
        self.assertEqual(self.state["stage"], "prepared")
        self.assertTrue((self.work / "state.json").exists())
        self.assertEqual(self.api.writes, [])

    def test_cli_conflict_updates_durable_message(self):
        self.open()
        self.state["pending"] = "older observation"
        self.submission().save()
        self.api.prs[0]["head"]["sha"] = "e" * 40
        original = client.Submission
        def factory(work, state):
            return original(work, state, self.api, self.verify, self.api.commit, self.api.push, self.api.board)
        with patch.object(client, "Submission", side_effect=factory):
            with patch("sys.stderr"):
                code = client.main(["--work", str(self.work), "submit"])
        saved = json.loads((self.work / "state.json").read_text())
        self.assertEqual(code, 1)
        self.assertNotIn("pending", saved)
        self.assertIn("head changed", saved["stopped"])

    def test_read_only_missing_record_has_no_writes_or_signing(self):
        with patch.object(crl, "_private_key", side_effect=AssertionError("signer access")):
            with self.assertRaisesRegex(client.Pending, "read-only"):
                self.submission().run(self.key_path, read_only=True)
        self.assertEqual(self.api.writes, [])

    def test_local_git_object_bridge_uses_exact_inventory_and_parent(self):
        objects = self.work / "archive.git"
        client.git(objects, ["init", "--bare", str(objects)])
        tree = client.git(objects, ["write-tree"])
        import os
        env = dict(os.environ)
        env.update(GIT_AUTHOR_NAME="Synthetic Fixture", GIT_AUTHOR_EMAIL="fixture@example.invalid",
                   GIT_COMMITTER_NAME="Synthetic Fixture", GIT_COMMITTER_EMAIL="fixture@example.invalid",
                   GIT_AUTHOR_DATE="2026-10-03T00:00:00Z", GIT_COMMITTER_DATE="2026-10-03T00:00:00Z")
        parent = client.git(objects, ["commit-tree", tree], b"synthetic base\n", env)
        original = client.git
        def local_only(directory, arguments, raw=None, environment=None):
            if arguments[0] == "fetch":
                return ""  # Base objects are already local; no remote boundary here.
            return original(directory, arguments, raw, environment)
        raw = b"synthetic selected bytes\n"
        with patch.object(client, "git", local_only):
            sha = client.local_commit(self.work, "archive", "owner/archive", parent,
                                      {"publications/test/data.txt": raw}, self.state, lambda: None)
        inventory = original(objects, ["ls-tree", "-r", sha])
        self.assertEqual(inventory, "100644 blob " + client.git_hash("blob", raw) + "\tpublications/test/data.txt")
        committed = original(objects, ["cat-file", "-p", sha])
        self.assertIn("parent " + parent, committed)
        self.assertIn("CRL archive " + self.publication["id"], committed)

    def test_preexisting_archive_reuse_makes_no_archive_push(self):
        # New journal, same approved package, actual commit represented by fixture.
        self.work = self.root / "existing-archive-journal"
        self.work.mkdir()
        self.state = client.prepare(self.work, self.package, "owner/archive", "owner/commons",
                                    "contributor/commons", archive_commit="d" * 40)
        self.open()
        self.assertEqual([v[1][0] for v in self.api.writes if v[0] == "push"], ["index"])
        self.assertEqual(self.state["archive_commit"], "d" * 40)

    def test_pr_head_change_is_not_adopted(self):
        self.open()
        self.api.prs[0]["head"]["sha"] = "e" * 40
        before = copy.deepcopy(self.api.writes)
        with self.assertRaisesRegex(ValueError, "head changed"):
            self.submission().run()
        self.assertEqual(self.api.writes, before)

    def test_typed_relation_failure_precedes_archive_write(self):
        payload = copy.deepcopy(self.publication["payload"])
        payload["relations"].append({"type": "depends-on", "target": payload["problem"], "scope": "invalid root dependency"})
        self.publication = crl.sign_publication(payload, self.key)
        (self.package / "crl-publication.json").write_bytes(client.encode(self.publication))
        self.work = self.root / "relation-journal"
        self.work.mkdir()
        self.state = client.prepare(self.work, self.package, "owner/archive", "owner/commons", "contributor/commons")
        with self.assertRaisesRegex(ValueError, "invalid root relation"):
            self.submission().run(self.key_path)
        self.assertEqual(self.api.writes, [])

    def test_simultaneous_writer_refused(self):
        with client.journal(self.work):
            with self.assertRaisesRegex(ValueError, "another contributor"):
                with client.journal(self.work):
                    self.fail("concurrent lock")


if __name__ == "__main__":
    unittest.main()
