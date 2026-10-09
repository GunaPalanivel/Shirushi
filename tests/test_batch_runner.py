"""Batch membership, process faults, saved roles and atomic publication controls."""
import contextlib
import gzip
import hashlib
import io
import json
import os
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from shirushi.artifacts import publish_new
from shirushi.batch import envelope, failure_decisions, run_supervised
from shirushi.contracts import load
from shirushi.extraction import Candidate
from shirushi.roles import acquire_role, check_role, propose_roles
from shirushi.run import main, read_records
from shirushi.snapshots import SnapshotStore
from shirushi_eval.score import family_metric
from tools.prepare_development_corpus import sample

ROOT = Path(__file__).resolve().parents[1]


def crash_worker(connection, job):
    os._exit(7)


def blocked_worker(connection, job):
    time.sleep(30)


def checkpoint_then_block_worker(connection, job):
    subject = job['subjects'][0]
    result = envelope(subject, job['run_id'], job['started_at'], [], error=None)
    connection.send(('checkpoint', subject, {'envelope': result, 'decisions': [], 'attempts': []}))
    connection.send(('accounting', None, {'requests': 3, 'response_bytes': 42, 'third_party_cost_usd': 0}))
    time.sleep(30)


def reordered_worker(connection, job):
    for subject in reversed(job['subjects']):
        result = envelope(subject, job['run_id'], job['started_at'], failure_decisions(None, 'synthetic_failure'),
                          error='synthetic_failure')
        connection.send(('result', subject, {'envelope': result, 'decisions': [], 'attempts': []}))
    connection.send(('done', None, None))


def partial_crash_worker(connection, job):
    subject = job['subjects'][0]
    result = envelope(subject, job['run_id'], job['started_at'], failure_decisions(None, 'synthetic_failure'), error='synthetic_failure')
    connection.send(('result', subject, {'envelope': result, 'decisions': [], 'attempts': []}))
    connection.close()
    os._exit(9)


def wrong_subject_worker(connection, job):
    result = envelope('999999999', job['run_id'], job['started_at'], failure_decisions(None, 'fixture_failure'), error='fixture_failure')
    connection.send(('result', job['subjects'][0], {'envelope': result, 'decisions': [], 'attempts': []}))
    connection.close()


def done_then_crash_worker(connection, job):
    for subject in job['subjects']:
        result = envelope(subject, job['run_id'], job['started_at'], [])
        connection.send(('result', subject, {'envelope': result, 'decisions': [], 'attempts': []}))
    connection.send(('done', None, None))
    connection.close()
    os._exit(17)


def done_then_block_worker(connection, job):
    for subject in job['subjects']:
        result = envelope(subject, job['run_id'], job['started_at'], [])
        connection.send(('result', subject, {'envelope': result, 'decisions': [], 'attempts': []}))
    connection.send(('done', None, None))
    time.sleep(30)


class BatchRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.subjects = [str(123450000 + i) for i in range(20)]
        self.rows = [{'organisation_number': subject, 'name': f'Fixture {i} AS', 'legal_form': 'AS',
                      'employees': i, 'municipality': 'OSLO', 'municipality_number': '0301',
                      'industry_code': '62.010', 'industry_label': 'Synthetic',
                      'latest_submitted_accounts': '2025'} for i, subject in enumerate(self.subjects)]
        raw = b''.join((json.dumps(r) + '\n').encode() for r in self.rows)
        archive = gzip.compress(raw, mtime=0)
        self.registry = self.root / 'registry.jsonl.gz'
        self.registry.write_bytes(archive)
        self.receipt = self.root / 'receipt.json'
        self.receipt.write_text(json.dumps({'source_class': 'frozen_registry', 'source_url': 'https://example.org/fixture',
                                         'retrieved_at': '2026-01-01T00:00:00Z',
                                         'sha256': hashlib.sha256(archive).hexdigest(),
                                         'uncompressed_sha256': hashlib.sha256(raw).hexdigest()}), encoding='utf-8')
        self.inputs = self.root / 'input.jsonl'
        self.inputs.write_text(''.join(json.dumps({'organisation_number': s}) + '\n' for s in self.subjects), encoding='utf-8')
        self.store = SnapshotStore(self.root / 'snapshots')
        self.contract = load(ROOT / 'contracts/company-envelope.v1.json')

    def cli(self, name='baseline', previous=None, extra=None):
        output, report = self.root / (name + '.jsonl'), self.root / (name + '-report.json')
        args = ['--organisations', str(self.inputs), '--registry', str(self.registry), '--registry-receipt', str(self.receipt),
                '--config', str(ROOT / 'configs/local-pilot.json'), '--store', str(self.store.root),
                '--output', str(output), '--report', str(report), '--run-id', name]
        if previous:
            args += ['--previous', str(previous)]
        args += extra or []
        with contextlib.redirect_stdout(io.StringIO()):
            code = main(args)
        return code, output, report

    def job(self, seconds=5):
        return {'subjects': self.subjects, 'deadline': time.monotonic() + seconds,
                'run_id': 'fault-fixture', 'started_at': '2026-01-01T00:00:00Z'}

    def test_twenty_company_cli_keeps_order_and_reference_values(self):
        code, output, report = self.cli()
        self.assertEqual(code, 0)
        results = read_records(output)
        self.assertEqual([e['organisation_number'] for e in results], self.subjects)
        self.assertEqual([next(c['value'] for c in e['claims'] if c['field'] == 'registered_employees') for e in results], list(range(20)))
        self.assertEqual(load(report)['accepted'], 160)
        self.assertEqual(load(report)['output_sha256'], hashlib.sha256(output.read_bytes()).hexdigest())

    def test_stalled_checkpoint_preserves_accounting_and_1500_terminal_slots(self):
        self.subjects = [str(123450000 + i) for i in range(1500)]
        job = self.job(seconds=1)
        results, reports, supervision = run_supervised(job, self.contract, checkpoint_then_block_worker)
        self.assertEqual([r['organisation_number'] for r in results], self.subjects)
        self.assertEqual(len(reports), 1500)
        self.assertTrue(all(r['run']['terminal_status'] == 'failed' for r in results))
        self.assertEqual(supervision['operations']['requests'], 3)
        self.assertEqual(supervision['operations']['response_bytes'], 42)

    def test_batch_replay_no_change_or_history_growth(self):
        _, first, _ = self.cli('first')
        code, second, _ = self.cli('second', previous=first)
        self.assertEqual(code, 0)
        self.assertTrue(all(not e['changes'] and not e['history'] for e in read_records(second)))

    def test_one_bad_subject_does_not_drop_other_nineteen(self):
        self.subjects[-1] = '987654321'
        self.inputs.write_text(''.join(json.dumps({'organisation_number': s}) + '\n' for s in self.subjects), encoding='utf-8')
        code, output, _ = self.cli()
        self.assertEqual(code, 1)
        results = read_records(output)
        self.assertEqual([e['organisation_number'] for e in results], self.subjects)
        self.assertEqual(sum(e['run']['terminal_status'] == 'completed' for e in results), 19)

    def test_missing_batch_source_preserves_all_previous_support(self):
        _, first, _ = self.cli('first')
        code, second, _ = self.cli('failed', first, ['--registry', str(self.root / 'absent.jsonl.gz')])
        self.assertEqual(code, 1)
        for before, after in zip(read_records(first), read_records(second)):
            self.assertEqual([(c['field'], c['value']) for c in before['claims']], [(c['field'], c['value']) for c in after['claims']])
            self.assertEqual(before['evidence'], after['evidence'])
            self.assertFalse(after['changes'])

    def test_failed_refresh_verifier_allows_unknown_observation_to_fail(self):
        from tools.validate_saved_company import main as verify
        self.rows[0]['employees'] = None
        raw = b''.join((json.dumps(r) + '\n').encode() for r in self.rows)
        archive = gzip.compress(raw, mtime=0)
        self.registry.write_bytes(archive)
        receipt = load(self.receipt)
        receipt.update(sha256=hashlib.sha256(archive).hexdigest(),
                       uncompressed_sha256=hashlib.sha256(raw).hexdigest())
        self.receipt.write_text(json.dumps(receipt), encoding='utf-8')
        _, first, _ = self.cli('first-null')
        code, second, _ = self.cli('failed-null', first, ['--registry', str(self.root / 'absent.jsonl.gz')])
        self.assertEqual(code, 1)
        with contextlib.redirect_stdout(io.StringIO()):
            result = verify(['--organisations', str(self.inputs), '--first', str(first), '--replay', str(second),
                             '--store', str(self.store.root), '--expect', 'failed-refresh'])
        self.assertEqual(result, 0)

    def test_input_limit_is_configuration_not_embedded_company_list(self):
        self.inputs.write_text(self.inputs.read_text(encoding='utf-8') + '{"organisation_number":"987654321"}\n', encoding='utf-8')
        code, output, _ = self.cli()
        self.assertEqual(code, 2)
        self.assertFalse(output.exists())

    def test_crash_and_partial_crash_leave_twenty_failed_slots(self):
        for target in (crash_worker, partial_crash_worker):
            with self.subTest(target=target.__name__):
                results, _, metadata = run_supervised(self.job(), self.contract, target)
                self.assertEqual([e['organisation_number'] for e in results], self.subjects)
                self.assertTrue(all(e['run']['terminal_status'] == 'failed' for e in results))
                self.assertFalse(metadata['worker_completed'])
                if target is partial_crash_worker:
                    self.assertEqual(results[0]['errors'][0]['reason'], 'synthetic_failure')

    def test_blocked_worker_is_terminated_without_waiting_for_sleep(self):
        start = time.monotonic()
        results, _, metadata = run_supervised(self.job(.3), self.contract, blocked_worker)
        self.assertLess(time.monotonic() - start, 2)
        self.assertEqual(len(results), 20)
        self.assertIn('budget', metadata['unfinished_reason'])

    def test_checkpoint_order_never_changes_input_order(self):
        results, _, metadata = run_supervised(self.job(), self.contract, reordered_worker)
        self.assertEqual([e['organisation_number'] for e in results], self.subjects)
        self.assertTrue(metadata['worker_completed'])

    def test_done_message_cannot_hide_crash_or_forced_termination(self):
        for target in (done_then_crash_worker, done_then_block_worker):
            with self.subTest(target=target.__name__):
                results, _, metadata = run_supervised(self.job(), self.contract, target)
                self.assertFalse(metadata['worker_completed'])
                self.assertNotEqual(metadata['worker_exit_code'], 0)
                self.assertTrue(all(e['run']['terminal_status'] == 'failed' for e in results))
                self.assertTrue(all(any(x['stage'] == 'supervisor' for x in e['errors']) for e in results))

    def test_wrong_company_checkpoint_cannot_be_published(self):
        results, _, metadata = run_supervised(self.job(), self.contract, wrong_subject_worker)
        self.assertEqual([e['organisation_number'] for e in results], self.subjects)
        self.assertIn('contract', metadata['unfinished_reason'])

    def role_snapshot(self):
        subject = self.subjects[0]
        url = f'https://data.brreg.no/enhetsregisteret/api/enheter/{subject}/roller'
        body = {'_links': {'self': {'href': url}, 'enhet': {'href': url[:-7]}},
                'rollegrupper': [{'sistEndret': '2026-01-01', 'roller': [
                    {'type': {'kode': 'DAGL', 'beskrivelse': 'Daglig leder'}, 'avregistrert': False,
                     'person': {'erDoed': False, 'fodselsdato': '1980-01-01',
                                'navn': {'fornavn': 'A', 'etternavn': 'Person'}}}]}]}
        raw = json.dumps(body).encode()
        path = self.root / 'roles.json'
        path.write_bytes(raw)
        entry = {'organisation_number': subject, 'source_class': 'brreg_roles_snapshot', 'path': 'roles.json',
                 'source_url': url, 'effective_url': url, 'http_status': 200,
                 'access_policy': 'brreg-open-data-nlod-2.0', 'retrieved_at': '2026-01-02T00:00:00Z',
                 'sha256': hashlib.sha256(raw).hexdigest()}
        sid = acquire_role(entry, self.root / 'manifest.json', self.store, 100000)
        return sid, body, entry

    def test_role_acceptance_has_context_but_exports_no_birth_date(self):
        sid, _, _ = self.role_snapshot()
        candidate = propose_roles(self.store, sid)[0]
        decision = check_role(self.store, candidate, self.subjects[0])
        self.assertTrue(decision['accepted'])
        self.assertEqual(decision['claim']['value'], {'role_code': 'DAGL', 'role_label': 'Daglig leder', 'person_name': 'A Person'})
        self.assertNotIn('1980-01-01', json.dumps(decision))

    def test_role_checker_rejects_other_subject_inactive_wrong_value_and_locator(self):
        sid, body, entry = self.role_snapshot()
        candidate = propose_roles(self.store, sid)[0]
        for bad in (replace(candidate, organisation_number='987654321'), replace(candidate, value={'person_name': 'B'}),
                    replace(candidate, locator={'group_index': -1, 'role_index': 0})):
            with self.subTest(candidate=bad):
                self.assertFalse(check_role(self.store, bad, self.subjects[0])['accepted'])
        body['rollegrupper'][0]['roller'][0]['avregistrert'] = True
        raw = json.dumps(body).encode()
        new_sid = self.store.save(raw, dict(entry, snapshot_kind='brreg_roles_json', sha256=hashlib.sha256(raw).hexdigest()))
        self.assertFalse(check_role(self.store, replace(candidate, snapshot_id=new_sid), self.subjects[0])['accepted'])

    def test_role_source_link_to_parent_is_rejected(self):
        sid, body, entry = self.role_snapshot()
        candidate = propose_roles(self.store, sid)[0]
        body['_links']['enhet']['href'] = 'https://data.brreg.no/enhetsregisteret/api/enheter/987654321'
        raw = json.dumps(body).encode()
        new_sid = self.store.save(raw, dict(entry, snapshot_kind='brreg_roles_json', sha256=hashlib.sha256(raw).hexdigest()))
        self.assertFalse(check_role(self.store, replace(candidate, snapshot_id=new_sid), self.subjects[0])['accepted'])

    def test_atomic_artifact_never_overwrites_or_exposes_partial_bytes(self):
        target = self.root / 'artifact.json'
        publish_new(target, b'complete')
        with self.assertRaises(FileExistsError):
            publish_new(target, b'replacement')
        self.assertEqual(target.read_bytes(), b'complete')
        with patch('shirushi.artifacts.os.link', side_effect=OSError('simulated interruption')):
            with self.assertRaises(OSError):
                publish_new(self.root / 'unpublished.json', b'partial')
        self.assertFalse((self.root / 'unpublished.json').exists())
        self.assertEqual(list(self.root.glob('.pending-*')), [])

    def test_official_mixture_and_unmeasured_denominator(self):
        self.assertAlmostEqual(family_metric(20, 15, 50, 30)['mixture'], .705)
        self.assertAlmostEqual(family_metric(20, 20, 50, 10)['mixture'], .76)
        self.assertIsNone(family_metric(0, 0, 0, 0)['mixture'])
        with self.assertRaises(ValueError):
            family_metric(20, 21, 50, 30)

    def test_sampling_is_repeatable_proportional_and_host_disjoint(self):
        rows = [dict(r, website='https://same.example') if i < 2 else dict(r, website='') for i, r in enumerate(self.rows)]
        first, receipt = sample(rows, total=10)
        second, _ = sample(list(reversed(rows)), total=10)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 10)
        self.assertLessEqual(sum(r['registered_host_group'] == 'same.example' for r in first), 1)
        self.assertEqual(sum(r['selected'] for r in receipt['strata']), 10)


if __name__ == '__main__':
    unittest.main()
