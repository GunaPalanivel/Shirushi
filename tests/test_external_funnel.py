"""Full discovery -> ownership -> content -> audit -> idempotent refresh trace."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from shirushi.contracts import ROOT, load, validate_envelopes
from shirushi.live import worker
from shirushi_eval.support import SourceAudit

SUBJECT = '923609016'


class ExternalFunnelTests(unittest.TestCase):
    def test_no_registry_website_discovers_two_content_families_and_refreshes(self):
        config = load(ROOT / 'configs/local-live.json')
        config.update(enabled_sources=['brreg_entity', 'company_owned'], third_party_cost_usd=0.02,
                      min_host_interval_seconds=0, max_pages_per_company=3)
        frames, requests = [], []
        class Connection:
            def send(self, frame):
                frames.append(frame)
            def close(self):
                pass
        def transport(fetcher, url, timeout, limit, headers=None):
            requests.append((url, headers))
            if 'api.search.brave.com' in url:
                body = json.dumps({'web': {'results': [{'url': 'https://example.com/'}]}}).encode()
                content_type = 'application/json'
            elif 'data.brreg.no' in url:
                body = json.dumps({'organisasjonsnummer': SUBJECT, 'navn': 'Example Pumps AS',
                                  '_links': {'self': {'href': url}}}).encode()
                content_type = 'application/json'
            elif url.endswith('robots.txt'):
                body, content_type = b'User-agent: *\nAllow: /\n', 'text/plain'
            elif url.endswith('/news'):
                body = b'<p>Example Pumps AS opened a new factory on 2026-10-01.</p>'
                content_type = 'text/html'
            else:
                body = (b'<footer>Copyright Example Pumps AS. Org.nr. 923609016</footer>'
                        b'<p>Example Pumps AS produces industrial pumps.</p><a href="/news">News</a>')
                content_type = 'text/html'
            fetcher.budget.consume(len(body))
            return 200, {'content-type': content_type}, body
        access = {'max_candidates': 3, 'max_queries_per_company': 2, 'request_interval_seconds': 0.02}
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'BRAVE_SEARCH_API_KEY': 'test-key'}), \
                patch('shirushi.fetch.Fetcher._request', transport):
            job = {'store': Path(root), 'subjects': [SUBJECT], 'previous': {}, 'config': config,
                   'deadline': time.monotonic() + 5, 'started_at': '2026-10-08T08:00:00Z',
                   'run_id': 'external-funnel', 'discovery': access}
            worker(Connection(), job)
            self.assertFalse([f for f in frames if f[0] == 'fatal'])
            first = next(f[2]['envelope'] for f in frames if f[0] == 'result')
            self.assertEqual(validate_envelopes([{'organisation_number': SUBJECT}], [first],
                                              load(ROOT / 'contracts/company-envelope.v1.json')), [])
            self.assertEqual({o['family'] for o in first['opportunities'] if o['status'] == 'covered'},
                             {'business_products', 'website_owned_profiles', 'jobs_dated_activity'})
            self.assertAlmostEqual(first['operations']['third_party_cost_usd'], 0.01)
            audit = SourceAudit(root, [SUBJECT])
            evidence = {e['id']: e for e in first['evidence']}
            for claim in first['claims']:
                audit.claim(SUBJECT, claim, evidence)
            self.assertTrue(all(headers is None for url, headers in requests if 'api.search.brave.com' not in url))
            job.update(previous={SUBJECT: first}, deadline=time.monotonic() + 5)
            frames.clear()
            worker(Connection(), job)
            self.assertFalse([f for f in frames if f[0] in ('fatal', 'invalid_previous')])
            second = next(f[2]['envelope'] for f in frames if f[0] == 'result')
            self.assertEqual(second['changes'], [])
            self.assertEqual(len(first['claims']), len(second['claims']))
