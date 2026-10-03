"""Local boundary tests. No network, production credentials, accounts or publishing."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import archive
import crl
from admission import apply, inspect, recover
import test_crl as fixtures
make_publication, make_entry = fixtures.make_publication, fixtures.make_entry
from jsonschema import ValidationError


def blob_sha(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.pub, self.key = make_publication()
        p = copy.deepcopy(self.pub["payload"])
        p["artifacts"] = [{"path": "note.txt", "sha256": hashlib.sha256(b"finite fixture").hexdigest(),
                           "description": "Synthetic finite test", "license_declared": "TEST-LICENSE"}]
        self.pub = crl.sign_publication(p, self.key)
        self.files = {"crl-publication.json": json.dumps(self.pub).encode(), "note.txt": b"finite fixture"}
        self.repository = "https://github.com/fixture/archive"
        self.commit = "c" * 40
        self.manifest = "publications/finite/crl-publication.json"
        self.header = crl.sign_index(crl.make_github_index_payload(self.pub, self.repository, self.commit,
                                                                 self.manifest), self.key)
        self.urls = []
        self.repo_meta = {"private": False, "visibility": "public", "full_name": "fixture/archive"}
        self.tree = {"truncated": False, "tree": [{"path": "publications/finite/" + name,
                     "type": "blob", "mode": "100644", "sha": blob_sha(raw), "size": len(raw)}
                    for name, raw in self.files.items()]}

    def fetch(self, url, limit):
        self.urls.append(url)
        if url == "https://api.github.com/repos/fixture/archive":
            raw = json.dumps(self.repo_meta).encode()
        elif "/git/trees/" in url:
            raw = json.dumps(self.tree).encode()
        else:
            name = url.rsplit("/", 1)[-1]
            raw = self.files[name]
        self.assertLessEqual(len(raw), limit)
        return raw

    def test_github_commit_archive_roundtrip_without_doi(self):
        report = archive.verify(self.header, self.fetch)
        self.assertTrue(report["archive_verified"])
        self.assertTrue(report["github_fetched"])
        self.assertFalse(report["zenodo_fetched"])
        self.assertEqual(report["scientific_validity"], "not-assessed")
        self.assertNotIn("doi", self.header["payload"]["archive"])
        self.assertTrue(all(self.commit in u or u == "https://api.github.com/repos/fixture/archive" for u in self.urls))

    def test_mutable_ref_url_and_mixed_modes_rejected(self):
        for field, value in (("commit", "main"), ("url", self.repository + "/tree/main"),
                             ("repository", "https://evil.invalid/archive"), ("manifest_path", "../crl-publication.json")):
            payload = copy.deepcopy(self.header["payload"])
            payload["archive"][field] = value
            with self.assertRaises((ValueError, ValidationError)):
                crl.validate_index(crl.sign_index(payload, self.key))
        payload = copy.deepcopy(self.header["payload"])
        payload["archive"]["doi"] = "10.5281/zenodo.1"
        with self.assertRaises(ValidationError):
            crl.validate_index(crl.sign_index(payload, self.key))

    def test_archive_private_symlink_and_truncated_tree_rejected(self):
        self.repo_meta["private"] = True
        with self.assertRaisesRegex(ValueError, "public"):
            archive.verify(self.header, self.fetch)
        self.repo_meta["private"] = False
        self.tree["truncated"] = True
        with self.assertRaisesRegex(ValueError, "truncated"):
            archive.verify(self.header, self.fetch)
        self.tree["truncated"] = False
        self.tree["tree"][1]["mode"] = "120000"
        with self.assertRaisesRegex(ValueError, "symlink"):
            archive.verify(self.header, self.fetch)

    def test_extra_missing_oversize_and_tampered_files_rejected(self):
        self.tree["tree"].append({"path": "publications/finite/undeclared.txt", "type": "blob", "mode": "100644",
                                   "sha": "f" * 40, "size": 0})
        with self.assertRaisesRegex(ValueError, "inventory"):
            archive.verify(self.header, self.fetch)
        self.tree["tree"].pop()
        self.tree["tree"][1]["size"] = archive.MAX_FILE_BYTES + 1
        with self.assertRaisesRegex(ValueError, "size"):
            archive.verify(self.header, self.fetch)
        self.tree["tree"][1]["size"] = len(self.files["note.txt"])
        self.files["note.txt"] = b"broken fixture"
        with self.assertRaisesRegex(ValueError, "blob hash"):
            archive.verify(self.header, self.fetch)

    def test_valid_git_blob_but_wrong_artifact_sha_rejected(self):
        self.files["note.txt"] = b"broken fixture"
        self.tree["tree"][1]["sha"] = blob_sha(self.files["note.txt"])
        with self.assertRaisesRegex(ValueError, "artifact SHA256"):
            archive.verify(self.header, self.fetch)

    def test_header_scope_differs_from_archive_rejected(self):
        p = copy.deepcopy(self.header["payload"])
        p["scope"] = "a stronger unchecked claim"
        with self.assertRaisesRegex(ValueError, "header differs"):
            archive.verify(crl.sign_index(p, self.key), self.fetch)

    def test_board_shows_real_commit_link_and_keeps_not_assessed(self):
        with tempfile.TemporaryDirectory() as d:
            crl.write_board(Path(d), {self.pub["id"]: self.header}, crl.load_registry())
            page = (Path(d) / "index.html").read_text()
            self.assertIn("GitHub commit snapshot", page)
            self.assertIn(self.commit, page)
            self.assertNotIn("Zenodo Version DOI:", page)
            data = json.loads((Path(d) / "board.json").read_text())
            self.assertEqual(data["entries"][0]["payload"]["archive"]["provider"], "github-commit")
            self.assertTrue(all(q["acceptance"] == "not-assessed" for q in data["questions"]))

    def zenodo_fixture(self):
        entry = make_entry(self.pub, self.key)
        meta = {"id": 123456, "doi": "10.5281/zenodo.123456", "conceptdoi": "10.5281/zenodo.123450",
                "metadata": {"access_right": "open"}, "files": [{"key": name, "size": len(raw),
                    "checksum": "md5:" + hashlib.md5(raw).hexdigest(), "links": {"self":
                    "https://zenodo.org/api/records/123456/files/" + name + "/content"}}
                    for name, raw in self.files.items()]}
        def fetch(url, limit):
            if url.endswith("/api/records/123456"):
                return json.dumps(meta).encode()
            return self.files[url.split("/")[-2]]
        return entry, meta, fetch

    def test_zenodo_compatibility_and_version_semantics(self):
        entry, meta, fetch = self.zenodo_fixture()
        report = archive.verify(entry, fetch)
        self.assertTrue(report["archive_verified"])
        self.assertTrue(report["zenodo_fetched"])
        meta["conceptdoi"] = meta["doi"]
        with self.assertRaisesRegex(ValueError, "distinction"):
            archive.verify(entry, fetch)

    def test_zenodo_external_file_link_and_draft_rejected(self):
        entry, meta, fetch = self.zenodo_fixture()
        meta["is_published"] = False
        with self.assertRaisesRegex(ValueError, "draft"):
            archive.verify(entry, fetch)
        meta["is_published"] = True
        meta["files"][0]["links"]["self"] = "https://127.0.0.1/credential"
        with self.assertRaisesRegex(ValueError, "origin"):
            archive.verify(entry, fetch)

    def test_public_fetch_has_no_auth_and_does_not_follow_redirects(self):
        client = archive.Zenodo(github=True)
        with patch.object(client.opener, "open", side_effect=OSError("mock transport")) as op:
            with self.assertRaises(OSError):
                client("https://api.github.com/repos/fixture/archive", 100)
            request = op.call_args.args[0]
            self.assertNotIn("Authorization", dict(request.header_items()))
        with self.assertRaises(ValueError):
            client("https://api.github.com@evil.invalid/repos/fixture/archive", 100)
        with self.assertRaisesRegex(ValueError, "redirect"):
            archive.NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.invalid/")


class ApplyTests(unittest.TestCase):
    def setUp(self):
        fixtures.AdmissionTests.setUp(self)
        self.local = "d" * 40
        self.live = self.local
        self.puts = []
        self.fail_merge = False
        self.refuse_merge = False
        self.main_match = True
        self.base_api = lambda path, method="GET", data=None: fixtures.AdmissionTests.api(self, path, method, data)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "registry").mkdir()
        (self.root / "registry/problems.json").write_bytes(crl.ROOT.joinpath("registry/problems.json").read_bytes())
        (self.root / "index").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def api(self, path, method="GET", data=None):
        if path.endswith("/merge"):
            self.puts.append(data)
            if self.refuse_merge:
                return {"merged": False}
            self.pr.update(state="closed", merged=True)
            self.live = "e" * 40
            if self.fail_merge:
                raise OSError("timeout after successful mock merge")
            return {"merged": True, "sha": self.live}
        if path.endswith("/git/ref/heads/main"):
            return {"object": {"sha": self.live}}
        if f"/git/trees/{self.live}" in path:
            tree = self.base_api(path)
            if not self.main_match:
                tree["tree"][0]["sha"] = "0" * 40
            return tree
        return self.base_api(path, method, data)

    def apply(self, verifier=None):
        return apply(self.api, "owner/commons", 1, self.root, self.pr["head"]["sha"],
                     archive_verifier=verifier or (lambda e: {"archive_verified": True, "zenodo_fetched": True}),
                     local_head=self.local)

    def test_auto_merge_fixed_head_archive_and_main_readback(self):
        report = self.apply()
        self.assertEqual(self.puts[0]["sha"], "a" * 40)
        self.assertTrue(report["merged"])
        self.assertEqual(report["admission_commit"], self.live)
        self.assertEqual(report["scientific_validity"], "not-assessed")

    def test_retry_merged_pr_is_readonly(self):
        self.apply()
        again = self.apply()
        self.assertTrue(again["already_merged"])
        self.assertEqual(len(self.puts), 1)

    def test_timeout_after_merge_recovers_without_second_put(self):
        self.fail_merge = True
        self.assertTrue(self.apply()["merged"])
        self.assertEqual(len(self.puts), 1)

    def test_unverified_archive_and_stale_base_never_merge(self):
        with self.assertRaisesRegex(ValueError, "archive"):
            self.apply(lambda e: {"archive_verified": False})
        self.assertFalse(self.puts)
        self.live = "f" * 40
        with self.assertRaisesRegex(ValueError, "base changed"):
            self.apply()
        self.assertFalse(self.puts)

    def test_refused_merge_and_missing_admitted_blob_fail(self):
        self.refuse_merge = True
        with self.assertRaisesRegex(ValueError, "not confirmed"):
            self.apply()
        self.refuse_merge = False
        self.main_match = False
        with self.assertRaisesRegex(ValueError, "missing or differs"):
            self.apply()

    def test_workflow_edit_not_merged_even_with_true_archive_stub(self):
        self.changed_path = ".github/workflows/pwn.yml"
        self.assertFalse(self.apply()["eligible"])
        self.assertFalse(self.puts)


class RecoveryTests(unittest.TestCase):
    def test_rotating_recovery_skips_bad_and_merges_only_one(self):
        def api(path):
            return [{"number": n, "draft": False} for n in range(1, 31)]
        calls = []
        def attempt(api, repo, number, root, **kwargs):
            calls.append(number)
            if number == 22:
                return {"merged": True}
            raise ValueError("fixture rejected")
        with patch("admission.apply", side_effect=attempt):
            result = recover(api, "owner/commons", Path("."), slot=1)
        self.assertEqual(calls, [21, 22])
        self.assertTrue(result["merged"])

    def test_recovery_overflow_stops(self):
        def api(path):
            return [{"number": n, "draft": False} for n in range(1, 101)]
        with self.assertRaisesRegex(ValueError, "100"):
            recover(api, "owner/commons", Path("."))


if __name__ == "__main__":
    unittest.main()
