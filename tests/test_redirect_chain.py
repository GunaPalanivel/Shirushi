"""A registry-declared host that redirects to another domain: bounded chain, then identity."""
import json
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path
from urllib.parse import urlsplit

from shirushi.contracts import ROOT, load
from shirushi.fetch import Budget, Fetcher, SourceUnavailable, website_hosts
from shirushi.live import acquire_website
from shirushi.redirects import REDIRECT_DENYLIST, registrable_domain
from shirushi.snapshots import SnapshotStore, digest
from shirushi.web_sources import check_web

REGISTRY = 'https://www.example.no/'
HOSTS = website_hosts('www.example.no')
SITE = 'https://www.pumps-example.com/'
SUBJECT, NAME = '923609016', 'Example Pumps AS'
PAGE = ('<html><head><title>Pumps</title></head><body><p>Example Pumps AS tilbyr pumper til industrien.</p>'
        '<footer><p>Example Pumps AS, Storgata 1</p></footer></body></html>')


def redirect(status, target):
    return status, {'location': target}, b''


def html(text=PAGE):
    return 200, {'content-type': 'text/html'}, text.encode()


class Net:
    """Scripted transport: unknown URLs are 404, every request is recorded."""
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, url, timeout, limit, *args):
        self.calls.append(url)
        return self.routes.get(url, (404, {'content-type': 'text/plain'}, b''))


def fetcher(routes):
    config = load(ROOT / 'configs/local-live.json')
    config.update(min_host_interval_seconds=0, max_retries=0)
    net = Net(routes)
    return Fetcher(Budget(config, time.monotonic() + 30), net), net


def fetch(routes, url=REGISTRY, hosts=HOSTS, registry=HOSTS):
    site, net = fetcher(routes)
    return site.get(url, hosts, robots=True, registry_hosts=registry), net


class RedirectPolicyTests(unittest.TestCase):
    def refused(self, routes, pattern, **kw):
        site, net = fetcher(routes)
        with self.assertRaisesRegex(SourceUnavailable, pattern) as caught:
            site.get(kw.pop('url', REGISTRY), HOSTS, robots=True, registry_hosts=kw.pop('registry', HOSTS))
        self.assertEqual(caught.exception.availability, 'blocked')
        return net

    def test_permanent_chain_from_the_registry_host_is_followed_and_recorded(self):
        (raw, receipt), net = fetch({REGISTRY: redirect(301, SITE), SITE: html()})
        self.assertIn(b'Example Pumps AS', raw)
        self.assertEqual(receipt['source_url'], REGISTRY)
        self.assertEqual(receipt['effective_url'], SITE)
        self.assertEqual(receipt['redirect_chain'], [{'from': REGISTRY, 'to': SITE, 'http_status': 301}])
        self.assertEqual(receipt['robots_response'][1]['source_url'], 'https://www.pumps-example.com/robots.txt')
        self.assertEqual(receipt['registry_robots_response'][1]['source_url'], 'https://www.example.no/robots.txt')

    def test_permanent_redirect_308_and_a_www_alias_hop_first_are_followed(self):
        middle = 'https://example.no/'
        (_, receipt), _ = fetch({REGISTRY: redirect(301, middle), middle: redirect(308, SITE), SITE: html()})
        self.assertEqual([h['http_status'] for h in receipt['redirect_chain']], [301, 308])
        self.assertEqual(urlsplit(receipt['effective_url']).hostname, 'www.pumps-example.com')

    def test_without_the_registry_marker_a_cross_domain_redirect_is_still_refused(self):
        site, _ = fetcher({REGISTRY: redirect(301, SITE), SITE: html()})
        with self.assertRaisesRegex(SourceUnavailable, 'escapes the permitted host scope'):
            site.get(REGISTRY, HOSTS, robots=True)

    def test_first_hop_must_be_issued_by_the_registry_host(self):
        other = 'https://www.other-site.no/'
        self.refused({other: redirect(301, SITE), SITE: html()}, 'escapes the permitted host scope',
                     url=other, registry=HOSTS)

    def test_a_later_hop_may_not_leave_the_first_destination(self):
        hop = 'https://www.third-party.com/'
        self.refused({REGISTRY: redirect(301, SITE), SITE: redirect(301, hop), hop: html()},
                     'escapes the permitted host scope')

    def test_http_alternate_port_credentials_and_private_targets_are_refused(self):
        for target in ('http://www.pumps-example.com/', 'https://www.pumps-example.com:8443/',
                       'https://user:pw@www.pumps-example.com/', 'https://10.0.0.5/', 'https://192.168.1.10/',
                       'https://127.0.0.1/', 'https://[::1]/', 'https://intranet/', 'https://localhost/'):
            with self.subTest(target=target):
                net = self.refused({REGISTRY: redirect(301, target), target: html()}, '.')
                self.assertNotIn(target, net.calls)

    def test_three_hops_are_followed_and_four_are_refused(self):
        a, b, c = (SITE + p for p in ('a', 'b', 'c'))
        (_, receipt), _ = fetch({REGISTRY: redirect(301, SITE), SITE: redirect(301, a), a: redirect(301, b), b: html()})
        self.assertEqual(len(receipt['redirect_chain']), 3)
        self.refused({REGISTRY: redirect(301, SITE), SITE: redirect(301, a), a: redirect(301, b),
                      b: redirect(301, c), c: html()}, 'Redirect bound exceeded')

    def test_temporary_redirects_across_domains_are_refused(self):
        for status in (302, 303, 307):
            with self.subTest(status=status):
                net = self.refused({REGISTRY: redirect(status, SITE), SITE: html()}, 'escapes the permitted host scope')
                self.assertNotIn(SITE, net.calls)

    def test_a_temporary_hop_anywhere_in_a_cross_domain_chain_is_refused(self):
        middle = 'https://example.no/'
        self.refused({REGISTRY: redirect(302, middle), middle: redirect(301, SITE), SITE: html()},
                     'Temporary redirect')

    def test_shared_platform_group_and_shortener_destinations_are_refused(self):
        for host in ('www.sparebank1.no', 'shop.myshopify.com', 'firm.wixsite.com', 'bit.ly', 'www.facebook.com',
                     'firm.webflow.io', 'www.linkedin.com'):
            target = 'https://' + host + '/nb/smn'
            with self.subTest(host=host):
                net = self.refused({REGISTRY: redirect(301, target), target: html()}, 'shared|group|escapes')
                self.assertNotIn(target, net.calls)

    def test_the_hop_that_crosses_must_itself_be_issued_for_a_fixed_registry_path(self):
        for middle in (REGISTRY + 'redirect?to=1', REGISTRY + 'deep/page'):
            with self.subTest(middle=middle):
                net = self.refused({REGISTRY: redirect(301, middle), middle: redirect(301, SITE), SITE: html()},
                                   'escapes the permitted host scope')
                self.assertNotIn(SITE, net.calls)

    def test_short_numeric_ip_spellings_are_not_public_hosts(self):
        for host in ('127.1', '10.1', '0x7f.1', '2130706433'):
            target = 'https://' + host + '/'
            with self.subTest(host=host):
                net = self.refused({REGISTRY: redirect(301, target), target: html()}, 'not a public registrable host')
                self.assertNotIn(target, net.calls)

    def test_the_destination_alias_may_not_be_a_bare_suffix_or_shared_host(self):
        for first, second in (('https://www.priv.no/', 'https://priv.no/'), ('https://www.co.uk/', 'https://co.uk/'),
                              ('https://www.com/', 'https://com/')):
            with self.subTest(first=first):
                net = self.refused({REGISTRY: redirect(301, first), first: redirect(301, second), second: html()},
                                   'not a public registrable host')
                self.assertNotIn(second, net.calls)

    def test_destination_robots_disallow_stops_before_the_body_is_requested(self):
        routes = {REGISTRY: redirect(301, SITE), SITE: html(),
                  'https://www.pumps-example.com/robots.txt': (200, {'content-type': 'text/plain'},
                                                                  b'User-agent: *\nDisallow: /\n')}
        net = self.refused(routes, 'Robots disallows URL')
        self.assertNotIn(SITE, net.calls)

    def test_registry_robots_disallow_stops_before_any_redirect_is_requested(self):
        routes = {REGISTRY: redirect(301, SITE), SITE: html(),
                  'https://www.example.no/robots.txt': (200, {'content-type': 'text/plain'},
                                                           b'User-agent: *\nDisallow: /\n')}
        net = self.refused(routes, 'Robots disallows URL')
        self.assertNotIn(REGISTRY, net.calls)

    def test_robots_txt_of_the_registry_host_may_redirect_across_authority(self):
        robots = 'https://www.example.no/robots.txt'
        moved = 'https://www.pumps-example.com/robots.txt'
        routes = {robots: redirect(301, moved), moved: (200, {'content-type': 'text/plain'}, b'User-agent: *\nAllow: /\n'),
                  REGISTRY: redirect(301, SITE), SITE: html()}
        (_, receipt), _ = fetch(routes)
        self.assertEqual(receipt['registry_robots_response'][1]['redirect_chain'],
                         [{'from': robots, 'to': moved, 'http_status': 301}])

    def test_robots_txt_rules_reached_by_redirect_apply_to_the_registry_host(self):
        robots = 'https://www.example.no/robots.txt'
        moved = 'https://www.pumps-example.com/robots.txt'
        routes = {robots: redirect(301, moved), moved: (200, {'content-type': 'text/plain'}, b'User-agent: *\nDisallow: /\n'),
                  REGISTRY: redirect(301, SITE), SITE: html()}
        self.refused(routes, 'Robots disallows URL')

    def test_temporary_robots_redirect_and_a_non_registry_robots_redirect_are_refused(self):
        robots = 'https://www.example.no/robots.txt'
        moved = 'https://www.pumps-example.com/robots.txt'
        self.refused({robots: redirect(302, moved), REGISTRY: redirect(301, SITE), SITE: html()},
                     'Robots access could not be established')
        far = 'https://www.third-party.com/robots.txt'
        self.refused({'https://www.pumps-example.com/robots.txt': redirect(301, far),
                      REGISTRY: redirect(301, SITE), SITE: html()}, 'Robots access could not be established')

    def test_only_the_registry_root_may_cross_domain(self):
        deep = 'https://www.example.no/redirect?to=' + SITE
        for url in ('https://www.example.no/blog', deep):
            with self.subTest(url=url):
                self.refused({url: redirect(301, SITE), SITE: html()}, 'escapes the permitted host scope', url=url)


class RegistrableDomainTests(unittest.TestCase):
    def test_ordinary_and_second_level_suffixes(self):
        expected = {'example.no': 'example.no', 'www.example.no': 'example.no', 'a.b.example.com': 'example.com',
                    'example.co.uk': 'example.co.uk', 'www.example.co.uk': 'example.co.uk',
                    'firm.priv.no': 'firm.priv.no', 'www.firm.priv.no': 'firm.priv.no',
                    'example.org': 'example.org', 'x.example.net': 'example.net', 'firma.oslo.no': 'firma.oslo.no',
                    'xn--brnnysund-m8ac.no': 'xn--brnnysund-m8ac.no'}
        for host, domain in expected.items():
            with self.subTest(host=host):
                self.assertEqual(registrable_domain(host), domain)

    def test_a_bare_suffix_or_single_label_has_no_registrable_domain(self):
        for host in ('priv.no', 'co.uk', 'no', 'localhost', '', 'kommune.no', 'oslo.no'):
            with self.subTest(host=host):
                self.assertIsNone(registrable_domain(host))

    def test_denylist_covers_the_named_shared_hosts(self):
        for domain in ('sparebank1.no', 'dnb.no', 'wixsite.com', 'squarespace.com', 'myshopify.com', 'webflow.io',
                       'facebook.com', 'linkedin.com', 'bit.ly'):
            self.assertIn(domain, REDIRECT_DENYLIST)


class RegistryLinkTests(unittest.TestCase):
    """check_web re-verifies the persisted chain; the page must also name the exact legal subject."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(Path(self.temp.name))
        raw = json.dumps({'organisasjonsnummer': SUBJECT, 'navn': NAME, 'hjemmeside': 'www.example.no'}).encode()
        self.anchor = self.store.save(raw, dict(organisation_number=SUBJECT, source_class='brreg_entity',
            source_url='https://data.brreg.no/enhetsregisteret/api/enheter/' + SUBJECT, http_status=200,
            sha256=digest(raw), retrieved_at='2026-10-10T08:00:00Z'))

    def save(self, text=PAGE, path='/', chain=None, requested=REGISTRY, host='www.pumps-example.com', **extra):
        raw = text.encode()
        url = 'https://' + host + path
        if chain is None:
            chain = [{'from': REGISTRY, 'to': url, 'http_status': 301}]
        meta = dict(organisation_number=SUBJECT, source_class='company_owned', requested_url=requested,
                    source_url=url, effective_url=url, http_status=200, sha256=digest(raw), declared_host=host,
                    source_origin=host, robots_checked=True, retrieved_at='2026-10-10T08:00:00Z',
                    ownership_anchor_snapshot_id=self.anchor, redirect_chain=chain)
        meta.update(extra)
        return self.store.save(raw, meta)

    def linked(self, sid):
        return [d['field'] for d in check_web(self.store, SUBJECT, sid)]

    def test_chain_and_exact_legal_name_make_the_destination_registry_linked(self):
        sid = self.save()
        decisions = check_web(self.store, SUBJECT, sid)
        self.assertEqual([d['field'] for d in decisions], ['product_service'])
        self.assertEqual(decisions[0]['claim']['scope'], 'registry_linked_html')
        self.assertNotIn('verified_website', [d['field'] for d in decisions])

    def test_the_same_page_without_a_chain_stays_unanchored(self):
        with self.assertRaisesRegex(ValueError, 'not anchored'):
            check_web(self.store, SUBJECT, self.save(chain=[], requested='https://www.pumps-example.com/'))

    def test_trade_name_without_the_legal_form_does_not_anchor(self):
        text = '<html><head><title>Example Pumps</title></head><body><p>Example Pumps tilbyr pumper.</p></body></html>'
        with self.assertRaisesRegex(ValueError, 'not anchored'):
            check_web(self.store, SUBJECT, self.save(text))

    def test_hidden_or_script_only_mentions_do_not_anchor(self):
        for text in ('<html><body><script>var n="Example Pumps AS";</script><p>Hei</p></body></html>',
                     '<html><body><div style="display:none">Example Pumps AS</div><p>Hei</p></body></html>'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'not anchored'):
                check_web(self.store, SUBJECT, self.save(text))

    def test_the_title_alone_may_carry_the_exact_legal_name(self):
        text = '<html><head><title>Example Pumps AS - Hjem</title></head><body><p>Hei</p></body></html>'
        self.assertEqual(self.linked(self.save(text)), [])  # anchored; no named assertion to publish

    def test_the_name_must_sit_in_the_title_a_heading_or_a_footer_address_or_contact_block(self):
        body = '<html><head><title>Hjem</title></head><body>%s</body></html>'
        blocks = {'h1': '<h1>Example Pumps AS</h1>', 'footer': '<footer>Example Pumps AS, Storgata 1</footer>',
                  'address': '<address>Example Pumps AS<br>Storgata 1</address>',
                  'contact class': '<div class="site-contact">Example Pumps AS, tlf 123</div>',
                  'kontakt id': '<div id="kontakt-oss"><p>Example Pumps AS</p></div>'}
        for label, block in blocks.items():
            with self.subTest(label):
                self.assertEqual(self.linked(self.save(body % block)), [])  # anchored, nothing to publish

    def test_a_mention_elsewhere_in_the_text_does_not_anchor(self):
        filler = 'x ' * 900
        body = '<html><head><title>Hjem</title></head><body>%s</body></html>'
        blocks = {'news item': '<article><h2>Nytt</h2><p>Example Pumps AS vant en kontrakt.</p></article>',
                  'reseller paragraph': '<main><p>Vi selger pumper fra Example Pumps AS og andre.</p></main>',
                  'h2 only': '<h2>Example Pumps AS</h2>', 'list item': '<ul><li>Example Pumps AS</li></ul>',
                  'wide contact wrapper': '<div class="contact-page"><p>Example Pumps AS</p><p>' + filler + '</p></div>',
                  'contact class on main': '<main class="contact"><p>Example Pumps AS</p><p>' + filler + '</p></main>',
                  'blockquote in footer': '<footer><blockquote>Example Pumps AS</blockquote></footer>'}
        for label, block in blocks.items():
            with self.subTest(label), self.assertRaisesRegex(ValueError, 'not anchored'):
                check_web(self.store, SUBJECT, self.save(body % block))

    def test_a_redirect_link_never_publishes_verified_website_from_json_ld(self):
        script = ('<script type="application/ld+json">{"@type":"Organization","identifier":"%s","url":"%s",'
                  '"description":"Pumper for industrien."}</script>')
        text = '<html><body>' + script % (SUBJECT, SITE) + '<footer>Example Pumps AS</footer></body></html>'
        fields = self.linked(self.save(text))
        self.assertIn('business_description', fields)  # the JSON-LD route ran
        self.assertNotIn('verified_website', fields)

    def test_the_registered_host_itself_still_publishes_verified_website_from_json_ld(self):
        script = ('<script type="application/ld+json">{"@type":"Organization","identifier":"%s",'
                  '"url":"https://www.example.no/"}</script>' % SUBJECT)
        raw = ('<html><body>' + script + '</body></html>').encode()
        meta = dict(organisation_number=SUBJECT, source_class='company_owned', source_url='https://www.example.no/',
                    effective_url='https://www.example.no/', http_status=200, sha256=digest(raw),
                    declared_host='www.example.no', source_origin='www.example.no', robots_checked=True,
                    retrieved_at='2026-10-10T08:00:00Z', ownership_anchor_snapshot_id=self.anchor, redirect_chain=[])
        fields = [d['field'] for d in check_web(self.store, SUBJECT, self.store.save(raw, meta))]
        self.assertIn('verified_website', fields)

    def test_a_longer_legal_name_is_not_the_exact_name(self):
        text = '<html><body><p>Example Pumps ASA er et selskap.</p><p>MyExample Pumps AS eier oss.</p></body></html>'
        with self.assertRaisesRegex(ValueError, 'not anchored'):
            check_web(self.store, SUBJECT, self.save(text))

    def test_chains_that_break_the_policy_do_not_anchor(self):
        cases = {
            'non-registry origin': dict(requested='https://www.other-site.no/',
                chain=[{'from': 'https://www.other-site.no/', 'to': SITE, 'http_status': 301}]),
            'origin outside the registry reaching an alias first': dict(requested='https://www.evil.example/',
                chain=[{'from': 'https://www.evil.example/', 'to': 'https://www.example.no/', 'http_status': 301},
                       {'from': 'https://www.example.no/', 'to': SITE, 'http_status': 301}]),
            'unnormalised http origin': dict(requested='http://www.example.no/',
                chain=[{'from': 'http://www.example.no/', 'to': SITE, 'http_status': 301}]),
            'temporary status': dict(chain=[{'from': REGISTRY, 'to': SITE, 'http_status': 302}]),
            'http hop': dict(chain=[{'from': REGISTRY, 'to': 'http://www.pumps-example.com/', 'http_status': 301}]),
            'port 8443': dict(chain=[{'from': REGISTRY, 'to': 'https://www.pumps-example.com:8443/', 'http_status': 301}]),
            'four hops': dict(chain=[{'from': REGISTRY, 'to': SITE + str(i), 'http_status': 301} if i == 0 else
                                     {'from': SITE + str(i - 1), 'to': SITE + str(i), 'http_status': 301} for i in range(4)],
                              path='/3'),
            'broken continuity': dict(chain=[{'from': REGISTRY, 'to': 'https://www.pumps-example.com/x', 'http_status': 301}]),
            'third domain': dict(chain=[{'from': REGISTRY, 'to': SITE, 'http_status': 301},
                                        {'from': SITE, 'to': 'https://www.third-party.com/', 'http_status': 301}],
                                 host='www.third-party.com'),
        }
        for label, kw in cases.items():
            with self.subTest(label), self.assertRaisesRegex(ValueError, 'not anchored'):
                check_web(self.store, SUBJECT, self.save(**kw))

    def test_denylisted_or_ip_destinations_do_not_anchor(self):
        for host in ('www.sparebank1.no', 'firm.wixsite.com', 'bit.ly', '10.0.0.5'):
            with self.subTest(host=host), self.assertRaisesRegex(ValueError, 'not anchored'):
                check_web(self.store, SUBJECT, self.save(host=host))

    def test_the_registry_row_must_name_the_origin_host(self):
        # The same persisted chain against a registry row for another host proves nothing.
        raw = json.dumps({'organisasjonsnummer': SUBJECT, 'navn': NAME, 'hjemmeside': 'www.unrelated.no'}).encode()
        self.anchor = self.store.save(raw, dict(organisation_number=SUBJECT, source_class='brreg_entity',
            source_url='https://data.brreg.no/enhetsregisteret/api/enheter/' + SUBJECT, http_status=200,
            sha256=digest(raw), retrieved_at='2026-10-10T08:00:00Z'))
        with self.assertRaisesRegex(ValueError, 'not anchored'):
            check_web(self.store, SUBJECT, self.save())

    def test_later_pages_inherit_the_anchor_of_the_verified_chain_root(self):
        root = self.save()
        sub = self.save('<html><body><p>Example Pumps AS tilbyr service.</p></body></html>', '/tjenester',
                        chain=[], requested='https://www.pumps-example.com/tjenester', redirect_anchor_snapshot_id=root)
        self.assertEqual(self.linked(sub), ['product_service'])

    def test_an_anchor_that_never_named_the_company_gives_later_pages_nothing(self):
        root = self.save('<html><body><p>Velkommen</p></body></html>')
        sub = self.save('<html><body><p>Example Pumps AS tilbyr service.</p></body></html>', '/tjenester',
                        chain=[], requested='https://www.pumps-example.com/tjenester', redirect_anchor_snapshot_id=root)
        with self.assertRaisesRegex(ValueError, 'not anchored'):
            check_web(self.store, SUBJECT, sub)

    def test_an_anchor_on_another_host_is_not_inherited(self):
        root = self.save()
        sub = self.save('<html><body><p>Example Pumps AS tilbyr service.</p></body></html>', '/tjenester', host='www.elsewhere.com',
                        chain=[], requested='https://www.elsewhere.com/tjenester', redirect_anchor_snapshot_id=root)
        with self.assertRaisesRegex(ValueError, 'not anchored'):
            check_web(self.store, SUBJECT, sub)

    def test_exact_operator_proof_route_is_unchanged_for_a_redirected_host(self):
        # Registered-host alias behaviour is untouched: the alias still needs no chain.
        raw = PAGE.encode()
        meta = dict(organisation_number=SUBJECT, source_class='company_owned', source_url='https://www.example.no/',
                    effective_url='https://www.example.no/', http_status=200, sha256=digest(raw),
                    declared_host='www.example.no', source_origin='www.example.no', robots_checked=True,
                    retrieved_at='2026-10-10T08:00:00Z', ownership_anchor_snapshot_id=self.anchor, redirect_chain=[])
        self.assertEqual([d['field'] for d in check_web(self.store, SUBJECT, self.store.save(raw, meta))], ['product_service'])


class AcquisitionTests(unittest.TestCase):
    """acquire_website offers the registry marker only for the registry-declared candidate."""
    def test_registry_candidate_crosses_domain_and_hypothesis_candidates_do_not(self):
        asked = []

        class Recorder:
            def get(self, url, hosts, robots=False, **kw):
                asked.append((url, kw.get('registry_hosts')))
                return PAGE.encode(), {'effective_url': url, 'content_type': 'text/html', 'redirect_chain': []}

        class Discovery:
            diagnostics = {}

            def candidates(self, subject, entity):
                return ['https://www.pumps-example.org/']

        acquire_website(Recorder(), SUBJECT, {'navn': NAME, 'hjemmeside': 'www.example.no'}, Discovery(), 3,
                        registry_redirects=True)
        self.assertEqual(asked[0], (REGISTRY, HOSTS))
        self.assertTrue(all(marker is None for url, marker in asked if url != REGISTRY))
        self.assertIn('https://www.pumps-example.org/', [u for u, _ in asked])


    def test_without_the_flag_no_candidate_may_cross_domain(self):
        asked = []

        class Recorder:
            def get(self, url, hosts, robots=False, **kw):
                asked.append((url, dict(kw)))
                return PAGE.encode(), {'effective_url': url, 'content_type': 'text/html', 'redirect_chain': []}

        acquire_website(Recorder(), SUBJECT, {'navn': NAME, 'hjemmeside': 'www.example.no'}, None, 3)
        self.assertEqual(asked[0], (REGISTRY, {}))
        self.assertTrue(all(kw == {} for _, kw in asked))


class ConfigFlagTests(unittest.TestCase):
    def check(self, **changes):
        from shirushi.contracts import validate_config
        config = load(ROOT / 'configs/local-live.json')
        config.update(changes)
        return validate_config(config, load(ROOT / 'configs/source-policy.json'))

    def test_the_flag_is_a_boolean_live_setting(self):
        self.assertEqual(self.check(), [])
        self.assertEqual(self.check(allow_registry_redirects=True), [])
        self.assertEqual(self.check(allow_registry_redirects=False), [])
        for bad in ('yes', 1, 0, None, [], 'true'):
            with self.subTest(value=bad):
                self.assertTrue(self.check(allow_registry_redirects=bad))

    def test_no_shipped_configuration_enables_it(self):
        for path in sorted((ROOT / 'configs').glob('*.json')):
            with self.subTest(path=path.name):
                self.assertNotIn('allow_registry_redirects', json.loads(path.read_text(encoding='utf-8')))


class DefaultFetchBytesTests(unittest.TestCase):
    def test_a_plain_fetch_keeps_its_old_receipts_and_refusals(self):
        routes = {'https://www.example.no/robots.txt': (404, {'content-type': 'text/plain'}, b''),
                  REGISTRY: redirect(301, SITE), SITE: html()}
        site, _ = fetcher(routes)
        with self.assertRaisesRegex(SourceUnavailable, 'Redirect or URL escapes the permitted host scope'):
            site.get(REGISTRY, HOSTS, robots=True)
        self.assertNotIn('redirect_chain', site.robots_sources['https://www.example.no'][1])
        marked, _ = fetcher(routes)
        with self.assertRaises(SourceUnavailable):
            marked.get('https://www.example.no/never', HOSTS, robots=True, registry_hosts=HOSTS)
        self.assertEqual(marked.robots_sources['https://www.example.no'][1]['redirect_chain'], [])


class WorkerTests(unittest.TestCase):
    """Whole worker with a scripted wire: the persisted receipts carry what a checker must re-verify."""
    def run_worker(self, pages, allow=True):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        config = load(ROOT / 'configs/local-external.json')
        config.update(enabled_sources=['brreg_entity', 'company_owned'], min_host_interval_seconds=0, max_retries=0)
        if allow:
            config['allow_registry_redirects'] = True
        frames, seen = [], []

        class Connection:
            def send(self, frame): frames.append(frame)
            def close(self): pass

        def transport(fetcher, url, timeout, limit, headers=None, request_body=None):
            seen.append(url)
            if 'data.brreg.no' in url:
                status, kind, raw = 200, 'application/json', json.dumps({
                    'organisasjonsnummer': SUBJECT, 'navn': NAME, 'hjemmeside': 'www.example.no',
                    '_links': {'self': {'href': url}}}).encode()
            elif url.endswith('/robots.txt'):
                status, kind, raw = 200, 'text/plain', b'User-agent: *\nAllow: /\n'
            elif url in pages and isinstance(pages[url], str) and pages[url].startswith('https://'):
                fetcher.budget.consume(0)
                return 301, {'location': pages[url]}, b''
            else:
                status, kind, raw = 200, 'text/html', pages.get(url, '<p>Tom</p>').encode()
            fetcher.budget.consume(len(raw))
            return status, {'content-type': kind}, raw

        job = {'store': Path(temp.name), 'subjects': [SUBJECT], 'previous': {}, 'config': config,
               'deadline': time.monotonic() + 10, 'started_at': '2026-10-12T08:00:00Z', 'run_id': 'redirect-chain',
               'discovery': None}
        with unittest.mock.patch('shirushi.fetch.Fetcher._request', transport):
            from shirushi.live import worker
            worker(Connection(), job)
        self.assertFalse([f for f in frames if f[0] == 'fatal'])
        store = SnapshotStore(Path(temp.name))
        receipts = {}
        for path in sorted((store.root / 'receipts').glob('*.json')):
            receipt = json.loads(path.read_text(encoding='utf-8'))
            if receipt.get('source_class') == 'company_owned':
                receipts[receipt['effective_url']] = dict(receipt, snapshot_id=path.stem)
        self.frames = frames
        return next(f[2]['envelope'] for f in frames if f[0] == 'result'), receipts, seen

    def test_registry_redirect_to_a_site_naming_the_legal_subject_publishes_named_assertions_only(self):
        pages = {REGISTRY: SITE, SITE: '<html><body><p>Example Pumps AS tilbyr pumper til industrien.</p>'
                                       '<a href="/om-oss">Om oss</a><footer>Example Pumps AS</footer></body></html>',
                 SITE + 'om-oss': '<html><body><p>Example Pumps AS leverer service.</p></body></html>'}
        result, receipts, seen = self.run_worker(pages)
        fields = {c['field'] for c in result['claims'] if c['availability'] == 'available'}
        self.assertIn('product_service', fields)
        self.assertNotIn('verified_website', fields)
        root, child = receipts[SITE], receipts[SITE + 'om-oss']
        self.assertEqual(root['requested_url'], REGISTRY)
        self.assertEqual(root['redirect_chain'], [{'from': REGISTRY, 'to': SITE, 'http_status': 301}])
        self.assertEqual(root['declared_host'], 'www.pumps-example.com')
        self.assertTrue(root['robots_snapshot_id'] and root['registry_robots_snapshot_id'])
        self.assertNotIn('redirect_anchor_snapshot_id', root)
        self.assertEqual(child['redirect_anchor_snapshot_id'], root['snapshot_id'])
        self.assertEqual(seen.count(SITE), 1)

    def test_registry_redirect_to_a_site_that_never_names_the_legal_subject_publishes_nothing(self):
        pages = {REGISTRY: SITE, SITE: '<html><body><p>Example Pumps tilbyr pumper til industrien.</p></body></html>'}
        result, receipts, _ = self.run_worker(pages)
        self.assertNotIn('product_service', {c['field'] for c in result['claims'] if c['availability'] == 'available'})
        self.assertIn(SITE, receipts)
        self.assertNotIn('redirect_anchor_snapshot_id', receipts[SITE])

    def test_a_json_ld_url_on_a_redirect_only_host_does_not_publish_verified_website(self):
        ld = ('<script type="application/ld+json">{"@type":"Organization","name":"Example Pumps AS",'
              '"identifier":"' + SUBJECT + '","url":"' + SITE + '"}</script>')
        pages = {REGISTRY: SITE, SITE: '<html><body>' + ld + '<p>Example Pumps AS tilbyr pumper.</p>'
                                       '<footer>Example Pumps AS</footer></body></html>'}
        result, _, _ = self.run_worker(pages)
        fields = {c['field'] for c in result['claims'] if c['availability'] == 'available'}
        self.assertIn('product_service', fields)
        self.assertNotIn('verified_website', fields)

    def test_the_flag_is_off_by_default_so_the_registry_redirect_is_refused_as_before(self):
        pages = {REGISTRY: SITE, SITE: PAGE}
        result, receipts, seen = self.run_worker(pages, allow=False)
        self.assertNotIn(SITE, seen)
        self.assertNotIn(SITE, receipts)
        self.assertFalse([r for r in receipts.values() if r.get('requested_url') == REGISTRY])
        failures = [f for frame in self.frames if frame[0] == 'result' for a in frame[2]['attempts']
                    for f in a.get('page_failures', [])]
        self.assertIn('Redirect or URL escapes the permitted host scope', [f['reason'] for f in failures])


if __name__ == '__main__':
    unittest.main()
