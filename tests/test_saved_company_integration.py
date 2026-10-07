"""Synthetic independent labels and counterexamples for the saved-company path."""
import contextlib
import gzip
import hashlib
import io
import json
import tempfile
import time
import unittest
from unittest.mock import patch
from dataclasses import replace
from pathlib import Path

from shirushi.contracts import load
from shirushi.evidence import EvidenceChecker
from shirushi.extraction import Candidate, extract
from shirushi.registry import acquire, find_row
from shirushi.run import main, read_records
from shirushi.snapshots import SnapshotStore
from tools.validate_saved_company import main as verify_replay

ROOT = Path(__file__).resolve().parents[1]
SUBJECT = '123456789'


class SavedCompanyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = SnapshotStore(self.root / 'snapshots')
        self.row = {'organisation_number': SUBJECT, 'name': 'Å Test AS', 'legal_form': 'AS',
                    'employees': 0, 'municipality': 'OSLO', 'municipality_number': '0301',
                    'industry_code': '62.010', 'industry_label': 'Programmering',
                    'latest_submitted_accounts': '2025', 'website': 'https://unverified.example'}
        self.inputs = self.root / 'input.jsonl'
        self.inputs.write_text(json.dumps({'organisation_number': SUBJECT}) + '\n', encoding='utf-8')
        self.archive, self.receipt_path, self.receipt = self.fixture(self.row, 'baseline')

    def fixture(self, row, name, retrieved='2026-01-01T00:00:00Z', additional=None):
        # Fixture bytes and expected values do not use the extractor or serializer.
        raw = (json.dumps(row, ensure_ascii=True) + '\n').encode()
        if additional is not None:
            raw += (json.dumps(additional) + '\n').encode()
        packed = gzip.compress(raw, mtime=0)
        archive = self.root / (name + '.jsonl.gz')
        archive.write_bytes(packed)
        receipt = {'source_class': 'frozen_registry', 'source_url': 'https://example.org/registry.jsonl.gz',
                   'retrieved_at': retrieved, 'sha256': hashlib.sha256(packed).hexdigest(),
                   'uncompressed_sha256': hashlib.sha256(raw).hexdigest()}
        receipt_path = self.root / (name + '.receipt.json')
        receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
        return archive, receipt_path, receipt

    def snapshot(self):
        return acquire(self.archive, self.receipt, SUBJECT, self.store, time.monotonic() + 10)

    def run_cli(self, name='run', archive=None, receipt=None, previous=None, extra=None):
        output, report = self.root / (name + '.jsonl'), self.root / (name + '.report.json')
        args = ['--organisations', str(self.inputs), '--registry', str(archive or self.archive),
                '--registry-receipt', str(receipt or self.receipt_path),
                '--config', str(ROOT / 'configs/local-pilot.json'), '--output', str(output),
                '--report', str(report), '--run-id', name, '--store', str(self.store.root)]
        if previous:
            args += ['--previous', str(previous)]
        if extra:
            args += extra
        with contextlib.redirect_stdout(io.StringIO()):
            code = main(args)
        return code, output, report

    def test_eight_labeled_fields_and_supported_zero(self):
        code, output, report = self.run_cli()
        self.assertEqual(code, 0)
        result = read_records(output)[0]
        expected = {'legal_name': 'Å Test AS', 'legal_form': 'AS', 'registered_employees': 0,
                    'registered_municipality': 'OSLO', 'registered_municipality_number': '0301',
                    'industry_code': '62.010', 'industry_label': 'Programmering',
                    'latest_submitted_accounts_year': '2025'}
        self.assertEqual({c['field']: c['value'] for c in result['claims']}, expected)
        self.assertEqual(result['operations']['requests'], 0)
        self.assertEqual(load(report)['accepted'], 8)
        self.assertNotIn('website', {c['field'] for c in result['claims']})
        self.assertEqual(next(e['claim_span'] for e in result['evidence'] if e['locator']['field'] == 'name'), '"\\u00c5 Test AS"')

    def test_same_snapshot_has_no_change_or_history_growth(self):
        _, first, _ = self.run_cli('first')
        code, second, _ = self.run_cli('second', previous=first)
        self.assertEqual(code, 0)
        old, new = read_records(first)[0], read_records(second)[0]
        self.assertEqual(new['changes'], [])
        self.assertEqual(new['history'], [])
        self.assertEqual(old['evidence'], new['evidence'])
        self.assertEqual([c['first_observed_at'] for c in old['claims']], [c['first_observed_at'] for c in new['claims']])

    def test_changed_value_has_one_event_and_retained_support(self):
        _, first, _ = self.run_cli('first')
        changed = dict(self.row, employees=7)
        archive, receipt, _ = self.fixture(changed, 'changed', '2026-02-01T00:00:00Z')
        code, second, _ = self.run_cli('second', archive, receipt, first)
        self.assertEqual(code, 0)
        new = read_records(second)[0]
        self.assertEqual([(c['field'], c['old_value'], c['new_value']) for c in new['changes']], [('registered_employees', 0, 7)])
        self.assertEqual(len(new['history']), 1)
        self.assertEqual(len(new['evidence']), 16)
        code, third, _ = self.run_cli('third', archive, receipt, second)
        self.assertEqual(code, 0)
        self.assertEqual(read_records(third)[0]['changes'], [])
        self.assertEqual(read_records(third)[0]['history'], new['history'])

    def test_failed_refresh_preserves_supported_values(self):
        _, first, _ = self.run_cli('first')
        code, second, _ = self.run_cli('failed', self.root / 'missing.jsonl.gz', previous=first)
        self.assertEqual(code, 1)
        old, new = read_records(first)[0], read_records(second)[0]
        self.assertEqual([(c['field'], c['value']) for c in new['claims']], [(c['field'], c['value']) for c in old['claims']])
        self.assertEqual(new['changes'], [])
        self.assertEqual(new['evidence'], old['evidence'])
        self.assertTrue(all(c['freshness'] == 'stale_after_failed_observation' for c in new['claims']))

    def test_missing_value_is_null_not_zero(self):
        archive, receipt, _ = self.fixture(dict(self.row, employees=None), 'missing')
        code, output, _ = self.run_cli(archive=archive, receipt=receipt)
        self.assertEqual(code, 0)
        claim = next(c for c in read_records(output)[0]['claims'] if c['field'] == 'registered_employees')
        self.assertIsNone(claim['value'])
        self.assertEqual(claim['availability'], 'not_available')

    def test_missing_refresh_does_not_remove_previous_value(self):
        _, first, _ = self.run_cli('first')
        archive, receipt, _ = self.fixture(dict(self.row, employees=None), 'missing', '2026-02-01T00:00:00Z')
        code, output, _ = self.run_cli('second', archive, receipt, first)
        self.assertEqual(code, 0)
        claim = next(c for c in read_records(output)[0]['claims'] if c['field'] == 'registered_employees')
        self.assertEqual(claim['value'], 0)
        self.assertEqual(claim['current_attempt_reason'], 'absent_in_frozen_row')
        self.assertEqual(read_records(output)[0]['changes'], [])

    def test_older_snapshot_cannot_overwrite_newer_support(self):
        _, first, _ = self.run_cli('first')
        archive, receipt, _ = self.fixture(dict(self.row, employees=99), 'older', '2025-01-01T00:00:00Z')
        code, output, _ = self.run_cli('second', archive, receipt, first)
        self.assertEqual(code, 0)
        claim = next(c for c in read_records(output)[0]['claims'] if c['field'] == 'registered_employees')
        self.assertEqual(claim['value'], 0)
        self.assertEqual(read_records(output)[0]['changes'], [])

    def test_checker_rejects_wrong_subject_value_type_and_field(self):
        candidate = next(c for c in extract(self.store, self.snapshot()) if c.field == 'registered_employees')
        checker = EvidenceChecker(self.store)
        for altered in (replace(candidate, organisation_number='987654321'), replace(candidate, value=11),
                        replace(candidate, value=False), replace(candidate, field='verified_website')):
            with self.subTest(altered=altered):
                self.assertFalse(checker.check(altered, SUBJECT)['accepted'])

    def test_checker_detects_row_tampering(self):
        candidate = extract(self.store, self.snapshot())[0]
        _, receipt = self.store.open(candidate.snapshot_id)
        self.store.path('objects', receipt['content_sha256']).write_bytes(b'{}')
        self.assertFalse(EvidenceChecker(self.store).check(candidate, SUBJECT)['accepted'])

    def test_checker_detects_parent_tampering(self):
        candidate = extract(self.store, self.snapshot())[0]
        _, receipt = self.store.open(candidate.snapshot_id)
        self.store.path('objects', receipt['parent_sha256']).write_bytes(b'forged')
        self.assertFalse(EvidenceChecker(self.store).check(candidate, SUBJECT)['accepted'])

    def test_forged_selected_row_is_not_archive_member(self):
        sid = self.snapshot()
        raw, receipt = self.store.open(sid)
        forged = self.store.save(raw.replace(b'Test', b'Fake'), receipt)
        candidate = Candidate(SUBJECT, 'legal_name', 'Å Fake AS', forged)
        self.assertFalse(EvidenceChecker(self.store).check(candidate, SUBJECT)['accepted'])

    def test_snapshot_is_idempotent_and_corruption_not_overwritten(self):
        sid = self.snapshot()
        self.assertEqual(self.snapshot(), sid)
        raw, receipt = self.store.open(sid)
        self.store.path('objects', receipt['content_sha256']).write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.store.save(raw, receipt)

    def test_invalid_snapshot_path_rejected(self):
        for value in ('../../secret', None, 1, 'a' * 63):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.open(value)

    def test_archive_and_expanded_hashes_checked(self):
        for key in ('sha256', 'uncompressed_sha256'):
            receipt = dict(self.receipt, **{key: '0' * 64})
            with self.subTest(key=key), self.assertRaises(ValueError):
                find_row(self.archive.read_bytes(), receipt, SUBJECT, True)

    def test_subject_absent_is_terminal_failure_not_substitution(self):
        self.inputs.write_text('{"organisation_number":"987654321"}\n', encoding='utf-8')
        code, output, _ = self.run_cli()
        self.assertEqual(code, 1)
        result = read_records(output)[0]
        self.assertEqual(result['organisation_number'], '987654321')
        self.assertTrue(all(c['value'] is None for c in result['claims']))

    def test_duplicate_registry_subject_rejected(self):
        archive, _, receipt = self.fixture(self.row, 'duplicate', additional=self.row)
        with self.assertRaises(ValueError):
            find_row(archive.read_bytes(), receipt, SUBJECT, True)

    def test_duplicate_and_malformed_inputs_are_preflight_rejections(self):
        for content in ('{"organisation_number":123456789}\n', '{"organisation_number":"123456789"}\n' * 2,
                        '{"organisation_number":"123456789","organisation_number":"987654321"}\n'):
            with self.subTest(content=content):
                self.inputs.write_text(content, encoding='utf-8')
                code, output, report = self.run_cli(str(len(list(self.root.glob('*.report.json')))))
                self.assertEqual(code, 2)
                self.assertFalse(output.exists())
                self.assertEqual(load(report)['status'], 'rejected_input')

    def test_batch_scope_is_explicitly_rejected(self):
        self.inputs.write_text('{"organisation_number":"123456789"}\n{"organisation_number":"987654321"}\n', encoding='utf-8')
        code, output, _ = self.run_cli()
        self.assertEqual(code, 2)
        self.assertFalse(output.exists())

    def test_receipt_malformed_future_and_credential_url_rejected(self):
        for receipt in ([], dict(self.receipt, retrieved_at='2099-01-01T00:00:00Z'),
                        dict(self.receipt, source_url='https://user:secret@example.org/')):
            with self.subTest(receipt=receipt):
                self.receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
                code, output, _ = self.run_cli(str(len(list(self.root.glob('*.report.json')))))
                self.assertEqual(code, 1)
                self.assertEqual(read_records(output)[0]['run']['terminal_status'], 'failed')

    def test_previous_supported_value_tampering_rejected(self):
        _, first, _ = self.run_cli('first')
        old = read_records(first)[0]
        old['claims'][0]['value'] = 'Forged legal name'
        first.write_text(json.dumps(old) + '\n', encoding='utf-8')
        code, output, _ = self.run_cli('second', previous=first)
        self.assertEqual(code, 2)
        self.assertFalse(output.exists())

    def test_previous_evidence_span_tampering_rejected(self):
        _, first, _ = self.run_cli('first')
        old = read_records(first)[0]
        old['evidence'][0]['claim_span'] = 'Unsupported quote'
        first.write_text(json.dumps(old) + '\n', encoding='utf-8')
        self.assertEqual(self.run_cli('second', previous=first)[0], 2)

    def test_no_overwrite_of_existing_outputs(self):
        _, output, report = self.run_cli()
        original = (output.read_bytes(), report.read_bytes())
        self.assertEqual(self.run_cli()[0], 2)
        self.assertEqual((output.read_bytes(), report.read_bytes()), original)

    def test_official_mode_never_runs(self):
        code, output, _ = self.run_cli(extra=['--config', str(ROOT / 'configs/official-run.template.json')])
        self.assertEqual(code, 2)
        self.assertFalse(output.exists())

    def test_verification_deadline_rejected(self):
        with self.assertRaises(ValueError):
            find_row(self.archive.read_bytes(), self.receipt, SUBJECT, True, time.monotonic() - 1)

    def test_plain_jsonl_registry_supported(self):
        plain = self.root / 'plain.jsonl'
        plain.write_bytes(gzip.decompress(self.archive.read_bytes()))
        receipt = dict(self.receipt, sha256=self.receipt['uncompressed_sha256'])
        receipt_path = self.root / 'plain.receipt.json'
        receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
        code, output, _ = self.run_cli(archive=plain, receipt=receipt_path)
        self.assertEqual(code, 0)
        self.assertEqual(read_records(output)[0]['claims'][0]['value'], 'Å Test AS')

    def test_read_only_verifier_does_not_invoke_maker(self):
        _, first, _ = self.run_cli('first')
        _, second, _ = self.run_cli('second', previous=first)
        args = ['--organisations', str(self.inputs), '--first', str(first), '--replay', str(second),
                '--store', str(self.store.root)]
        with patch('shirushi.extraction.extract', side_effect=AssertionError('Maker invoked')):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(verify_replay(args), 0)
        changed = read_records(second)[0]
        changed['changes'] = [{'kind': 'invented_removal'}]
        second.write_text(json.dumps(changed) + '\n', encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(verify_replay(args), 1)

    def test_boolean_in_registry_is_not_employee_zero(self):
        archive, receipt, _ = self.fixture(dict(self.row, employees=False), 'boolean')
        code, output, report = self.run_cli(archive=archive, receipt=receipt)
        self.assertEqual(code, 1)
        claim = next(c for c in read_records(output)[0]['claims'] if c['field'] == 'registered_employees')
        self.assertIsNone(claim['value'])
        decision = next(d for d in load(report)['decisions'] if d['field'] == 'registered_employees')
        self.assertIs(decision['candidate']['value'], False)
        self.assertEqual(decision['checker_version'], 'registry_evidence_v1')


if __name__ == '__main__':
    unittest.main()
