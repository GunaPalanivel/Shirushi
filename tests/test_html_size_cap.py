"""Per-response byte cap: company-page HTML may be larger than every other response kind."""
import gzip
import time
import unittest
from unittest import mock

from shirushi import fetch
from shirushi.contracts import ROOT, load, validate_config
from shirushi.fetch import Budget, BudgetExceeded, Fetcher, SourceUnavailable

PAGE = 'https://example.com/'
HOSTS = {'example.com'}
HTML = {'content-type': 'text/html; charset=utf-8'}
MIB = 1024 * 1024


def inline_image_page(size):
    """A page that is mostly one inline base64 image, like the probe's 2.35 MB company page."""
    head = b'<html><body><p>Drives av Lise AS</p><img src="data:image/jpeg;base64,'
    tail = b'"></body></html>'
    return head + b'A' * (size - len(head) - len(tail)) + tail


class CapTestCase(unittest.TestCase):
    def setUp(self):
        self.config = load(ROOT / 'configs/local-live.json')
        self.config.update(min_host_interval_seconds=0, max_retries=0)

    def fetcher(self, body, headers=HTML, robots_body=b'User-agent: *\nAllow: /\n'):
        self.budget = Budget(self.config, time.monotonic() + 30)
        return Fetcher(self.budget, lambda url, *a: (200, {'content-type': 'text/plain'}, robots_body)
                       if url.endswith('/robots.txt') else (200, headers, body))


class CompanyPageCapTests(CapTestCase):
    def test_two_mebibyte_plus_company_page_is_retained_byte_for_byte(self):
        page = inline_image_page(2_348_409)
        self.assertGreater(len(page), self.config['max_response_bytes'])
        body, receipt = self.fetcher(page).get(PAGE, HOSTS, robots=True)
        self.assertEqual(body, page)  # data: URIs are neither skipped nor rewritten
        self.assertEqual(receipt['content_type'], HTML['content-type'])

    def test_page_bytes_are_charged_to_the_run_budget(self):
        page = inline_image_page(2_300_000)
        robots = b'User-agent: *\nAllow: /\n'
        self.fetcher(page, robots_body=robots).get(PAGE, HOSTS, robots=True)
        self.assertEqual(self.budget.bytes, len(page) + len(robots))

    def test_page_that_would_overrun_the_total_budget_is_refused(self):
        self.config['max_total_bytes'] = 2_000_000
        with self.assertRaises(BudgetExceeded):
            self.fetcher(inline_image_page(2_300_000)).get(PAGE, HOSTS, robots=True)

    def test_page_over_the_html_cap_is_refused_and_the_cap_is_inclusive(self):
        cap = self.config['max_html_bytes']
        self.assertEqual(cap, 4 * MIB)
        body, _ = self.fetcher(inline_image_page(cap)).get(PAGE, HOSTS, robots=True)
        self.assertEqual(len(body), cap)
        with self.assertRaisesRegex(SourceUnavailable, 'per-source byte limit'):
            self.fetcher(inline_image_page(cap + 1)).get(PAGE, HOSTS, robots=True)

    def test_configs_without_an_html_cap_keep_the_single_cap(self):
        del self.config['max_html_bytes']
        with self.assertRaisesRegex(SourceUnavailable, 'per-source byte limit'):
            self.fetcher(inline_image_page(2_300_000)).get(PAGE, HOSTS, robots=True)


class OtherResponsesKeepTheStandardCapTests(CapTestCase):
    def test_json_response_of_page_size_is_refused(self):
        body = b'{"x": "' + b'a' * 2_300_000 + b'"}'
        with self.assertRaisesRegex(SourceUnavailable, 'per-source byte limit'):
            self.fetcher(body, {'content-type': 'application/json'}).get(PAGE, HOSTS)

    def test_html_without_robots_scope_is_refused(self):
        # Only company-page fetches (robots=True) earn the larger cap.
        with self.assertRaisesRegex(SourceUnavailable, 'per-source byte limit'):
            self.fetcher(inline_image_page(2_300_000)).get(PAGE, HOSTS)

    def test_robots_checked_sitemap_and_json_and_unlabelled_bodies_are_refused(self):
        body = b'<urlset>' + b' ' * 2_300_000 + b'</urlset>'
        for headers in ({'content-type': 'application/xml'}, {'content-type': 'application/json'}, {}):
            with self.subTest(headers=headers):
                with self.assertRaisesRegex(SourceUnavailable, 'per-source byte limit'):
                    self.fetcher(body, headers).get('https://example.com/sitemap.xml', HOSTS, robots=True)

    def test_oversized_robots_txt_is_refused_by_its_own_fetch(self):
        with self.assertRaisesRegex(SourceUnavailable, 'Robots access could not be established'):
            self.fetcher(b'<html></html>', robots_body=b'User-agent: *\n' + b'#' * 2_300_000).get(PAGE, HOSTS, robots=True)


class DecompressionTests(CapTestCase):
    def test_compressed_body_that_inflates_past_the_cap_is_refused_not_inflated(self):
        inflated = b'<html>' + b'A' * (6 * MIB) + b'</html>'
        packed = gzip.compress(inflated)
        self.assertLess(len(packed), 64 * 1024)
        with self.assertRaisesRegex(SourceUnavailable, 'Unsupported compressed response'):
            self.fetcher(packed, {'content-type': 'text/html', 'content-encoding': 'gzip'}).get(PAGE, HOSTS, robots=True)
        for coding in ('deflate', 'br', 'GZIP'):
            with self.subTest(coding=coding):
                with self.assertRaisesRegex(SourceUnavailable, 'Unsupported compressed response'):
                    self.fetcher(b'x', {'content-type': 'text/html', 'content-encoding': coding}).get(PAGE, HOSTS, robots=True)


class FakeResponse:
    def __init__(self, body, headers, chunk=65536):
        self.status, self.body, self.pos, self.chunk = 200, body, 0, chunk
        self.header_list = list(headers.items())

    def getheaders(self):
        return self.header_list

    def isclosed(self):
        return self.pos >= len(self.body)

    def read(self, count):
        piece = self.body[self.pos:self.pos + min(count, self.chunk)]
        self.pos += len(piece)
        return piece


class FakeConnection:
    requests = []

    def __init__(self, response):
        self.response = response

    def request(self, method, target, body=None, headers=None):
        self.requests.append(headers)

    def getresponse(self):
        return self.response

    def close(self):
        pass


class StreamingTransportTests(CapTestCase):
    """The real transport, with only the socket replaced."""

    def fetch(self, body, headers):
        response = FakeResponse(body, headers)
        FakeConnection.requests = []
        self.budget = Budget(self.config, time.monotonic() + 30)
        fetcher = Fetcher(self.budget)
        fetcher.robots_sources['https://example.com'] = (b'', {})
        # Skip robots: the transport, not the robots protocol, is under test.
        with mock.patch.object(fetch, 'PinnedHTTPS', lambda *a: FakeConnection(response)), \
                mock.patch.object(fetch, 'public_addresses', lambda host: ['93.184.216.34']), \
                mock.patch.object(Fetcher, 'check_robots', lambda *a: None):
            return fetcher.get(PAGE, HOSTS, robots=True), response

    def test_streamed_html_page_over_two_mebibytes_is_read_and_charged(self):
        page = inline_image_page(2_348_409)
        (body, _), _ = self.fetch(page, HTML)
        self.assertEqual(body, page)
        self.assertEqual(self.budget.bytes, len(page))
        self.assertEqual(FakeConnection.requests[0]['Accept-Encoding'], 'identity')

    def test_streamed_non_html_stops_reading_at_the_standard_cap(self):
        body = b'{"x": "' + b'a' * 3_000_000 + b'"}'
        with self.assertRaisesRegex(SourceUnavailable, 'per-source byte limit'):
            self.fetch(body, {'content-type': 'application/xml'})
        # Aborted one chunk past the standard cap, not at the HTML cap.
        self.assertLessEqual(self.budget.bytes, self.config['max_response_bytes'] + 1)


class ConfigContractTests(unittest.TestCase):
    def check(self, **changes):
        config = load(ROOT / 'configs/local-live.json')
        config.update(changes)
        return validate_config(config, load(ROOT / 'configs/source-policy.json'))

    def test_live_config_declares_a_valid_html_cap(self):
        self.assertEqual(self.check(), [])

    def test_html_cap_must_be_an_integer_not_below_the_standard_cap(self):
        for bad in (0, -1, 2.5, '4194304', True, 1024):
            with self.subTest(value=bad):
                self.assertTrue(self.check(max_html_bytes=bad))


if __name__ == '__main__':
    unittest.main()
