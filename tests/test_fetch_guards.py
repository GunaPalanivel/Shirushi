"""Robots handling in the bounded fetcher: a non-robots HTML answer is not a block."""
import time
import unittest
from urllib.robotparser import RobotFileParser

from shirushi.contracts import ROOT, load
from shirushi.fetch import Budget, Fetcher, SourceUnavailable

PAGE = 'https://example.com/about'
HOSTS = {'example.com'}


def html_document(size, extra=''):
    body = '<!DOCTYPE html><html lang="no"><head><title>x</title></head><body>' + extra
    return (body + '<p>' + 'x' * (size - len(body) - 20) + '</p></body></html>').encode()


class RobotsBoundTests(unittest.TestCase):
    def fetcher(self, robots):
        config = load(ROOT / 'configs/local-live.json')
        config.update(min_host_interval_seconds=0, max_retries=0)
        self.budget = Budget(config, time.monotonic() + 30)
        return Fetcher(self.budget, lambda url, *a: (200, {'content-type': 'text/html'}, robots)
                       if url.endswith('/robots.txt') else (200, {'content-type': 'text/html'}, b'<html>ok</html>'))

    def test_oversized_html_page_served_as_robots_txt_imposes_no_rules(self):
        raw = html_document(80_000)
        self.assertGreater(len(raw), 65536)
        body, receipt = self.fetcher(raw).get(PAGE, HOSTS, robots=True)
        self.assertEqual(body, b'<html>ok</html>')
        self.assertEqual(receipt['robots_response'][0], raw)  # the observed bytes stay retained for audit
        # The independent auditor re-parses the same bytes and reaches the same verdict.
        audit = RobotFileParser('https://example.com/robots.txt')
        audit.parse(raw.decode('utf-8').splitlines())
        self.assertTrue(audit.can_fetch('Shirushi/0.1', PAGE))

    def test_oversized_genuine_robots_file_stays_blocked(self):
        raw = b'User-agent: *\nAllow: /\n' + b'# padding\n' * 8000
        self.assertGreater(len(raw), 65536)
        with self.assertRaisesRegex(SourceUnavailable, 'Robots access could not be established') as caught:
            self.fetcher(raw).get(PAGE, HOSTS, robots=True)
        self.assertEqual(caught.exception.availability, 'blocked')

    def test_oversized_html_containing_directives_stays_blocked(self):
        for directive in ('Disallow: /', 'User-agent: *', 'Sitemap: https://example.com/s.xml', '  allow: /'):
            with self.subTest(directive=directive):
                raw = html_document(80_000, '\n' + directive + '\n')
                with self.assertRaises(SourceUnavailable) as caught:
                    self.fetcher(raw).get(PAGE, HOSTS, robots=True)
                self.assertEqual(caught.exception.availability, 'blocked')

    def test_oversized_non_html_without_directives_stays_blocked(self):
        with self.assertRaises(SourceUnavailable):
            self.fetcher(b'{"not": "robots"}' + b' ' * 70_000).get(PAGE, HOSTS, robots=True)

    def test_small_robots_rules_still_apply(self):
        with self.assertRaisesRegex(SourceUnavailable, 'Robots disallows'):
            self.fetcher(b'User-agent: *\nDisallow: /\n').get(PAGE, HOSTS, robots=True)


class ResponseCapTests(unittest.TestCase):
    def test_inline_image_page_over_the_cap_is_refused(self):
        # Characterizes the current per-source cap (unseen probe, company 18): a page
        # that is mostly inline base64 images exceeds it although its markup is small.
        config = load(ROOT / 'configs/local-live.json')
        config.update(min_host_interval_seconds=0, max_retries=0)
        image = b'<img src="data:image/jpeg;base64,' + b'A' * 2_300_000 + b'">'
        page = b'<html><body>' + image + b'<p>' + b'x' * 38_000 + b'</p></body></html>'
        self.assertGreater(len(page), config['max_response_bytes'])
        fetcher = Fetcher(Budget(config, time.monotonic() + 30), lambda *a: (200, {'content-type': 'text/html'}, page))
        with self.assertRaisesRegex(SourceUnavailable, 'per-source byte limit'):
            fetcher.get(PAGE, HOSTS)


if __name__ == '__main__':
    unittest.main()
