import base64
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import ValidationError

import crl
from admission import inspect

ROOT_PROBLEM = "crl:problem:riemann-hypothesis"


def make_publication(key=None, kind="RESULT", relation_target=ROOT_PROBLEM):
    key = key or Ed25519PrivateKey.generate()
    payload = {
        "profile": "crl-publication/0.3",
        "type": kind,
        "problem": ROOT_PROBLEM,
        "title": "Synthetic test publication",
        "body": "Synthetic content used only by tests.",
        "scope": "Synthetic test scope.",
        "creators": [{"name": "Test Contributor", "contribution": "Synthetic test contribution."}],
        "actor": {"kind": "human-ai", "name": "Test Actor"},
        "created_at": "2026-10-03T00:00:00Z",
        "basis_snapshot": None,
        "rights": {
            "rights_holder_statement": "Synthetic test rights holder statement.",
            "license_declared": "TEST-LICENSE"
        },
        "relations": [],
        "artifacts": [],
    }
    if kind == "QUESTION":
        payload["relations"] = [
            {"type": "subproblem-of", "target": relation_target, "scope": "Synthetic subquestion."}
        ]
    elif kind == "RESULT":
        payload["relations"] = [
            {"type": "addresses", "target": relation_target, "scope": "Synthetic answer scope."}
        ]
        payload["result_kind"] = "lemma"
        payload["answer_scope"] = "partial"
    else:
        payload["relations"] = [
            {"type": "reviews", "target": relation_target, "scope": "Synthetic review scope."}
        ]
        payload["review"] = {
            "outcome": "challenges",
            "method": "argument-check",
            "scope": "Synthetic review."
        }
    return crl.sign_publication(payload, key), key


def make_entry(publication, key, doi="10.5281/zenodo.123456"):
    payload = crl.make_index_payload(
        publication,
        doi,
        "https://zenodo.org/records/" + doi.rsplit(".", 1)[-1],
        "https://github.com/example/research",
        "a" * 40,
    )
    return crl.sign_index(payload, key)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.registry = crl.load_registry()
        self.pub, self.key = make_publication()
        self.entry = make_entry(self.pub, self.key)

    def test_publication_roundtrip(self):
        crl.validate_publication(self.pub)
        self.assertEqual(self.pub["id"], self.entry["payload"]["record_id"])

    def test_index_roundtrip(self):
        crl.validate_index(self.entry)
        crl.validate_index_graph({self.pub["id"]: self.entry}, self.registry)

    def test_tamper_rejected(self):
        entry = copy.deepcopy(self.entry)
        entry["payload"]["title"] = "changed"
        with self.assertRaisesRegex(ValueError, "signature"):
            crl.validate_index(entry)

    def test_publication_tamper_rejected(self):
        publication = copy.deepcopy(self.pub)
        publication["payload"]["body"] += " changed"
        with self.assertRaisesRegex(ValueError, "hash"):
            crl.validate_publication(publication)

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            crl.loads(b'{"a":1,"a":2}', 100)

    def test_relation_scope_required(self):
        entry = copy.deepcopy(self.entry)
        del entry["payload"]["relations"][0]["scope"]
        with self.assertRaises(ValidationError):
            crl.validate_index(entry)

    def test_rights_required(self):
        entry = copy.deepcopy(self.entry)
        del entry["payload"]["rights"]
        with self.assertRaises(ValidationError):
            crl.validate_index(entry)

    def test_specific_zenodo_doi_required(self):
        entry = copy.deepcopy(self.entry)
        entry["payload"]["archive"]["doi"] = "10.1234/example"
        with self.assertRaises(ValidationError):
            crl.validate_index(entry)

    def test_doi_and_url_must_match(self):
        entry = copy.deepcopy(self.entry)
        p = copy.deepcopy(entry["payload"])
        p["archive"]["url"] = "https://zenodo.org/records/999"
        entry = crl.sign_index(p, self.key)
        with self.assertRaisesRegex(ValueError, "disagree"):
            crl.validate_index(entry)

    def test_missing_remote_reference_allowed_but_context_partial(self):
        missing = "crl:sha256:" + "b" * 64
        p = copy.deepcopy(self.pub["payload"])
        p["actor"].pop("public_key")
        p["relations"].append(
            {"type": "depends-on", "target": missing, "scope": "Remote dependency."}
        )
        pub = crl.sign_publication(p, self.key)
        entry = make_entry(pub, self.key, "10.5281/zenodo.123457")
        index = {pub["id"]: entry}
        crl.validate_index_graph(index, self.registry)
        ctx = crl.context(pub["id"], index, self.registry)
        self.assertEqual(ctx["coverage"], "partial")
        self.assertIn(missing, ctx["missing_record_ids"])

    def test_later_review_appears_in_context(self):
        result_id = self.pub["id"]
        review_pub, review_key = make_publication(kind="REVIEW", relation_target=result_id)
        review_entry = make_entry(review_pub, review_key, "10.5281/zenodo.123458")
        index = {result_id: self.entry, review_pub["id"]: review_entry}
        crl.validate_index_graph(index, self.registry)
        ctx = crl.context(result_id, index, self.registry)
        self.assertIn(
            review_pub["id"],
            {e["payload"]["record_id"] for e in ctx["entries"]}
        )

    def test_support_is_not_acceptance(self):
        b = crl.board({self.pub["id"]: self.entry}, self.registry)
        self.assertTrue(all(q["acceptance"] == "not-assessed" for q in b["questions"]))
        self.assertEqual(b["zenodo_availability"], "not-checked")

    def test_full_result_is_candidate(self):
        p = copy.deepcopy(self.pub["payload"])
        p["actor"].pop("public_key")
        p["answer_scope"] = "full"
        pub = crl.sign_publication(p, self.key)
        entry = make_entry(pub, self.key, "10.5281/zenodo.123459")
        b = crl.board({pub["id"]: entry}, self.registry)
        root = next(q for q in b["questions"] if q["id"] == ROOT_PROBLEM)
        self.assertEqual(root["progress"], "candidate-exists")

    def test_index_path_is_sharded(self):
        path = crl.index_path(self.pub["id"])
        digest = self.pub["id"].split(":")[-1]
        self.assertEqual(path.parts[:2], (digest[:2], digest[2:4]))
        self.assertEqual(path.name, digest + ".json")

    def test_board_does_not_fetch_zenodo(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("network call")):
            crl.board({self.pub["id"]: self.entry}, self.registry)

    def test_html_is_escaped(self):
        p = copy.deepcopy(self.pub["payload"])
        p["actor"].pop("public_key")
        p["title"] = "<script>alert(1)</script>"
        pub = crl.sign_publication(p, self.key)
        entry = make_entry(pub, self.key, "10.5281/zenodo.123460")
        with tempfile.TemporaryDirectory() as d:
            crl.write_board(Path(d), {pub["id"]: entry}, self.registry)
            page = (Path(d) / "index.html").read_text()
            self.assertNotIn("<script>alert", page)
            self.assertIn("&lt;script&gt;", page)
            self.assertIn("default-src 'none'", page)

    def test_withdrawal_must_be_own_publication(self):
        other_key = Ed25519PrivateKey.generate()
        p = copy.deepcopy(self.pub["payload"])
        p["actor"] = {"kind": "human", "name": "Other"}
        p["result_kind"] = "withdrawal"
        p["answer_scope"] = "none"
        p["relations"] = [
            {"type": "withdraws", "target": self.pub["id"], "scope": "Attempted withdrawal."}
        ]
        pub = crl.sign_publication(p, other_key)
        entry = make_entry(pub, other_key, "10.5281/zenodo.123461")
        with self.assertRaisesRegex(ValueError, "someone else's"):
            crl.validate_index_graph(
                {self.pub["id"]: self.entry, pub["id"]: entry}, self.registry
            )


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.registry = crl.load_registry()
        self.pub, self.key = make_publication()
        self.entry = make_entry(self.pub, self.key)
        self.raw = json.dumps(self.entry).encode()
        self.path = "index/" + crl.index_path(self.pub["id"]).as_posix()
        self.pr = {
            "state": "open",
            "draft": False,
            "base": {"ref": "main", "repo": {"full_name": "owner/commons"}},
            "head": {"sha": "a" * 40, "repo": {"full_name": "fork/commons"}},
            "changed_files": 1,
        }
        self.mode = "100644"
        self.changed_path = self.path

    def api(self, path, method="GET", data=None):
        blob_sha = hashlib.sha1(b"blob " + str(len(self.raw)).encode() + b"\0" + self.raw).hexdigest()
        if path.endswith("/pulls/1"):
            return copy.deepcopy(self.pr)
        if "/pulls/1/files" in path:
            return [{"filename": self.changed_path, "status": "added", "sha": blob_sha}]
        if "/git/trees/" in path:
            return {
                "truncated": False,
                "tree": [{
                    "path": self.path,
                    "sha": blob_sha,
                    "mode": self.mode,
                    "type": "blob",
                    "size": len(self.raw),
                }],
            }
        if "/git/blobs/" in path:
            return {
                "encoding": "base64",
                "size": len(self.raw),
                "content": base64.b64encode(self.raw).decode(),
            }
        raise AssertionError("unexpected API access: " + path)

    def run_inspect(self, head=None):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "registry").mkdir(parents=True)
            source = Path(__file__).resolve().parents[1] / "registry/problems.json"
            (root / "registry/problems.json").write_bytes(source.read_bytes())
            (root / "index").mkdir()
            return inspect(self.api, "owner/commons", 1, root, head)

    def test_new_index_entry_is_eligible(self):
        self.assertTrue(self.run_inspect()["eligible"])

    def test_old_records_path_is_not_auto_admitted(self):
        self.changed_path = "records/aa/bb/" + "c" * 64 + ".json"
        self.assertFalse(self.run_inspect()["eligible"])

    def test_workflow_change_is_not_auto_admitted(self):
        self.changed_path = ".github/workflows/owned.yml"
        self.assertFalse(self.run_inspect()["eligible"])

    def test_multifile_change_is_not_auto_admitted(self):
        self.pr["changed_files"] = 2
        self.assertFalse(self.run_inspect()["eligible"])

    def test_executable_and_symlink_rejected(self):
        for mode in ("100755", "120000", "160000"):
            self.mode = mode
            with self.assertRaisesRegex(ValueError, "non-executable"):
                self.run_inspect()

    def test_stale_head_rejected(self):
        with self.assertRaisesRegex(ValueError, "changed"):
            self.run_inspect("c" * 40)

    def test_oversized_blob_rejected(self):
        self.raw += b" " * crl.MAX_INDEX_BYTES
        with self.assertRaisesRegex(ValueError, "oversize"):
            self.run_inspect()


if __name__ == "__main__":
    unittest.main()
