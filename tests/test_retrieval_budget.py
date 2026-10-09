"""Available source opportunities must survive a bounded retrieval policy."""
import email.utils
import json
import time
import unittest
from datetime import date

from shirushi.contracts import ROOT, load
from shirushi.fetch import Budget, Fetcher
from shirushi.live import acquire_website
from shirushi.nav_jobs import HOST, SUBUNIT, NavFeed
from shirushi.web_sources import page_values

SUBJECT = '923609016'
NAME = 'Example Pumps AS'
CUTOFF = '2026-10-09T00:00:00Z'


class RetrievalBudgetTests(unittest.TestCase):
    def test_www_redirect_does_not_spend_another_page_on_the_same_home(self):
        class Pages:
            def __init__(self):
                self.urls = []
            def get(self, url, *_args, **_kw):
                self.urls.append(url)
                effective = url.replace('://www.', '://')
                raw = ('<footer>Copyright ' + NAME + '. Org.nr. ' + SUBJECT + '</footer>'
                       '<a href="/products/pump">Pump</a><a href="/careers">Careers</a>').encode()
                return raw, {'effective_url': effective, 'content_type': 'text/html'}
        fetcher = Pages()
        acquire_website(fetcher, SUBJECT, {'navn': NAME, 'hjemmeside': 'https://www.example-pumps.no/'}, None, 3)
        self.assertEqual(fetcher.urls, ['https://www.example-pumps.no/',
                         'https://example-pumps.no/products/pump', 'https://example-pumps.no/careers'])

    def test_products_cannot_consume_every_content_page_before_jobs(self):
        base = 'https://example-pumps.no/'
        posting = {'@type': 'JobPosting', 'title': 'Pump engineer', 'datePosted': '2026-10-01',
                   'validThrough': '2026-10-31', 'identifier': 'job-1',
                   'hiringOrganization': {'identifier': SUBJECT}}
        class Pages:
            def __init__(self):
                self.urls = []
            def get(self, url, *_args, **_kw):
                self.urls.append(url)
                if url == base:
                    raw = ('<a href="/careers">Careers</a>' + ''.join(
                        '<a href="/products/p' + str(i) + '">Product</a>' for i in range(5)) +
                        '<a href="/news">News</a><footer>Copyright ' + NAME +
                        '. Org.nr. ' + SUBJECT + '</footer>').encode()
                elif url.endswith('/careers'):
                    raw = ('<script type="application/ld+json">' + json.dumps(posting) + '</script>').encode()
                else:
                    raw = b'<p>Available page</p>'
                return raw, {'effective_url': url, 'content_type': 'text/html'}
        fetcher = Pages()
        pages, _, _ = acquire_website(fetcher, SUBJECT, {'navn': NAME, 'hjemmeside': base}, None, 6)
        jobs = [v for raw, receipt in pages for v in page_values(
            raw, SUBJECT, receipt['effective_url'], date(2026, 10, 9)) if v[0] == 'job_posting']
        self.assertEqual(len(jobs), 1)
        self.assertIn(base + 'news', fetcher.urls)
        self.assertLessEqual(len(fetcher.urls), 6)

    def test_initial_nav_inventory_includes_active_ad_older_than_one_week(self):
        config = load(ROOT / 'configs/shard-validation.json')
        config.update(max_retries=0, min_host_interval_seconds=0)
        budget = Budget(config, time.monotonic() + 5)
        entry = 'https://' + HOST + '/api/v1/feedentry/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        changed = email.utils.parsedate_to_datetime('Thu, 01 Oct 2026 00:00:00 GMT')
        def transport(url, _timeout, _limit, headers=None):
            if url.endswith('/publicToken'):
                return 200, {}, b'a.b.c'
            if url.endswith('/feed'):
                since = email.utils.parsedate_to_datetime(headers['If-Modified-Since'])
                body = {'items': [{'url': entry, '_feed_entry': {'status': 'ACTIVE', 'businessName': NAME}}]
                        if changed >= since else [], 'next_url': None}
            elif url == entry:
                body = {'status': 'ACTIVE', 'ad_content': {'employer': {'orgnr': '999888777'}}}
            elif url == SUBUNIT + '999888777':
                body = {'organisasjonsnummer': '999888777', 'overordnetEnhet': SUBJECT}
            else:
                raise AssertionError(url)
            return 200, {'content-type': 'application/json'}, json.dumps(body).encode()
        feed = NavFeed(Fetcher(budget, transport), cutoff=CUTOFF)
        self.assertEqual(len(feed.for_company(SUBJECT, {'navn': NAME})[0]), 1)
        self.assertTrue(feed.diagnostics['window_complete'])
        self.assertEqual(budget.requests, 4)

    def test_nav_truncation_is_unknown_and_later_inactive_events_remove_leads(self):
        config = load(ROOT / 'configs/shard-validation.json')
        config.update(max_retries=0, min_host_interval_seconds=0)
        entry = 'https://' + HOST + '/api/v1/feedentry/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        for closed in (True, False):
            with self.subTest(closed=closed):
                budget = Budget(config, time.monotonic() + 5)
                def transport(url, _timeout, _limit, headers=None):
                    if url.endswith('/publicToken'):
                        return 200, {}, b'a.b.c'
                    items = [{'url': entry, '_feed_entry': {'status': 'ACTIVE', 'businessName': NAME}}]
                    if closed:
                        items.append({'url': entry, '_feed_entry': {'status': 'INACTIVE'}})
                    body = {'items': items, 'next_url': None if closed else '/api/v1/feed/next'}
                    return 200, {}, json.dumps(body).encode()
                feed = NavFeed(Fetcher(budget, transport), max_pages=1, cutoff=CUTOFF)
                index = feed.headers()
                self.assertEqual(feed.diagnostics['window_complete'], closed)
                self.assertEqual(bool(index), not closed)
                self.assertEqual(budget.requests, 2)
