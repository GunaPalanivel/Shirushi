"""Independent audit of a company page reached through a registry-host redirect chain."""
import copy
import json
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

from shirushi.contracts import ROOT, load
from shirushi.snapshots import SnapshotStore, digest
from shirushi.web_sources import check_web
from shirushi_eval import redirect_support
from shirushi_eval.redirect_support import chain_failure, legal_name_visible, registrable_domain
from shirushi_eval.support import SourceAudit

SUBJECT, NAME = '923609016', 'Example Pumps AS'
REGISTRY_HOST, REGISTRY = 'www.example.no', 'https://www.example.no/'
HOST = 'www.pumps-example.com'
SITE = 'https://' + HOST + '/'
OPEN = 'User-agent: *\nAllow: /\n'
ROOT_PAGE = ('<html><head><title>Pumps</title></head><body><h1>Example Pumps AS</h1>'
             '<p>Example Pumps AS tilbyr pumper til industrien.</p></body></html>')
SUB_PAGE = '<html><body><p>Example Pumps AS tilbyr service og vedlikehold.</p></body></html>'
ANCHOR = '<anchor>'


def hop(source, target, status=301):
    return {'from': source, 'to': target, 'http_status': status}


def failure(requested, chain, effective=None, path='/'):
    return chain_failure(requested, chain, effective or (chain[-1]['to'] if chain else requested), REGISTRY_HOST, path)


class ChainRuleTests(unittest.TestCase):
    """Rules R1-R6 and the amendments, on bare chains."""
    def refused(self, requested, chain, effective=None, path='/'):
        self.assertIsNotNone(failure(requested, chain, effective, path), chain)

    def test_a_permanent_chain_from_the_registry_host_passes(self):
        self.assertIsNone(failure(REGISTRY, [hop(REGISTRY, SITE)]))
        self.assertIsNone(failure(REGISTRY, [hop(REGISTRY, SITE, 308)]))
        self.assertIsNone(failure('https://example.no/', [hop('https://example.no/', SITE)]))

    def test_an_alias_hop_may_precede_the_crossing_and_the_destination_alias_may_follow(self):
        self.assertIsNone(failure(REGISTRY, [hop(REGISTRY, 'https://example.no/'),
                                             hop('https://example.no/', 'https://pumps-example.com/'),
                                             hop('https://pumps-example.com/', SITE)]))

    def test_the_destination_may_carry_a_path_and_query(self):
        self.assertIsNone(failure(REGISTRY, [hop(REGISTRY, SITE + 'no/index.html?lang=nb')]))

    def test_robots_chain_uses_the_robots_path(self):
        robots = REGISTRY + 'robots.txt'
        self.assertIsNone(failure(robots, [hop(robots, SITE + 'robots.txt')], path='/robots.txt'))
        self.refused(robots, [hop(robots, SITE + 'robots.txt')], path='/')

    def test_the_first_hop_must_be_issued_by_the_registry_host(self):
        self.refused('https://www.other-site.no/', [hop('https://www.other-site.no/', SITE)])
        self.refused('https://www.evil.example/', [hop('https://www.evil.example/', REGISTRY), hop(REGISTRY, SITE)])

    def test_requested_url_must_be_the_normalised_registry_root(self):
        for requested in ('http://www.example.no/', 'https://www.example.no:8443/', 'https://www.example.no:443/',
                          'https://user@www.example.no/', 'https://www.example.no/?a=1', 'https://www.example.no/no/',
                          'https://www.example.no/#x', 'https://www.example.no./', 'https://WWW.example.no/'):
            with self.subTest(requested):
                self.refused(requested, [hop(requested, SITE)])

    def test_the_crossing_hop_must_be_for_the_fixed_registry_path(self):
        self.refused(REGISTRY, [hop(REGISTRY, 'https://www.example.no/no/'), hop('https://www.example.no/no/', SITE)])

    def test_transport_of_every_hop(self):
        for target in ('http://www.pumps-example.com/', 'https://www.pumps-example.com:8443/',
                       'https://www.pumps-example.com:443/', 'https://user:pw@www.pumps-example.com/',
                       'https://www.pumps-example.com/#frag', 'https://www.pumps-example.com./',
                       'https://www.pumps\\-example.com/', 'https://www.pumps-example.com/\n',
                       'ftp://www.pumps-example.com/', 'https://[::1]/', 'https://localhost/', 'https://intranet/',
                       'https://10.0.0.5/', 'https://192.168.1.1/', 'https://127.0.0.1/', 'https://127.1/',
                       'https://10.1/', 'https://0x7f.1/', 'https://2130706433/', 'https://server.local/',
                       'https://a..b.com/', 'https://-bad-.com/', 'https://www.pumpsé.com/'):
            with self.subTest(target):
                self.refused(REGISTRY, [hop(REGISTRY, target)])

    def test_at_most_three_hops(self):
        chain = [hop(REGISTRY, SITE + '1')] + [hop(SITE + str(i), SITE + str(i + 1)) for i in (1, 2)]
        self.assertIsNone(failure(REGISTRY, chain))
        chain.append(hop(SITE + '3', SITE + '4'))
        self.refused(REGISTRY, chain)

    def test_every_hop_must_be_permanent(self):
        for status in (302, 303, 307, 200, 300, 304, 0, '301', None, True, 301.0):
            with self.subTest(status):
                self.refused(REGISTRY, [hop(REGISTRY, SITE, status)])
        self.refused(REGISTRY, [hop(REGISTRY, 'https://example.no/', 301), hop('https://example.no/', SITE, 302)])
        self.refused(REGISTRY, [hop(REGISTRY, 'https://example.no/', 302), hop('https://example.no/', SITE, 301)])

    def test_no_third_domain_after_the_crossing(self):
        self.refused(REGISTRY, [hop(REGISTRY, SITE), hop(SITE, 'https://www.third-party.com/')])
        self.refused(REGISTRY, [hop(REGISTRY, SITE), hop(SITE, 'https://shop.pumps-example.com/')])
        self.refused(REGISTRY, [hop(REGISTRY, SITE), hop(SITE, 'https://www.pumps-example.no/')])

    def test_denylisted_destinations(self):
        for host in ('www.sparebank1.no', 'sparebank1.no', 'firm.wixsite.com', 'bit.ly', 'x.github.io', 'www.facebook.com',
                     'proff.no', 'shop.myshopify.com', 'www.dnb.no', 'foo.vercel.app', 't.co', 'sedoparking.com',
                     'www.linkedin.com', 'example.pages.dev'):
            with self.subTest(host):
                self.refused(REGISTRY, [hop(REGISTRY, 'https://' + host + '/')])

    def test_a_denylisted_later_hop_is_refused_even_after_an_allowed_destination(self):
        self.refused(REGISTRY, [hop(REGISTRY, SITE), hop(SITE, 'https://www.pumps-example.com/'),
                                hop('https://www.pumps-example.com/', 'https://bit.ly/x')])

    def test_bare_suffixes_and_their_aliases_are_refused(self):
        for host in ('priv.no', 'www.priv.no', 'com', 'www.com', 'oslo.no', 'co.uk', 'www.co.uk', 'kommune.no'):
            with self.subTest(host):
                self.refused(REGISTRY, [hop(REGISTRY, 'https://' + host + '/')])

    def test_chain_must_be_continuous_and_end_at_the_effective_url(self):
        self.refused(REGISTRY, [hop(REGISTRY, SITE + 'x')], effective=SITE)
        self.refused(REGISTRY, [hop(REGISTRY, SITE), hop(SITE + 'y', SITE + 'z')], effective=SITE + 'z')
        self.refused(REGISTRY, [hop('https://www.example.no/other', SITE)], effective=SITE)

    def test_malformed_chains_are_refused_not_raised(self):
        for chain in ([], None, 'x', [None], [{}], [{'from': REGISTRY, 'to': SITE}], [{'from': 1, 'to': 2, 'http_status': 301}],
                      [hop(REGISTRY, SITE), 'x'], {'from': REGISTRY}):
            with self.subTest(chain):
                self.assertIsNotNone(chain_failure(REGISTRY, chain, SITE, REGISTRY_HOST, '/'))
        self.assertIsNotNone(chain_failure(None, [hop(REGISTRY, SITE)], SITE, REGISTRY_HOST, '/'))
        self.assertIsNotNone(chain_failure(REGISTRY, [hop(REGISTRY, SITE)], SITE, None, '/'))
        self.assertIsNotNone(chain_failure(REGISTRY, [hop(REGISTRY, SITE)], SITE, '', '/'))

    def test_a_chain_that_never_leaves_the_registry_aliases_is_not_a_cross_domain_link(self):
        self.assertIsNotNone(failure(REGISTRY, [hop(REGISTRY, 'https://example.no/')]))


class RegistrableDomainTests(unittest.TestCase):
    def test_ordinary_and_listed_suffixes(self):
        for host, expected in {'www.example.no': 'example.no', 'example.no': 'example.no', 'a.b.example.co.uk': 'example.co.uk',
                               'x.priv.no': 'x.priv.no', 'shop.example.com.au': 'example.com.au', 'a.foo.co.jp': 'foo.co.jp',
                               'www.vind.no': 'vind.no', 'a.example.oslo.no': 'example.oslo.no', 'a.b.example.co.ke': 'example.co.ke'}.items():
            with self.subTest(host):
                self.assertEqual(registrable_domain(host), expected)

    def test_bare_suffixes_and_single_labels_have_none(self):
        for host in ('priv.no', 'com', 'localhost', 'oslo.no', 'co.uk', 'co.ke', 'kommune.no', '', None, 'a..b'):
            with self.subTest(host):
                self.assertIsNone(registrable_domain(host))


class LegalNameTests(unittest.TestCase):
    def visible(self, html):
        return legal_name_visible(html.encode(), NAME)

    def test_title_h1_footer_address_or_contact_block_names_the_exact_legal_name(self):
        for html in ('<html><head><title>Example Pumps AS - Hjem</title></head><body><p>Hei</p></body></html>',
                     '<html><body><h1>Velkommen til example pumps as</h1><p>Hei</p></body></html>',
                     '<html><body><footer>(c) Example   Pumps AS</footer></body></html>',
                     '<html><body><footer><p>Drives av Example Pumps AS</p></footer></body></html>',
                     '<html><body><address>Example Pumps AS, Storgata 1</address></body></html>',
                     '<html><body><div class="Site-Contact"><p>Example Pumps AS</p></div></body></html>',
                     '<html><body><section id="kontakt-oss"><p>Example Pumps AS</p></section></body></html>'):
            with self.subTest(html):
                self.assertTrue(self.visible(html))

    def test_the_name_in_body_text_news_or_other_blocks_does_not_anchor(self):
        wide = '<div class="contact-wrapper"><p>' + 'x ' * 800 + 'Example Pumps AS</p></div>'
        for html in ('<html><body><p>Hei fra Example Pumps AS.</p></body></html>',
                     '<html><body><main><p>Example Pumps AS er partner.</p></main></body></html>',
                     '<html><body><article><h2>Example Pumps AS vant prisen</h2><p>Nyhet</p></article></body></html>',
                     '<html><body><h2>Example Pumps AS</h2><h3>Example Pumps AS</h3></body></html>',
                     '<html><body><ul><li>Example Pumps AS</li></ul></body></html>',
                     '<html><body><div class="reseller"><p>Vi selger pumper fra Example Pumps AS.</p></div></body></html>',
                     '<html><body class="contact"><p>Example Pumps AS</p></body></html>',
                     '<html><body><main id="contact"><p>Example Pumps AS</p></main></body></html>',
                     '<html><body>' + wide + '</body></html>',
                     '<html><body><div class="contacts"><div class="x"><p>' + 'y ' * 800 + 'Example Pumps AS</p></div></div></body></html>'):
            with self.subTest(html[:80]):
                self.assertFalse(self.visible(html))

    def test_hidden_or_quoted_identity_blocks_do_not_anchor(self):
        for html in ('<html><body><footer hidden>Example Pumps AS</footer></body></html>',
                     '<html><body><footer style="display:none">Example Pumps AS</footer></body></html>',
                     '<html><body><div hidden><h1>Example Pumps AS</h1></div></body></html>',
                     '<html><body><footer><blockquote>Example Pumps AS</blockquote></footer></body></html>',
                     '<html><body><address aria-hidden="true">Example Pumps AS</address></body></html>',
                     '<html><body><footer><script>var n="Example Pumps AS"</script></footer></body></html>'):
            with self.subTest(html):
                self.assertFalse(self.visible(html))

    def test_everything_else_does_not(self):
        for html in ('<html><body><script>var n="Example Pumps AS";</script><p>Hei</p></body></html>',
                     '<html><body><div style="display:none">Example Pumps AS</div><p>Hei</p></body></html>',
                     '<html><body><div hidden>Example Pumps AS</div><p>Hei</p></body></html>',
                     '<html><body><div aria-hidden="true">Example Pumps AS</div><p>Hei</p></body></html>',
                     '<html><body><!-- Example Pumps AS --><p>Hei</p></body></html>',
                     '<html><body><template>Example Pumps AS</template><p>Hei</p></body></html>',
                     '<html><body><noscript>Example Pumps AS</noscript><p>Hei</p></body></html>',
                     '<html><head><style>.a{content:"Example Pumps AS"}</style></head><body><p>Hei</p></body></html>',
                     '<html><body><img alt="Example Pumps AS" src="x.png"><p>Hei</p></body></html>',
                     '<html><body><meta name="description" content="Example Pumps AS"><p>Hei</p></body></html>',
                     '<html><body><footer>Example Pumps ASA er et selskap.</footer></body></html>',
                     '<html><body><footer>MyExample Pumps AS eier oss.</footer></body></html>',
                     '<html><body><h1>Example Pumps AS2</h1></body></html>',
                     '<html><body><p>Example Pumps</p></body></html>',
                     '<html><body><blockquote><h1>Example Pumps AS</h1></blockquote></body></html>',
                     '<html><body><p>Hei</p></body></html>', ''):
            with self.subTest(html):
                self.assertFalse(self.visible(html))

    def test_undecodable_bytes_are_not_a_name(self):
        self.assertFalse(legal_name_visible(b'\xff\xfe<p>Example Pumps AS</p>', NAME))

    def test_empty_name_never_matches(self):
        self.assertFalse(legal_name_visible(b'<p>anything</p>', ''))
        self.assertFalse(legal_name_visible(b'<p>anything</p>', None))


class AuditBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(Path(self.temp.name))
        self.anchor = self.registry_row()

    def registry_row(self, host='www.example.no', name=NAME):
        raw = json.dumps({'organisasjonsnummer': SUBJECT, 'navn': name, 'hjemmeside': host}).encode()
        return self.store.save(raw, dict(organisation_number=SUBJECT, source_class='brreg_entity',
            source_url='https://data.brreg.no/enhetsregisteret/api/enheter/' + SUBJECT, http_status=200,
            sha256=digest(raw), retrieved_at='2026-10-10T08:00:00Z'))

    def robots(self, host, text=OPEN, status=200, **extra):
        raw = text.encode() if status == 200 else b''
        url = extra.pop('source_url', 'https://' + host + '/robots.txt')
        meta = dict(source_class='robots_policy', source_url=url, effective_url=extra.pop('effective_url', url),
                    http_status=status, sha256=digest(raw), retrieved_at='2026-10-10T08:00:00Z',
                    content_type='text/plain', source_origin=host, redirect_chain=[],
                    access_policy='public-robots-policy')
        meta.update(extra)
        return self.store.save(raw, meta)

    def page(self, text, path='/', host=HOST, chain=None, requested=REGISTRY, **extra):
        """A company page receipt; a value of None in extra removes that field."""
        raw = text.encode()
        url = 'https://' + host + path
        if chain is None:
            chain = [hop(REGISTRY, url)]
        meta = dict(organisation_number=SUBJECT, source_class='company_owned', requested_url=requested, source_url=url,
                    effective_url=url, http_status=200, sha256=digest(raw), declared_host=host, source_origin=host,
                    robots_checked=True, retrieved_at='2026-10-10T08:00:00Z', ownership_anchor_snapshot_id=self.anchor,
                    redirect_chain=chain, content_type='text/html',
                    robots_snapshot_id=extra.pop('robots_snapshot_id', None) or self.robots(host))
        meta.update(extra)
        return self.store.save(raw, {k: v for k, v in meta.items() if v is not None})

    def root(self, text=ROOT_PAGE, **kw):
        kw.setdefault('registry_robots_snapshot_id', self.robots(REGISTRY_HOST))
        return self.page(text, **kw)

    def sub(self, root, text=SUB_PAGE, path='/tjenester', host=HOST, **kw):
        url = 'https://' + host + path
        kw.setdefault('redirect_anchor_snapshot_id', root)
        return self.page(text, path, host, chain=[], requested=url, **kw)

    def genuine(self):
        """The maker's own decision for a sub page under a good root."""
        sid = self.sub(self.root())
        decisions = check_web(self.store, SUBJECT, sid)
        self.assertEqual([d['field'] for d in decisions], ['product_service'])
        return decisions[0], sid

    def run_audit(self, decision, sid):
        decision = copy.deepcopy(decision)
        _, receipt = self.store.open(sid)
        item = decision['evidence']
        item.update(snapshot_id=sid, source_url=receipt['source_url'], content_sha256=receipt['content_sha256'])
        SourceAudit(self.store.root, [SUBJECT]).claim(SUBJECT, decision['claim'], {item['id']: item})

    def accepted(self, decision, sid):
        self.run_audit(decision, sid)

    def rejected(self, decision, sid, reason):
        with self.assertRaisesRegex(ValueError, 'Audit website discovery anchor mismatch.*' + reason):
            self.run_audit(decision, sid)


class AcceptedChainTests(AuditBase):
    def test_sub_page_under_a_verified_chain_root_is_supported(self):
        decision, sid = self.genuine()
        self.accepted(decision, sid)

    def test_the_chain_root_page_is_its_own_anchor(self):
        sid = self.root()
        decisions = check_web(self.store, SUBJECT, sid)
        self.assertEqual([d['field'] for d in decisions], ['product_service'])
        self.accepted(decisions[0], sid)

    def test_registry_robots_reached_by_a_permanent_cross_domain_redirect_is_supported(self):
        decision, _ = self.genuine()
        robots = REGISTRY + 'robots.txt'
        registry = self.robots(REGISTRY_HOST, source_url=robots, effective_url=SITE + 'robots.txt',
                               redirect_chain=[hop(robots, SITE + 'robots.txt')])
        root = self.root(registry_robots_snapshot_id=registry)
        self.accepted(decision, self.sub(root))

    def test_registry_robots_absent_is_supported_as_404(self):
        decision, _ = self.genuine()
        root = self.root(registry_robots_snapshot_id=self.robots(REGISTRY_HOST, status=404))
        self.accepted(decision, self.sub(root))

    def test_name_only_in_the_title_of_the_root_is_enough(self):
        decision, _ = self.genuine()
        root = self.root('<html><head><title>Example Pumps AS</title></head><body><p>Hei</p></body></html>')
        self.accepted(decision, self.sub(root))

    def test_a_different_www_alias_of_the_registry_host_may_start_the_chain(self):
        decision, _ = self.genuine()
        origin = 'https://example.no/'
        root = self.root(requested=origin, chain=[hop(origin, SITE)],
                         registry_robots_snapshot_id=self.robots('example.no'))
        self.accepted(decision, self.sub(root))


class RejectedChainTests(AuditBase):
    def forged_root(self, reason, **kw):
        decision, _ = self.genuine()
        self.rejected(decision, self.sub(self.root(**kw)), reason)

    def test_first_hop_not_issued_by_the_registry_host(self):
        other = 'https://www.other-site.no/'
        self.forged_root('requested', requested=other, chain=[hop(other, SITE)])

    def test_an_alias_hop_from_a_foreign_origin_is_not_a_registry_chain(self):
        foreign = 'https://www.evil.example/'
        self.forged_root('requested', requested=foreign, chain=[hop(foreign, REGISTRY), hop(REGISTRY, SITE)])

    def test_transport_violations(self):
        for target in ('http://' + HOST + '/', 'https://' + HOST + ':8443/', 'https://u:p@' + HOST + '/'):
            with self.subTest(target):
                self.forged_root('chain', chain=[hop(REGISTRY, target)], effective_url=target)

    def test_private_destination(self):
        url = 'https://10.0.0.5/'
        self.forged_root('chain', host='10.0.0.5', chain=[hop(REGISTRY, url)])

    def test_four_hops(self):
        chain = [hop(REGISTRY, SITE + '0')] + [hop(SITE + str(i), SITE + str(i + 1)) for i in range(3)]
        self.forged_root('chain', chain=chain, path='/3')

    def test_temporary_statuses(self):
        for status in (302, 303, 307):
            with self.subTest(status):
                self.forged_root('chain', chain=[hop(REGISTRY, SITE, status)])
        self.forged_root('chain', chain=[hop(REGISTRY, 'https://example.no/'), hop('https://example.no/', SITE, 307)])

    def test_denylisted_destinations(self):
        for host in ('www.sparebank1.no', 'firm.wixsite.com', 'bit.ly', 'proff.no'):
            with self.subTest(host):
                self.forged_root('chain', host=host, chain=[hop(REGISTRY, 'https://' + host + '/')])

    def test_third_domain_after_the_crossing(self):
        third = 'https://www.third-party.com/'
        self.forged_root('chain', host='www.third-party.com', chain=[hop(REGISTRY, SITE), hop(SITE, third)])

    def test_chain_that_does_not_end_at_the_effective_url(self):
        self.forged_root('chain', chain=[hop(REGISTRY, SITE + 'elsewhere')])

    def test_root_without_any_chain(self):
        self.forged_root('chain', chain=[], requested=SITE)

    def test_root_with_the_chain_field_missing(self):
        self.forged_root('chain', chain=None, requested=REGISTRY, redirect_chain=None)

    def test_requested_url_missing_or_not_the_registry_host(self):
        self.forged_root('requested', requested=None)
        self.forged_root('requested', requested='https://www.example.no/no/')

    def test_registry_row_for_another_host_proves_nothing(self):
        decision, _ = self.genuine()
        self.anchor = self.registry_row('www.unrelated.no')
        self.rejected(decision, self.sub(self.root()), 'requested')

    def test_sub_page_without_an_anchor_stays_unanchored(self):
        decision, _ = self.genuine()
        self.rejected(decision, self.sub(self.root(), redirect_anchor_snapshot_id=None), 'chain')

    def test_anchor_that_is_not_a_snapshot(self):
        decision, _ = self.genuine()
        for forged in ('0' * 64, 'x', 5):
            with self.subTest(forged):
                self.rejected(decision, self.sub(self.root(), redirect_anchor_snapshot_id=forged), 'anchor')

    def test_anchor_pointing_at_a_page_that_is_not_a_chain_root(self):
        decision, _ = self.genuine()
        plain = self.page(ROOT_PAGE, chain=[], requested=SITE)
        self.rejected(decision, self.sub(plain), 'chain')

    def test_anchor_pointing_at_the_registry_row(self):
        decision, _ = self.genuine()
        self.rejected(decision, self.sub(self.anchor), 'anchor')

    def test_anchor_chains_do_not_recurse(self):
        decision, _ = self.genuine()
        inner = self.root()
        middle = self.sub(inner, '<html><body><p>Example Pumps AS tilbyr noe.</p></body></html>', '/a')
        self.rejected(decision, self.sub(middle), 'anchor')

    def test_anchor_on_another_host(self):
        decision, _ = self.genuine()
        root = self.root(host='www.elsewhere.com', chain=[hop(REGISTRY, 'https://www.elsewhere.com/')])
        self.rejected(decision, self.sub(root), 'host')

    def test_anchor_from_another_organisation_or_ownership_anchor(self):
        decision, _ = self.genuine()
        self.rejected(decision, self.sub(self.root(organisation_number='999999999')), 'organisation')
        other = self.registry_row('www.example.no', 'Other Name AS')
        self.rejected(decision, self.sub(self.root(ownership_anchor_snapshot_id=other)), 'ownership')

    def test_root_receipt_must_describe_a_good_fetch(self):
        decision, _ = self.genuine()
        cases = {'status': dict(http_status=404), 'robots': dict(robots_checked=False), 'robots_none': dict(robots_checked=None),
                 'class': dict(source_class='jobs'), 'hash': dict(sha256='0' * 64),
                 'host': dict(declared_host='www.other.com'), 'source': dict(source_url=SITE + 'other')}
        for label, kw in cases.items():
            with self.subTest(label):
                self.rejected(decision, self.sub(self.root(**kw)), 'root')


class IdentityTests(AuditBase):
    def rejected_root(self, text):
        decision, _ = self.genuine()
        self.rejected(decision, self.sub(self.root(text)), 'legal name')

    def test_root_without_the_legal_name(self):
        self.rejected_root('<html><head><title>Pumps</title></head><body><p>Velkommen</p></body></html>')

    def test_trade_name_without_the_legal_form(self):
        self.rejected_root('<html><head><title>Example Pumps</title></head><body><p>Example Pumps leverer.</p></body></html>')

    def test_name_only_in_script_hidden_or_comment(self):
        for text in ('<html><body><script>var n="Example Pumps AS";</script><p>Hei</p></body></html>',
                     '<html><body><div style="display:none">Example Pumps AS</div><p>Hei</p></body></html>',
                     '<html><body><!-- Example Pumps AS --><p>Hei</p></body></html>'):
            with self.subTest(text):
                self.rejected_root(text)

    def test_longer_name_is_not_the_exact_name(self):
        self.rejected_root('<html><body><p>Example Pumps ASA er et selskap.</p></body></html>')

    def test_a_sub_page_naming_the_company_does_not_vouch_for_a_root_that_does_not(self):
        # The claim page itself carries the exact name; only the chain root counts for the link.
        self.rejected_root('<html><body><p>Hei</p></body></html>')


class RobotsTests(AuditBase):
    def rejected_with(self, reason, **kw):
        decision, _ = self.genuine()
        self.rejected(decision, self.sub(self.root(**kw)), reason)

    def test_final_host_robots_disallow_of_the_root_page(self):
        self.rejected_with('robots', robots_snapshot_id=self.robots(HOST, 'User-agent: *\nDisallow: /\n'))

    def test_final_host_robots_must_be_retained_for_a_redirect_linked_root(self):
        decision, _ = self.genuine()
        root = self.page(ROOT_PAGE, registry_robots_snapshot_id=self.robots(REGISTRY_HOST))
        raw, receipt = self.store.open(root)
        receipt.pop('robots_snapshot_id')
        bare = self.store.save(raw, receipt)
        self.rejected(decision, self.sub(bare), 'robots')

    def test_final_host_robots_from_another_host_or_status(self):
        self.rejected_with('robots', robots_snapshot_id=self.robots('www.elsewhere.com'))
        self.rejected_with('robots', robots_snapshot_id=self.robots(HOST, status=500))

    def test_registry_robots_disallowing_the_requested_url(self):
        self.rejected_with('registry robots',
                           registry_robots_snapshot_id=self.robots(REGISTRY_HOST, 'User-agent: *\nDisallow: /\n'))
        self.rejected_with('registry robots',
                           registry_robots_snapshot_id=self.robots(REGISTRY_HOST, 'User-agent: Shirushi\nDisallow: /\n'))

    def test_registry_robots_missing(self):
        self.rejected_with('registry robots', registry_robots_snapshot_id=None)

    def test_registry_robots_of_the_wrong_origin_class_or_status(self):
        self.rejected_with('registry robots', registry_robots_snapshot_id=self.robots(HOST))
        self.rejected_with('registry robots', registry_robots_snapshot_id=self.robots(REGISTRY_HOST, status=403))
        self.rejected_with('registry robots', registry_robots_snapshot_id=self.anchor)
        self.rejected_with('registry robots', registry_robots_snapshot_id='0' * 64)
        self.rejected_with('registry robots', registry_robots_snapshot_id=self.page(ROOT_PAGE, chain=[], requested=SITE))

    def test_registry_robots_whose_own_chain_breaks_the_rules(self):
        robots = REGISTRY + 'robots.txt'
        for chain, effective in (([hop(robots, SITE + 'robots.txt', 302)], SITE + 'robots.txt'),
                                 ([hop(robots, 'http://' + HOST + '/robots.txt')], 'http://' + HOST + '/robots.txt'),
                                 ([hop(robots, 'https://bit.ly/robots.txt')], 'https://bit.ly/robots.txt'),
                                 ([hop(robots, 'https://www.sparebank1.no/robots.txt')], 'https://www.sparebank1.no/robots.txt')):
            with self.subTest(chain):
                self.rejected_with('registry robots', registry_robots_snapshot_id=self.robots(
                    REGISTRY_HOST, source_url=robots, effective_url=effective, redirect_chain=chain))

    def test_registry_robots_tampered_after_the_fact(self):
        decision, _ = self.genuine()
        registry = self.robots(REGISTRY_HOST)
        sid = self.sub(self.root(registry_robots_snapshot_id=registry))
        (self.store.root / 'receipts' / (registry + '.json')).write_bytes(b'{}')
        self.rejected(decision, sid, 'registry robots')

    def test_robots_object_replaced_after_the_fact(self):
        decision, _ = self.genuine()
        registry = self.robots(REGISTRY_HOST, OPEN + '# registry copy\n')
        receipt = self.store.open(registry)[1]
        sid = self.sub(self.root(registry_robots_snapshot_id=registry))
        (self.store.root / 'objects' / (receipt['content_sha256'] + '.bin')).write_bytes(b'User-agent: *\nDisallow: /\n')
        self.rejected(decision, sid, 'registry robots')


class TamperingTests(AuditBase):
    def test_root_receipt_replaced_after_the_fact(self):
        decision, _ = self.genuine()
        root = self.root()
        sid = self.sub(root)
        (self.store.root / 'receipts' / (root + '.json')).write_bytes(b'{}')
        self.rejected(decision, sid, 'root')

    def test_root_object_replaced_after_the_fact(self):
        decision, _ = self.genuine()
        root = self.root()
        receipt = self.store.open(root)[1]
        sid = self.sub(root)
        (self.store.root / 'objects' / (receipt['content_sha256'] + '.bin')).write_bytes(b'<p>Example Pumps AS</p>')
        self.rejected(decision, sid, 'root')

    def test_a_root_that_is_missing_from_the_store(self):
        decision, _ = self.genuine()
        root = self.root()
        sid = self.sub(root)
        (self.store.root / 'receipts' / (root + '.json')).unlink()
        self.rejected(decision, sid, 'root')


class ProofAndRegistryHostUnchangedTests(AuditBase):
    def test_a_page_on_the_registry_host_needs_no_chain(self):
        raw = SUB_PAGE.encode()
        url = REGISTRY + 'tjenester'
        sid = self.store.save(raw, dict(organisation_number=SUBJECT, source_class='company_owned', source_url=url,
            effective_url=url, http_status=200, sha256=digest(raw), declared_host=REGISTRY_HOST,
            source_origin=REGISTRY_HOST, robots_checked=True, retrieved_at='2026-10-10T08:00:00Z',
            ownership_anchor_snapshot_id=self.anchor, robots_snapshot_id=self.robots(REGISTRY_HOST)))
        decision = check_web(self.store, SUBJECT, sid)[0]
        self.accepted(decision, sid)

    def test_a_foreign_host_without_chain_or_proof_is_still_refused(self):
        decision, _ = self.genuine()
        plain = self.page(SUB_PAGE, '/tjenester', chain=[], requested=SITE + 'tjenester')
        with self.assertRaisesRegex(ValueError, 'Audit website discovery anchor mismatch'):
            self.run_audit(decision, plain)

    def proof_page(self, path):
        text = ('<html><body><p>Vilkår mellom Example Pumps AS og deres kunder. Org.nr 923 609 016.</p></body></html>')
        return self.page(text, path, chain=[], requested=SITE + path.lstrip('/'))

    def test_exact_operator_proof_does_not_consult_the_chain(self):
        decision, _ = self.genuine()
        proof = self.proof_page('/tjenester/avtale.html')
        sid = self.sub(self.root(chain=[hop(REGISTRY, SITE, 302)]), SUB_PAGE,
                       path='/tjenester/x', operator_snapshot_id=proof)
        # The proof lifts the host gate exactly as before; the linked-HTML route then fails on its own host rule.
        with self.assertRaisesRegex(ValueError, 'lacks registry host linkage'):
            self.run_audit(decision, sid)

    def test_seller_path_scoping_still_applies_to_a_proven_redirect_host(self):
        decision, _ = self.genuine()
        proof = self.proof_page('/vilkaar/avtale.html')
        sid = self.sub(self.root(), operator_snapshot_id=proof, path='/tjenester')
        with self.assertRaisesRegex(ValueError, 'escapes verified seller path'):
            self.run_audit(decision, sid)

    def test_a_redirect_link_never_establishes_website_ownership(self):
        decision, _ = self.genuine()
        forged = copy.deepcopy(decision)
        forged['claim']['field'] = 'verified_website'
        with self.assertRaisesRegex(ValueError, 'anchor mismatch.*never establishes website ownership'):
            self.run_audit(forged, self.sub(self.root()))


class DownstreamRoutesTests(AuditBase):
    def test_a_redirect_link_does_not_lift_the_operator_only_routes(self):
        decision, _ = self.genuine()
        sid = self.sub(self.root())
        for method in ('explicit_subject_html_v1', 'scoped_catalogue_html_v2'):
            forged = copy.deepcopy(decision)
            forged['evidence']['extraction_method'] = method
            with self.subTest(method), self.assertRaises(ValueError) as caught:
                self.run_audit(forged, sid)
            self.assertNotIn('anchor mismatch', str(caught.exception))  # the host gate passed; the route itself refuses


class WholeWorkerAgreementTests(unittest.TestCase):
    """What the maker's worker persists for a redirected registry site is what the auditor re-verifies."""
    def run_worker(self, pages, allow=True):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        config = load(ROOT / 'configs/local-external.json')
        config.update(enabled_sources=['brreg_entity', 'company_owned'], min_host_interval_seconds=0, max_retries=0)
        if allow:
            config['allow_registry_redirects'] = True
        frames = []

        class Connection:
            def send(self, frame): frames.append(frame)
            def close(self): pass

        def transport(fetcher, url, timeout, limit, headers=None, request_body=None):
            if 'data.brreg.no' in url:
                status, kind, raw = 200, 'application/json', json.dumps({
                    'organisasjonsnummer': SUBJECT, 'navn': NAME, 'hjemmeside': REGISTRY_HOST,
                    '_links': {'self': {'href': url}}}).encode()
            elif url.endswith('/robots.txt'):
                status, kind, raw = 200, 'text/plain', OPEN.encode()
            elif isinstance(pages.get(url), tuple):
                fetcher.budget.consume(0)
                return pages[url][0], {'location': pages[url][1]}, b''
            else:
                status, kind, raw = 200, 'text/html', pages.get(url, '<p>Tom</p>').encode()
            fetcher.budget.consume(len(raw))
            return status, {'content-type': kind}, raw

        job = {'store': Path(temp.name), 'subjects': [SUBJECT], 'previous': {}, 'config': config,
               'deadline': time.monotonic() + 10, 'started_at': '2026-10-12T08:00:00Z', 'run_id': 'redirect-audit',
               'discovery': None}
        with unittest.mock.patch('shirushi.fetch.Fetcher._request', transport):
            from shirushi.live import worker
            worker(Connection(), job)
        self.assertFalse([f for f in frames if f[0] == 'fatal'])
        return next(f[2]['envelope'] for f in frames if f[0] == 'result'), Path(temp.name)

    def audit_all(self, result, store):
        audit = SourceAudit(store, [SUBJECT])
        evidence = {e['id']: e for e in result['evidence']}
        claims = [c for c in result['claims'] if c['availability'] == 'available']
        for claim in claims:
            audit.claim(SUBJECT, claim, evidence)
        return claims

    def test_published_claims_of_a_redirected_site_pass_the_independent_audit(self):
        pages = {REGISTRY: (301, SITE), SITE: '<html><body><h1>Example Pumps AS</h1><p>Example Pumps AS tilbyr pumper til industrien.</p>'
                                              '<a href="/om-oss">Om oss</a></body></html>',
                 SITE + 'om-oss': '<html><body><p>Example Pumps AS leverer service og vedlikehold.</p></body></html>'}
        result, store = self.run_worker(pages)
        claims = self.audit_all(result, store)
        self.assertIn('product_service', {c['field'] for c in claims})
        self.assertGreaterEqual(len({e['source_url'] for e in result['evidence']}), 2)  # root and the inheriting child

    def test_the_audit_refuses_the_same_run_when_the_registry_robots_receipt_is_removed(self):
        pages = {REGISTRY: (301, SITE), SITE: '<html><body><h1>Example Pumps AS</h1><p>Example Pumps AS tilbyr pumper til industrien.</p></body></html>'}
        result, store = self.run_worker(pages)
        receipts = [json.loads(path.read_text(encoding='utf-8')) for path in (store / 'receipts').glob('*.json')]
        removed = {r['registry_robots_snapshot_id'] for r in receipts if r.get('registry_robots_snapshot_id')}
        self.assertTrue(removed)
        for identifier in removed:
            (store / 'receipts' / (identifier + '.json')).unlink()
        with self.assertRaisesRegex(ValueError, 'registry robots'):
            self.audit_all(result, store)

    def test_the_maker_does_not_publish_a_json_ld_verified_website_for_a_redirect_only_host(self):
        # SPEC R11: a redirect link never yields verified_website, also not through the JSON-LD identifier route.
        ld = ('<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization",'
              '"name":"Example Pumps AS","identifier":"923609016","url":"' + SITE + '"}</script>')
        pages = {REGISTRY: (301, SITE), SITE: '<html><body>' + ld + '<h1>Example Pumps AS</h1>'
                                              '<p>Example Pumps AS tilbyr pumper.</p></body></html>'}
        result, store = self.run_worker(pages)
        self.assertNotIn('verified_website', {c['field'] for c in result['claims'] if c['availability'] == 'available'})
        self.audit_all(result, store)

    def test_a_forged_verified_website_on_a_redirect_only_host_is_refused_by_the_audit(self):
        ld = ('<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization",'
              '"name":"Example Pumps AS","identifier":"923609016","url":"' + SITE + '"}</script>')
        pages = {REGISTRY: (301, SITE), SITE: '<html><body>' + ld + '<h1>Example Pumps AS</h1>'
                                              '<p>Example Pumps AS tilbyr pumper.</p></body></html>'}
        result, store = self.run_worker(pages)
        claim = next(c for c in result['claims'] if c['availability'] == 'available' and c['field'] == 'product_service')
        forged = dict(claim, field='verified_website')
        with self.assertRaisesRegex(ValueError, 'never establishes website ownership'):
            SourceAudit(store, [SUBJECT]).claim(SUBJECT, forged, {e['id']: e for e in result['evidence']})

    def test_with_the_opt_in_flag_off_the_maker_refuses_and_nothing_redirect_linked_is_published(self):
        pages = {REGISTRY: (301, SITE), SITE: '<html><body><h1>Example Pumps AS</h1>'
                                              '<p>Example Pumps AS tilbyr pumper til industrien.</p></body></html>'}
        result, store = self.run_worker(pages, allow=False)
        fields = {c['field'] for c in result['claims'] if c['availability'] == 'available'}
        self.assertNotIn('product_service', fields)
        self.assertNotIn('verified_website', fields)
        receipts = [json.loads(path.read_text(encoding='utf-8')) for path in (store / 'receipts').glob('*.json')]
        self.assertFalse([r for r in receipts if r.get('source_class') == 'company_owned' and r.get('redirect_chain')])
        self.audit_all(result, store)


if __name__ == '__main__':
    unittest.main()
