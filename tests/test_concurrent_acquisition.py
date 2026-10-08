"""Concurrent limits, cancellation and single collector regressions."""
import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from shirushi.contracts import ROOT, load, validate_envelopes
from shirushi.fetch import Budget, BudgetExceeded, Fetcher
from shirushi.live import worker


class ConcurrentAcquisitionTests(unittest.TestCase):
    def config(self, **changes):
        result = load(ROOT / 'configs/local-live.json')
        result.update(min_host_interval_seconds=0, max_retries=0, **changes)
        return result

    def test_parallel_waiters_cannot_overcharge_request_cap(self):
        budget = Budget(self.config(request_budget=1), time.monotonic() + 3)
        budget.config['min_host_interval_seconds'] = 0.02
        budget.last_start['example.com'] = time.monotonic()
        def start():
            try:
                budget.start('example.com')
                return True
            except BudgetExceeded:
                return False
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(lambda _: start(), range(12)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(budget.requests, 1)

    def test_byte_reservations_are_atomic(self):
        budget = Budget(self.config(max_total_bytes=10), time.monotonic() + 3)
        def consume():
            try:
                budget.consume(3)
                return True
            except BudgetExceeded:
                return False
        with ThreadPoolExecutor(max_workers=12) as pool:
            self.assertEqual(sum(pool.map(lambda _: consume(), range(12))), 3)
        self.assertEqual(budget.bytes, 9)

    def test_stream_read_reservations_prevent_unaccounted_parallel_bytes(self):
        budget = Budget(self.config(max_total_bytes=10), time.monotonic() + 3)
        first = budget.reserve_read(8)
        second = budget.reserve_read(8)
        self.assertEqual((first, second), (8, 2))
        self.assertEqual(budget.remaining_bytes(), 0)
        budget.finish_read(first, 3)
        third = budget.reserve_read(8)
        self.assertEqual(third, 5)
        budget.finish_read(second, 2)
        budget.finish_read(third, 5)
        self.assertEqual(budget.bytes, 10)
        self.assertEqual(budget.reserved_bytes, 0)
        with self.assertRaises(BudgetExceeded):
            budget.reserve_read(1)

    def test_spacing_and_host_concurrency_survive_parallel_requests(self):
        config = self.config(per_host_concurrency=2)
        config['min_host_interval_seconds'] = 0.02
        budget = Budget(config, time.monotonic() + 3)
        starts, lock = [], threading.Lock()
        def transport(*args):
            with lock:
                starts.append(time.monotonic())
            time.sleep(0.03)
            return 200, {}, b'ok'
        fetcher = Fetcher(budget, transport)
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: fetcher.get('https://example.com/', {'example.com'}), range(8)))
        self.assertTrue(all(b-a >= 0.018 for a, b in zip(starts, starts[1:])))
        self.assertEqual(budget.peak_active, 2)
        self.assertEqual(budget.requests, 8)

    def test_robots_is_single_flight_without_global_network_lock(self):
        budget = Budget(self.config(per_host_concurrency=4), time.monotonic() + 3)
        seen, lock = [], threading.Lock()
        def transport(url, *args):
            with lock:
                seen.append(url)
            time.sleep(0.01)
            return 200, {}, b'User-agent: *\nAllow: /\n' if url.endswith('robots.txt') else b'ok'
        fetcher = Fetcher(budget, transport)
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: fetcher.get('https://example.com/', {'example.com'}, robots=True), range(8)))
        self.assertEqual(seen.count('https://example.com/robots.txt'), 1)
        self.assertEqual(budget.requests, 9)
        self.assertGreater(budget.peak_active, 1)

    def test_cancel_releases_host_waiters_and_prevents_new_attempts(self):
        budget = Budget(self.config(), time.monotonic() + 3)
        entered, release = threading.Event(), threading.Event()
        def transport(*args):
            entered.set()
            release.wait(1)
            return 200, {}, b'ok'
        fetcher = Fetcher(budget, transport)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(fetcher.get, 'https://example.com/', {'example.com'})
            self.assertTrue(entered.wait(1))
            second = pool.submit(fetcher.get, 'https://example.com/', {'example.com'})
            budget.cancel()
            with self.assertRaises(BudgetExceeded):
                second.result(timeout=1)
            release.set()
            first.result(timeout=1)
        self.assertEqual(budget.requests, 1)

    def test_collector_alone_sends_and_assembles_in_order(self):
        subjects = ['923609016', '989061593', '914778271']
        config = self.config(workers=3, enabled_sources=['brreg_entity'])
        caller, frames, active, peak, lock = threading.get_ident(), [], 0, 0, threading.Lock()
        class Connection:
            def send(self, frame):
                if threading.get_ident() != caller:
                    raise AssertionError('Concurrent Pipe writer')
                frames.append(frame)
            def close(self):
                pass
        def get(fetcher, url, hosts, robots=False):
            nonlocal active, peak
            with fetcher.budget.request('data.brreg.no'):
                with lock:
                    active += 1
                    peak = max(peak, active)
                time.sleep(0.015)
                with lock:
                    active -= 1
                subject = url.rsplit('/', 1)[1]
                raw = json.dumps({'organisasjonsnummer': subject, 'navn': 'Test AS',
                                  '_links': {'self': {'href': url}}}).encode()
                fetcher.budget.consume(len(raw))
                return raw, {'source_url': url, 'effective_url': url, 'http_status': 200,
                             'retrieved_at': '2026-10-08T08:00:00Z', 'source_origin': 'data.brreg.no',
                             'content_type': 'application/json'}
        config['per_host_concurrency'] = 3
        with tempfile.TemporaryDirectory() as root, patch('shirushi.fetch.Fetcher.get', get):
            worker(Connection(), {'store': Path(root), 'subjects': subjects, 'previous': {}, 'config': config,
                                 'deadline': time.monotonic() + 3, 'started_at': '2026-10-08T08:00:00Z',
                                 'run_id': 'concurrent-test'})
        self.assertEqual([f for f in frames if f[0] == 'fatal'], [])
        outputs = [f[2]['envelope'] for f in frames if f[0] == 'result']
        self.assertEqual([e['organisation_number'] for e in outputs], subjects)
        self.assertEqual(validate_envelopes([{'organisation_number': s} for s in subjects], outputs,
                                          load(ROOT / 'contracts/company-envelope.v1.json')), [])
        self.assertEqual(peak, 3)
        self.assertEqual(sum(e['operations']['requests'] for e in outputs), 3)

