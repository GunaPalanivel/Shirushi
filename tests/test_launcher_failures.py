"""Real child failures cannot be accepted through an otherwise valid artifact."""
import contextlib
import gzip
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from shirushi.contracts import load
from shirushi.official import main
from shirushi.snapshots import digest


class LauncherFailureTests(unittest.TestCase):
    def launch(self, child_exit=0, mutate=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = b'{"organisation_number":"923609016","name":"Example Pumps AS","employees":0}\n'
            archive = gzip.compress(raw, mtime=0)
            (root / 'registry.jsonl.gz').write_bytes(archive)
            (root / 'receipt.json').write_text(json.dumps({'source_class': 'frozen_registry',
                'source_url': 'https://example.org/frozen', 'dataset_format': 'jsonl',
                'retrieved_at': '2026-01-01T00:00:00Z', 'sha256': digest(archive),
                'uncompressed_sha256': digest(raw)}), encoding='utf-8')
            (root / 'input.txt').write_text('923609016\n', encoding='utf-8')
            original = subprocess.run
            observed = []
            def run(command, **kwargs):
                environment = dict(kwargs['env'])
                # This portable test exercises completion, not Linux limits.
                environment.pop('SHIRUSHI_WORKER_ADDRESS_SPACE_LIMIT', None)
                kwargs['env'] = environment
                primary = 'shirushi.run' in command
                if primary and child_exit:
                    start = command.index('shirushi.run') + 1
                    wrapper = ('import os,sys; from shirushi.run import main; '
                               'result=main(sys.argv[1:]); '
                               f'sys.exit(result) if result else os._exit({child_exit})')
                    command = [sys.executable, '-X', 'dev', '-W', 'error', '-c', wrapper] + command[start:]
                kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                result = original(command, **kwargs)
                if primary:
                    if result.returncode not in (0, child_exit):
                        self.fail(json.dumps(load(root / 'work/shard-0000/report.json')['errors']))
                    observed.append(result.returncode)
                    if mutate:
                        path = root / 'work/shard-0000/report.json'
                        report = load(path)
                        mutate(report)
                        path.write_text(json.dumps(report), encoding='utf-8')
                return result
            guard = {'snapshot_store_limit_bytes': 8_000_000_000,
                     'worker_address_space_limit_bytes': 8_000_000_000}
            with contextlib.ExitStack() as stack:
                stack.enter_context(patch.dict(os.environ))
                stack.enter_context(patch('shirushi.official.resource_guard', return_value=guard))
                stack.enter_context(patch('shirushi.official.subprocess.run', side_effect=run))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                if sys.platform != 'linux':
                    stack.enter_context(patch.dict(sys.modules, {'resource': SimpleNamespace(
                        RUSAGE_SELF=0, RUSAGE_CHILDREN=1,
                        getrusage=lambda _kind: SimpleNamespace(ru_maxrss=0))}))
                code = main(['--organisations', str(root / 'input.txt'), '--registry', str(root / 'registry.jsonl.gz'),
                    '--registry-receipt', str(root / 'receipt.json'), '--output', str(root / 'output.jsonl'),
                    '--report', str(root / 'report.json'), '--work-dir', str(root / 'work'),
                    '--cutoff', '2026-01-01T00:00:00Z', '--run-id', 'launcher-control', '--offline'])
            return code, load(root / 'report.json'), (root / 'output.jsonl').exists(), observed

    def test_successful_real_child_and_audit_remain_completed(self):
        code, report, output, observed = self.launch()
        self.assertEqual((code, report['status'], output, observed), (0, 'completed', True, [0]))

    def test_actual_exit_17_after_writing_valid_output_fails_launcher(self):
        code, report, output, observed = self.launch(child_exit=17)
        self.assertEqual((code, report['status'], output, observed), (1, 'failed', False, [17]))
        self.assertFalse(report['artifact_complete'])
        self.assertIn('code 17', report['reason'])

    def test_exit_zero_cannot_override_failed_report_or_worker(self):
        for change in (lambda r: r.update(status='failed'),
                       lambda r: r['supervision'].update(worker_exit_code=17),
                       lambda r: r['supervision'].update(worker_completed=False)):
            with self.subTest(change=change):
                code, report, output, observed = self.launch(mutate=change)
                self.assertEqual((code, report['status'], output, observed), (1, 'failed', False, [0]))


class LiveSmokeFailureTests(unittest.TestCase):
    def test_failed_launcher_gets_a_failure_receipt_without_requiring_output(self):
        from tools import validate_official_live
        for exit_code in (0, 17):
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / 'smoke'
                def failed_child(_command, **_kwargs):
                    (output / 'report.json').write_text(json.dumps({'status': 'failed',
                        'artifact_complete': False, 'reason': 'Failed shard', 'child_exit_code': 17}), encoding='utf-8')
                    return SimpleNamespace(returncode=exit_code)
                args = ['validate_official_live', '--output-dir', str(output),
                        '--registry', 'supplied.csv.gz', '--registry-receipt', 'receipt.json']
                with patch.object(sys, 'argv', args), patch.object(validate_official_live.subprocess,
                        'run', side_effect=failed_child), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(validate_official_live.main(), 1)
                receipt = load(output / 'validation.json')
                self.assertEqual(receipt['status'], 'FAIL')
                self.assertEqual(receipt['launcher_report']['child_exit_code'], 17)
                self.assertIsNone(receipt['official_score'])
