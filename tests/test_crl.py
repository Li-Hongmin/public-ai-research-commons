import base64
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import ValidationError
from tools import crl
from tools.admission import inspect
from examples.demo import make_demo


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.records, self.registry = make_demo()
        self.q = next(r for r in self.records.values() if r['payload']['type'] == 'QUESTION')
        self.r = next(r for r in self.records.values() if r['payload']['type'] == 'RESULT')
        self.c = next(r for r in self.records.values() if r['payload']['type'] == 'REVIEW')

    def ressign(self, record, edit):
        p = copy.deepcopy(record['payload'])
        p['actor'].pop('public_key')
        edit(p)
        return crl.sign(p, Ed25519PrivateKey.generate())

    def test_demo_roundtrip(self):
        self.assertEqual(len(self.records), 5)
        crl.validate_graph(self.records, self.registry)
        for r in self.records.values():
            crl.validate_record(crl.loads(json.dumps(r).encode()))

    def test_tamper_rejected(self):
        r = copy.deepcopy(self.r); r['payload']['body'] += ' changed'
        with self.assertRaisesRegex(ValueError, 'hash'): crl.validate_record(r)

    def test_recomputed_hash_does_not_forge_signature(self):
        r = copy.deepcopy(self.r); r['payload']['body'] += ' changed'
        r['id'] = 'crl:sha256:' + crl.digest(r['payload'])
        with self.assertRaisesRegex(ValueError, 'signature'): crl.validate_record(r)

    def test_duplicate_keys_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate'): crl.loads(b'{"a":1,"a":2}')

    def test_nan_rejected(self):
        with self.assertRaises(ValueError): crl.loads(b'{"x":NaN}')

    def test_bad_utf8_rejected(self):
        with self.assertRaises(ValueError): crl.loads(b'"\xff"')

    def test_nested_json_rejected(self):
        with self.assertRaises(ValueError): crl.loads(b'[' * 25 + b'0' + b']' * 25)

    def test_byte_limit(self):
        with self.assertRaises(ValueError): crl.loads(b' ' * (crl.MAX_BYTES + 1))

    def test_unknown_fields_rejected(self):
        r = copy.deepcopy(self.q); r['execute'] = 'arbitrary.sh'
        with self.assertRaises(ValidationError): crl.validate_record(r)

    def test_missing_reference_rejected(self):
        records = dict(self.records); del records[self.q['id']]
        with self.assertRaisesRegex(ValueError, 'missing reference'): crl.validate_graph(records, self.registry)

    def test_root_allowlist(self):
        with self.assertRaisesRegex(ValueError, 'not registered'): crl.validate_graph(self.records, {'programs': []})

    def test_wrong_relation_type_rejected(self):
        r = self.ressign(self.q, lambda p: p['relations'].append({'type': 'depends-on', 'target': self.q['id']}))
        with self.assertRaisesRegex(ValueError, 'wrong type'): crl.validate_graph({**self.records, r['id']: r}, self.registry)

    def test_no_foreign_withdrawal(self):
        def edit(p):
            p.update(result_kind='withdrawal', answer_scope='none', relations=[{'type': 'withdraws', 'target': self.r['id']}])
        r = self.ressign(self.r, edit)
        with self.assertRaisesRegex(ValueError, "someone else's"): crl.validate_graph({**self.records, r['id']: r}, self.registry)

    def test_own_withdrawal_preserves_record(self):
        key = Ed25519PrivateKey.generate()
        p = copy.deepcopy(self.r['payload']); p['actor'].pop('public_key')
        original = crl.sign(p, key)
        p.update(result_kind='withdrawal', answer_scope='none', relations=[{'type': 'withdraws', 'target': original['id']}])
        withdraw = crl.sign(p, key)
        records = {**self.records, original['id']: original, withdraw['id']: withdraw}
        crl.validate_graph(records, self.registry)
        b = crl.board(records, self.registry)
        self.assertIn(original['id'], b['withdrawn_ids'])
        self.assertIn(original['id'], [r['id'] for r in b['records']])

    def test_revision_carries_known_objection(self):
        revision = next(r for r in self.records.values() if any(e['type'] == 'revises' for e in r['payload']['relations']))
        ids = {r['id'] for r in crl.context(revision['id'], self.records, self.registry)['records']}
        self.assertIn(self.c['id'], ids)
        self.assertIn(self.r['id'], ids)

    def test_later_review_appears_without_editing_claim(self):
        before = crl.context(self.r['id'], {self.q['id']: self.q, self.r['id']: self.r}, self.registry)
        after = crl.context(self.r['id'], self.records, self.registry)
        self.assertNotEqual(before['snapshot']['id'], after['snapshot']['id'])
        self.assertIn(self.c['id'], {r['id'] for r in after['records']})

    def test_partial_context_is_labelled(self):
        records = dict(self.records); del records[self.q['id']]
        ctx = crl.context(self.r['id'], records, self.registry)
        self.assertEqual(ctx['coverage'], 'partial')
        self.assertIn(self.q['id'], ctx['missing_record_ids'])

    def test_snapshot_independent_of_map_order(self):
        rev = dict(reversed(list(self.records.items())))
        self.assertEqual(crl.snapshot(self.records, self.registry), crl.snapshot(rev, self.registry))

    def test_registry_bound_to_snapshot(self):
        registry = copy.deepcopy(self.registry); registry['note'] = 'different coverage'
        self.assertNotEqual(crl.snapshot(self.records, registry)['id'], crl.snapshot(self.records, self.registry)['id'])

    def test_support_is_not_acceptance(self):
        b = crl.board(self.records, self.registry)
        self.assertTrue(all(q['acceptance'] == 'not-assessed' for q in b['questions']))
        self.assertEqual(b['artifact_availability'], 'not-checked')

    def test_partial_result_is_not_full_candidate(self):
        r = self.ressign(self.r, lambda p: p.update(answer_scope='partial'))
        b = crl.board({self.q['id']: self.q, r['id']: r}, self.registry)
        self.assertTrue(all(q['progress'] == 'no-candidate' for q in b['questions']))

    def test_html_is_escaped(self):
        q = self.ressign(self.q, lambda p: p.update(title='<script>alert(1)</script>', body='<img src=x onerror=alert(1)>'))
        with tempfile.TemporaryDirectory() as d:
            crl.write_board(Path(d), {q['id']: q}, self.registry)
            page = (Path(d) / 'index.html').read_text()
            self.assertNotIn('<script>', page)
            self.assertIn('&lt;script&gt;', page)
            self.assertIn("default-src 'none'", page)

    def test_artifact_scheme_rejected(self):
        r = self.ressign(self.r, lambda p: p.update(artifacts=[{'uri': 'javascript:alert(1)', 'sha256': '0'*64, 'description': 'malicious'}]))
        with self.assertRaises(ValidationError): crl.validate_record(r)

    def test_artifact_is_never_fetched(self):
        r = self.ressign(self.r, lambda p: p.update(artifacts=[{'uri': 'https://example.invalid/proof.py', 'sha256': '0'*64, 'description': 'not fetched'}]))
        with patch('urllib.request.urlopen', side_effect=AssertionError('network call')):
            crl.validate_graph({**self.records, r['id']: r}, self.registry)
            self.assertEqual(crl.context(r['id'], {**self.records, r['id']: r}, self.registry)['artifact_availability'], 'not-checked')

    def test_filename_and_symlink_checks(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'wrong.json').write_text(json.dumps(self.q))
            with self.assertRaisesRegex(ValueError, 'filename'): crl.load_records(root)
            (root / 'wrong.json').unlink()
            (root / 'link').symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'symlink'): crl.load_records(root)

    def test_jcs_utf16_and_numbers(self):
        self.assertEqual(crl.canonical({'\ue000': 1, '\U00010000': 2}), '{"\U00010000":2,"\ue000":1}'.encode())
        self.assertEqual(crl.canonical([1e-7, 1e-6, -0.0, 1e20]), b'[1e-7,0.000001,0,100000000000000000000]')


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        records, self.registry = make_demo()
        self.record = next(r for r in records.values() if r['payload']['type'] == 'QUESTION')
        self.raw = json.dumps(self.record).encode()
        self.path = 'records/' + crl.record_path(self.record['id']).as_posix()
        self.pr = {'state': 'open', 'draft': False, 'base': {'ref': 'main', 'repo': {'full_name': 'owner/commons'}},
                   'head': {'sha': 'a'*40, 'repo': {'full_name': 'fork/commons'}}, 'changed_files': 1}
        self.mode = '100644'
        self.changed_path = self.path

    def api(self, path, method='GET', data=None):
        if path.endswith('/pulls/1'): return copy.deepcopy(self.pr)
        if '/pulls/1/files' in path: return [{'filename': self.changed_path, 'status': 'added', 'sha': 'b'*40}]
        if '/git/trees/' in path: return {'truncated': False, 'tree': [{'path': self.path, 'sha': 'b'*40, 'mode': self.mode, 'type': 'blob', 'size': len(self.raw)}]}
        if '/git/blobs/' in path: return {'encoding': 'base64', 'size': len(self.raw), 'content': base64.b64encode(self.raw).decode()}
        raise AssertionError('unexpected API access: ' + path)

    def run_inspect(self, head=None):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / 'registry').mkdir()
            (root / 'registry/problems.json').write_text(json.dumps(self.registry))
            return inspect(self.api, 'owner/commons', 1, root, head)

    def test_new_record_is_eligible(self):
        self.assertTrue(self.run_inspect()['eligible'])

    def test_workflow_change_is_not_auto_admitted(self):
        self.changed_path = '.github/workflows/owned.yml'
        self.assertFalse(self.run_inspect()['eligible'])

    def test_multifile_change_is_not_auto_admitted(self):
        self.pr['changed_files'] = 2
        self.assertFalse(self.run_inspect()['eligible'])

    def test_executable_and_symlink_rejected(self):
        for mode in ('100755', '120000', '160000'):
            self.mode = mode
            with self.assertRaisesRegex(ValueError, 'non-executable'): self.run_inspect()

    def test_stale_head_rejected(self):
        with self.assertRaisesRegex(ValueError, 'changed'): self.run_inspect('c'*40)

    def test_oversized_blob_rejected(self):
        self.raw += b' ' * crl.MAX_BYTES
        with self.assertRaisesRegex(ValueError, 'oversize'): self.run_inspect()


if __name__ == '__main__':
    unittest.main()
