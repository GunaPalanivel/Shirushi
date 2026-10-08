"""Discovery is bounded, billed, scoped and never treats snippets as facts."""
import json
import time
import unittest
from urllib.parse import parse_qs, urlsplit

from shirushi.contracts import ROOT, load
from shirushi.discovery import BraveDiscovery, COST_PER_ATTEMPT_USD
from shirushi.fetch import Budget, BudgetExceeded, Fetcher, SourceUnavailable


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        config = load(ROOT / 'configs/local-live.json')
        config.update(third_party_cost_usd=0.01, min_host_interval_seconds=0, max_retries=0)
        self.budget = Budget(config, time.monotonic() + 3)
        self.access = {'max_candidates': 3, 'max_queries_per_company': 2, 'request_interval_seconds': 0.02}

    def test_exact_queries_no_spelling_changes_and_transient_url_candidates(self):
        seen = []
        def transport(url, timeout, limit, headers):
            seen.append((url, headers))
            return 200, {}, json.dumps({'web': {'results': [
                {'url': 'https://example.com/', 'description': 'Fake unsupported claim'},
                {'url': 'https://example.com/duplicate'}, {'url': 'http://unsafe.com'},
                {'url': 'https://other.com/'}]}}).encode()
        candidates = BraveDiscovery(Fetcher(self.budget, transport), self.access, token='test-key').candidates('923609016')
        self.assertEqual(candidates, ['https://example.com/', 'https://other.com/'])
        self.assertEqual(self.budget.requests, 2)
        self.assertAlmostEqual(self.budget.cost, 0.01)
        queries = [parse_qs(urlsplit(row[0]).query) for row in seen]
        self.assertEqual([row['q'][0] for row in queries], ['"923609016"', '"923 609 016"'])
        self.assertTrue(all(row['spellcheck'] == ['false'] for row in queries))
        self.assertNotIn('test-key', json.dumps(self.budget.emit()))

    def test_authenticated_redirects_are_not_followed_or_unbilled(self):
        calls = []
        def transport(url, timeout, limit, headers):
            calls.append(url)
            return 302, {'location': 'https://example.com/'}, b''
        with self.assertRaisesRegex(SourceUnavailable, 'Authenticated redirects'):
            BraveDiscovery(Fetcher(self.budget, transport), self.access, token='test-key').candidates('923609016')
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.budget.cost, COST_PER_ATTEMPT_USD)

    def test_every_retry_is_billed_and_cap_stops_before_retry(self):
        self.budget.config.update(max_retries=1, third_party_cost_usd=0.005)
        def transport(*args):
            raise OSError('Failure')
        with self.assertRaises(BudgetExceeded):
            BraveDiscovery(Fetcher(self.budget, transport), self.access, token='test-key').candidates('923609016')
        self.assertEqual(self.budget.requests, 1)
        self.assertEqual(self.budget.cost, 0.005)

    def test_credentials_cannot_be_sent_to_company_sites(self):
        with self.assertRaisesRegex(SourceUnavailable, 'scope refused'):
            Fetcher(self.budget).get('https://example.com/', {'example.com'},
                                     request_headers={'X-Subscription-Token': 'test-key'})
        self.assertEqual(self.budget.requests, 0)

    def test_authenticated_search_cannot_omit_its_paid_charge(self):
        with self.assertRaisesRegex(SourceUnavailable, 'scope refused'):
            Fetcher(self.budget).get('https://api.search.brave.com/res/v1/web/search?q=test',
                {'api.search.brave.com'}, request_headers={'X-Subscription-Token': 'test-key'})
        self.assertEqual(self.budget.requests, 0)

    def test_authentication_error_does_not_expose_secret(self):
        def transport(*args):
            raise OSError('Secret test-key was refused')
        with self.assertRaises(SourceUnavailable) as caught:
            BraveDiscovery(Fetcher(self.budget, transport), self.access, token='test-key').candidates('923609016')
        self.assertNotIn('test-key', str(caught.exception))
