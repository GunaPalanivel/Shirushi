"""Independent audit of social_profile claims: producer is check_web, checker is SourceAudit."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from shirushi.snapshots import SnapshotStore, digest
from shirushi.web_sources import check_web
from shirushi_eval.support import SourceAudit

METHOD = 'social_profile_link_v1'
SUBJECT = '923609016'
FB = 'https://www.facebook.com/FjordheimBygg'


def page(body, head=''):
    return '<!doctype html><html><head><title>Fjordheim</title>' + head + '</head><body>' + body + '</body></html>'


def footer(*hrefs):
    return page('<footer><div class="social">' + ''.join('<a href="%s"><i></i></a>' % h for h in hrefs) + '</div></footer>')


def ld(payload):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return '<script type="application/ld+json">' + text + '</script>'


class SocialAuditBase(unittest.TestCase):
    name = 'Fjordheim Bygg AS'
    registry_host = 'fjordheim.example'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(Path(self.temp.name))
        self.use_name(self.name)

    def use_name(self, name):
        raw = json.dumps({'organisasjonsnummer': SUBJECT, 'navn': name, 'hjemmeside': self.registry_host}).encode()
        self.anchor = self.store.save(raw, dict(organisation_number=SUBJECT, source_class='brreg_entity',
            source_url='https://data.brreg.no/enhetsregisteret/api/enheter/' + SUBJECT, http_status=200,
            sha256=digest(raw), retrieved_at='2026-10-10T08:00:00Z'))

    def save(self, html, host=None, path='/'):
        host = host or self.registry_host
        raw = html.encode()
        return self.store.save(raw, dict(organisation_number=SUBJECT, source_class='company_owned',
            source_url='https://%s%s' % (host, path), effective_url='https://%s%s' % (host, path), http_status=200,
            sha256=digest(raw), declared_host=host, source_origin=host, robots_checked=True,
            retrieved_at='2026-10-10T08:00:00Z', ownership_anchor_snapshot_id=self.anchor))

    def decisions(self, html, host=None, path='/'):
        sid = self.save(html, host, path)
        self.sid = sid
        return [d for d in check_web(self.store, SUBJECT, sid) if d['field'] == 'social_profile']

    def audit(self, decision):
        SourceAudit(self.store.root, [SUBJECT]).claim(SUBJECT, decision['claim'],
                                                      {decision['evidence']['id']: decision['evidence']})

    def rejects(self, decision, message='Audit social|Evidence span|Evidence origin|Audit website discovery'):
        with self.assertRaisesRegex(ValueError, message):
            self.audit(decision)

    def published(self, html, **kw):
        found = self.decisions(html, **kw)
        for decision in found:
            self.assertEqual(decision['evidence']['extraction_method'], METHOD)
        return found

    def one(self, html, **kw):
        found = self.published(html, **kw)
        self.assertEqual(len(found), 1, html)
        return found[0]

    def forged(self, html, tag, value, canonical_url, platform, *, source='a_href', score=0.98, tokens=('fjordheim', 'bygg'),
               host=None, path='/', scope='registry_linked_html', raw_url=None, occurrence=0):
        """A decision the maker would never publish, pointing at the opening tag `tag` of the page."""
        sid = self.save(html, host, path)
        raw, receipt = self.store.open(sid)
        text = raw.decode()
        start = -1
        for _ in range(occurrence + 1):
            start = text.index(tag, start + 1)
        end = start + len(tag)
        name = tag[1:].split()[0].rstrip('>/')
        close = text.find('</%s>' % name, end)
        locator = {'source': source, 'raw_url': raw_url if raw_url is not None else tag.split('"')[1], 'html_start': start,
                   'html_end': end, 'element_end': close + len(name) + 3 if close >= 0 else len(text),
                   'platform': platform, 'handle_score': score, 'handle_tokens': list(tokens), 'canonical_url': canonical_url}
        return self.assemble(sid, host or self.registry_host, path, value, tag, locator, scope)

    def assemble(self, sid, host, path, value, span, locator, scope='registry_linked_html', method=METHOD):
        raw, _ = self.store.open(sid)
        encoded = json.dumps([SUBJECT, 'social_profile', scope, value, None], ensure_ascii=False,
                             sort_keys=True, separators=(',', ':')).encode()
        cid = hashlib.sha256(encoded).hexdigest()
        eid = sid + ':' + cid
        claim = {'claim_id': cid, 'field': 'social_profile', 'value': value, 'scope': scope, 'family': 'website_owned_profiles',
                 'item_key': value, 'period': None, 'availability': 'available', 'evidence_ids': [eid], 'freshness': 'live_source'}
        evidence = {'id': eid, 'snapshot_id': sid, 'source_url': 'https://%s%s' % (host, path), 'source_class': 'company_owned',
                    'source_origin': host, 'retrieved_at': '2026-10-10T08:00:00Z', 'content_sha256': digest(raw),
                    'claim_span': span, 'locator': locator, 'support_spans': {}, 'extraction_method': method}
        return {'field': 'social_profile', 'family': 'website_owned_profiles', 'accepted': True, 'claim': claim, 'evidence': evidence}

    def retarget(self, decision, **claim_changes):
        """Change claim fields and keep the claim id consistent with the new scope/value/item key."""
        decision = copy.deepcopy(decision)
        decision['claim'].update(claim_changes)
        claim = decision['claim']
        encoded = json.dumps([SUBJECT, claim['field'], claim['scope'], claim['item_key'], claim['period']], ensure_ascii=False,
                             sort_keys=True, separators=(',', ':')).encode()
        claim['claim_id'] = hashlib.sha256(encoded).hexdigest()
        return decision


class PublishedClaimsAreAudited(SocialAuditBase):
    def test_footer_icons_and_all_platforms(self):
        found = self.published(footer(FB + '/', 'https://www.linkedin.com/company/fjordheim-bygg-as/', 'https://instagram.com/fjordheimbygg',
                                      'https://twitter.com/FjordheimBygg', 'https://www.youtube.com/@FjordheimBygg',
                                      'https://www.tiktok.com/@fjordheimbygg'))
        self.assertEqual(len(found), 6)
        for decision in found:
            self.audit(decision)

    def test_json_ld_in_graph_publisher_and_string_forms(self):
        payloads = [{'@context': 'https://schema.org', '@graph': [{'@type': 'WebSite'}, {'@type': 'Organization', 'name': 'Fjordheim Bygg AS',
                     'sameAs': [FB, 'https://x.com/FjordheimBygg']}]},
                    {'@type': 'WebPage', 'publisher': {'@type': 'Organization', 'sameAs': FB}},
                    [{'@type': 'WebPage', 'mainEntity': [{'@type': 'Organization', 'name': 'FJORDHEIM BYGG', 'sameAs': [FB]}]}]]
        for payload in payloads:
            text = payload if isinstance(payload, str) else json.dumps(payload)
            with self.subTest(payload=text):
                found = self.published(page('', ld(text)))
                self.assertTrue(found)
                for decision in found:
                    self.audit(decision)
        raw_slash = page('', ld('{"sameAs": ["https:\\/\\/x.com\\/FjordheimBygg"]}'))
        decision = self.one(raw_slash)
        self.audit(decision)
        self.assertEqual(json.loads(decision['evidence']['claim_span']), 'https://x.com/FjordheimBygg')

    def test_plugin_iframe_data_href_and_relative_forms(self):
        html = page('<iframe src="https://www.facebook.com/plugins/page.php?href=https%3A%2F%2Fwww.facebook.com%2FFjordheimBygg%2F&tabs=x"></iframe>'
                    '<div class="fb-page" data-href="https://www.instagram.com/fjordheimbygg/"></div>'
                    '<a href="//www.linkedin.com/company/fjordheim-bygg-as">in</a>'
                    '<a href="https://www.facebook.com/people/Fjordheim-Bygg-AS/100063812345678/photos">p</a>'
                    '<a href="https://www.youtube.com/channel/UCfjordheimbygg/videos">y</a>')
        found = self.published(html)
        self.assertEqual(len(found), 5)
        for decision in found:
            self.audit(decision)

    def test_locator_corner_cases_audit(self):
        for html in (page('<footer><a href="%s">x</footer>' % FB), '<html><body><a href="%s">x' % FB,
                     page('<a href="%s" />' % FB), page('<div data-href="%s"/>' % FB),
                     page('<a href="  %s/ ">x</a>' % FB), page('<a href="%s?a=1&amp;b=2">x</a>' % FB),
                     page('<div hidden><span></div><a href="%s">x</a>' % FB),
                     page('<a href="%s" data-href="https://www.instagram.com/fjordheimbygg">x</a>' % FB),
                     page('<a href="HTTP://WWW.Facebook.COM/FjordheimBygg">x</a>'),
                     page('<a href="https://www.linkedin.com/Company/Fjordheim-Bygg-AS/">x</a>')):
            with self.subTest(html=html):
                found = self.published(html)
                self.assertTrue(found)
                for decision in found:
                    self.audit(decision)

    def test_script_index_counts_hidden_and_non_candidate_scripts(self):
        html = page('<div hidden>' + ld({'sameAs': ['https://x.com/Nope']}) + '</div>'
                    '<!-- ' + ld({'x': 1}) + ' -->' + '<script>var a=1</script>'
                    + ld({'sameAs': ['https://x.com/FjordheimBygg']}))
        decision = self.one(html)
        self.assertEqual(decision['evidence']['locator']['script_index'], 1)
        self.audit(decision)

    def test_company_owned_scope_on_a_proven_page_and_registry_scope_on_the_registry_host(self):
        proven = page('<footer><p>© 2026 Fjordheim Bygg AS. Org.nr 923 609 016</p><a href="%s">f</a></footer>' % FB)
        decision = self.one(proven, host='brand.example')
        self.assertEqual(decision['claim']['scope'], 'company_owned_html')
        self.audit(decision)
        decision = self.one(footer(FB))
        self.assertEqual(decision['claim']['scope'], 'registry_linked_html')
        self.audit(decision)

    def test_group_site_rules_accepted_cases(self):
        for host, path, href in (('fjordheim.example', '/nb-no/vilkar', FB), ('fjordheim.example', '/nb-no/', FB + '.no'),
                                 ('fjordheim.example', '/en-gb/', FB + '-Norge'), ('fjordheim.example', '/nb-no/', FB + 'Norway')):
            with self.subTest(path=path, href=href):
                found = self.published(footer(href), path=path)
                # fjordheim.example is not .no and has locale path: only market-marked channels publish.
                for decision in found:
                    self.audit(decision)
        self.assertEqual(len(self.published(footer(FB), path='/en/')), 1)

    def test_case_variants_are_one_claim_and_the_first_occurrence_supplies_the_span(self):
        html = footer('https://facebook.com/FjordheimBygg', 'https://facebook.com/fjordheimbygg', 'http://www.facebook.com/FjordheimBygg?x=1')
        found = self.published(html)
        self.assertEqual(len(found), 1)
        self.audit(found[0])
        self.assertTrue(found[0]['evidence']['claim_span'].startswith('<a href="https://facebook.com/FjordheimBygg"'))

    def test_json_ld_before_html_wins_in_document_order(self):
        html = page('<a href="https://x.com/FjordheimBygg">x</a>', ld({'sameAs': ['https://x.com/FjordheimBygg']}))
        decision = self.one(html)
        self.assertEqual(decision['evidence']['locator']['source'], 'json_ld_same_as')
        self.audit(decision)

    def test_context_accept_blocks(self):
        fb = '<a href="%s"><i></i></a>' % FB
        for body in ('<footer><h4>Følg oss</h4><ul><li>' + fb + '</li></ul></footer>',
                     '<footer><p>© 2026 Fjordheim Bygg AS</p><div class="x">' + fb + '</div></footer>',
                     '<footer><p>Org.nr 923 609 016</p>' + fb + '</footer>',
                     '<footer><div class="icons">' + fb + '</div><div>Nettside av Byra AS</div></footer>',
                     '<header><div class="top">' + fb + '</div></header>'):
            with self.subTest(body=body):
                decision = self.one(page(body))
                self.audit(decision)

    def test_name_forms_gate_cases(self):
        cases = (('Narvikgården AS', 'https://facebook.com/Narvikgaarden'), ('Bjørn Åsen Elektro AS', 'https://facebook.com/BjornAsenElektro'),
                 ('Hervik Elektro Montasje Service AS', 'https://facebook.com/hervikelektromontasje'),
                 ('Fjordheim Norge AS', 'https://www.linkedin.com/company/fjordheim-norge'),
                 ('G3 Gausdal Treindustrier SA', 'https://no.linkedin.com/company/G3-Gausdal-Treindustrier-SA/admin/feed'),
                 ('Fjordheim Bygg AS', 'https://facebook.com/fjordheim'), ('Bjørn Bygg AS', 'https://www.facebook.com/Bj%C3%B8rn-Bygg-AS'))
        for name, href in cases:
            with self.subTest(name=name):
                self.use_name(name)
                decision = self.one(footer(href))
                self.audit(decision)


class UnpublishedThingsAreRejected(SocialAuditBase):
    """Forged claims for every spec negative: the auditor re-derives and refuses."""

    def check(self, html, tag, value, canonical_url, platform, **kw):
        self.rejects(self.forged(html, tag, value, canonical_url, platform, **kw))

    def test_share_login_and_non_profile_urls(self):
        cases = [('https://www.facebook.com/sharer/sharer.php?u=x', 'facebook.com/sharer/sharer.php', 'facebook'),
                 ('https://www.facebook.com/dialog/share?href=x', 'facebook.com/dialog/share', 'facebook'),
                 ('https://www.facebook.com/login.php', 'facebook.com/login.php', 'facebook'),
                 ('https://www.facebook.com/tr?id=1', 'facebook.com/tr', 'facebook'),
                 ('https://www.facebook.com/events/123', 'facebook.com/events/123', 'facebook'),
                 ('https://www.facebook.com/groups/fjordheim', 'facebook.com/groups/fjordheim', 'facebook'),
                 ('https://www.facebook.com/profile.php?id=100012345', 'facebook.com/profile.php', 'facebook'),
                 ('https://www.facebook.com/FjordheimBygg/posts/123', 'facebook.com/fjordheimbygg/posts/123', 'facebook'),
                 ('https://www.facebook.com/FjordheimBygg/events', 'facebook.com/fjordheimbygg/events', 'facebook'),
                 ('https://www.facebook.com/v2.8/FjordheimBygg', 'facebook.com/v2.8/fjordheimbygg', 'facebook'),
                 ('https://twitter.com/intent/tweet?text=x', 'x.com/intent/tweet', 'x'),
                 ('https://twitter.com/share?url=x', 'x.com/share', 'x'),
                 ('https://x.com/home', 'x.com/home', 'x'),
                 ('https://x.com/FjordheimBygg/status/12345', 'x.com/fjordheimbygg/status/12345', 'x'),
                 ('https://www.instagram.com/p/CXabc123/', 'instagram.com/p/cxabc123', 'instagram'),
                 ('https://www.instagram.com/FjordheimBygg/p/CXabc/', 'instagram.com/fjordheimbygg/p/cxabc', 'instagram'),
                 ('https://www.youtube.com/watch?v=abc', 'youtube.com/watch', 'youtube'),
                 ('https://www.youtube.com/embed/FjordheimBygg', 'youtube.com/embed/fjordheimbygg', 'youtube'),
                 ('https://www.tiktok.com/@fjordheimbygg/video/123', 'tiktok.com/@fjordheimbygg/video/123', 'tiktok'),
                 ('https://www.linkedin.com/shareArticle?mini=true&url=x', 'linkedin.com/sharearticle', 'linkedin'),
                 ('https://www.linkedin.com/company', 'linkedin.com/company', 'linkedin')]
        for href, value, platform in cases:
            with self.subTest(href=href):
                self.check(footer(href), '<a href="%s">' % href, value, 'https://' + value, platform)

    def test_linkedin_personal_school_and_showcase(self):
        for href, value in (('https://www.linkedin.com/in/fjordheim-bygg', 'linkedin.com/in/fjordheim-bygg'),
                            ('https://www.linkedin.com/school/fjordheim-bygg', 'linkedin.com/school/fjordheim-bygg'),
                            ('https://www.linkedin.com/showcase/fjordheim-bygg', 'linkedin.com/showcase/fjordheim-bygg'),
                            ('https://www.linkedin.com/pub/fjordheim-bygg/1/2/3', 'linkedin.com/pub/fjordheim-bygg')):
            with self.subTest(href=href):
                self.check(footer(href), '<a href="%s">' % href, value, 'https://' + value, 'linkedin')

    def test_look_alike_hosts_and_subdomains(self):
        for href, value, platform in (('https://facebook.com.evil.example/FjordheimBygg', 'facebook.com.evil.example/fjordheimbygg', 'facebook'),
                                      ('https://notfacebook.com/FjordheimBygg', 'notfacebook.com/fjordheimbygg', 'facebook'),
                                      ('https://l.facebook.com/FjordheimBygg', 'facebook.com/fjordheimbygg', 'facebook'),
                                      ('https://business.facebook.com/FjordheimBygg', 'facebook.com/fjordheimbygg', 'facebook'),
                                      ('https://www.m.facebook.com/FjordheimBygg', 'facebook.com/fjordheimbygg', 'facebook'),
                                      ('https://youtu.be/FjordheimBygg', 'youtube.com/fjordheimbygg', 'youtube'),
                                      ('https://example.com/?u=https://facebook.com/FjordheimBygg', 'facebook.com/fjordheimbygg', 'facebook'),
                                      ('https://www.facebook.com:8080/FjordheimBygg', 'facebook.com/fjordheimbygg', 'facebook'),
                                      ('ftp://www.facebook.com/FjordheimBygg', 'facebook.com/fjordheimbygg', 'facebook')):
            with self.subTest(href=href):
                self.check(footer(href), '<a href="%s">' % href, value, 'https://' + value, platform)

    def test_other_entities_and_handle_without_name_tokens(self):
        for href, value in (('https://facebook.com/rivalcorp', 'facebook.com/rivalcorp'),
                            ('https://facebook.com/byggmester123', 'facebook.com/byggmester123'),
                            ('https://facebook.com/Fjordheim-Eiendom', 'facebook.com/fjordheim-eiendom'),
                            ('https://facebook.com/FjordheimGroup', 'facebook.com/fjordheimgroup'),
                            ('https://www.linkedin.com/company/1234567', 'linkedin.com/company/1234567')):
            with self.subTest(href=href):
                platform = 'linkedin' if 'linkedin' in href else 'facebook'
                self.check(footer(href), '<a href="%s">' % href, value, 'https://' + value, platform, tokens=('fjordheim',), score=0.95)

    def test_generic_only_and_parent_group_handles(self):
        self.use_name('Bygg AS')
        self.check(footer('https://facebook.com/byggmester123'), '<a href="https://facebook.com/byggmester123">', 'facebook.com/byggmester123',
                   'https://facebook.com/byggmester123', 'facebook', tokens=('bygg',))
        self.use_name('Fjordheim Norge AS')
        self.check(footer('https://www.linkedin.com/company/fjordheim'), '<a href="https://www.linkedin.com/company/fjordheim">',
                   'linkedin.com/company/fjordheim', 'https://linkedin.com/company/fjordheim', 'linkedin', tokens=('fjordheim',), score=0.95)
        self.use_name('Hervik Elektro Montasje AS')
        self.check(footer('https://facebook.com/hervikelektro'), '<a href="https://facebook.com/hervikelektro">',
                   'facebook.com/hervikelektro', 'https://facebook.com/hervikelektro', 'facebook', tokens=('hervik', 'elektro'), score=0.90)

    def test_gate_score_and_tokens_are_the_derived_ones(self):
        good = self.one(footer(FB))
        for change in ({'handle_score': 0.95}, {'handle_score': 0.90}, {'handle_tokens': ['fjordheim']}, {'handle_tokens': ['bygg', 'fjordheim']},
                       {'handle_score': 0.98, 'handle_tokens': []}):
            forged = copy.deepcopy(good)
            forged['evidence']['locator'].update(change)
            self.rejects(forged)

    def test_agency_partner_group_and_other_entity_contexts(self):
        fb = '<a href="%s"><i></i></a>' % FB
        tag = '<a href="%s">' % FB
        bodies = ['<div>Laget av <a href="https://byra.example">Byra AS</a> ' + fb + '</div>',
                  '<section><h2>Våre partnere</h2><div>' + fb + '</div></section>',
                  '<footer><h4>Følg konsernet</h4>' + fb + '</footer>',
                  '<footer><p>Naboen Bygg AS</p>' + fb + '</footer>',
                  '<footer><p>Design: Byra AS, Org.nr 999 888 777</p>' + fb + '</footer>',
                  '<footer><p>Nettside utviklet av Byra</p>' + fb + '</footer>',
                  '<div>Powered by WebHost ' + fb + '</div>',
                  '<section><h2>Our customers</h2><ul><li>' + fb + '</li></ul></section>',
                  '<section><h3>Referanser</h3><div>' + fb + '</div></section>',
                  '<div class="sponsor">Sponsor ' + fb + '</div>',
                  '<footer><p>Medlem av Bygg Norge</p>' + fb + '</footer>',
                  '<footer><h4>Datterselskap</h4>' + fb + '</footer>',
                  '<footer><h4>Follow our parent company</h4>' + fb + '</footer>',
                  '<footer><p>Foto: Ola Nordmann</p>' + fb + '</footer>',
                  '<footer><p>Org.nr 999 888 777</p>' + fb + '</footer>']
        for body in bodies:
            with self.subTest(body=body):
                self.check(page(body), tag, 'facebook.com/fjordheimbygg', 'https://facebook.com/FjordheimBygg', 'facebook')

    def test_hidden_quoted_script_and_comment_links(self):
        tag = '<a href="%s">' % FB
        bodies = ['<div style="display: none">%s</a></div>', '<div hidden>%s</a></div>', '<a aria-hidden="true" href="%s">',
                  '<div class="d-none">%s</a></div>', '<div class="Foo SR-ONLY">%s</a></div>', '<template>%s</a></template>',
                  '<noscript>%s</a></noscript>', '<blockquote>%s</a></blockquote>', '<q>%s</a></q>', '<pre>%s</a></pre>',
                  '<code>%s</code>', '<textarea>%s</textarea>', '<div hidden><p>unclosed%s</a></div>', '<p hidden>x<p>%s</a>']
        for body in bodies:
            if body.startswith('<a aria-hidden'):
                html, marker = page(body % FB), '<a aria-hidden="true" href="%s">' % FB
            else:
                html, marker = page(body % tag), tag
            with self.subTest(body=body):
                self.check(html, marker, 'facebook.com/fjordheimbygg', 'https://facebook.com/FjordheimBygg', 'facebook')

    def test_link_in_visible_text_title_img_and_link_tag_has_no_element_to_point_at(self):
        html = page('<p>Folg oss pa https://www.facebook.com/FjordheimBygg</p>'
                    '<a href="/kontakt" title="https://facebook.com/FjordheimBygg">Kontakt</a>')
        decision = self.forged(footer(FB), '<a href="%s">' % FB, 'facebook.com/fjordheimbygg', 'https://facebook.com/FjordheimBygg', 'facebook')
        other = self.one(footer(FB))
        # Move a genuine claim onto the page that only mentions the URL as text.
        sid = self.save(html)
        forged = copy.deepcopy(other)
        forged['evidence'].update(snapshot_id=sid, content_sha256=digest(html.encode()))
        self.rejects(forged)
        self.assertTrue(decision)

    def test_group_channels_on_locale_pages_and_national_subsidiary(self):
        for path in ('/nb-no/vilkar', '/en-gb/', '/en_gb/x'):
            with self.subTest(path=path):
                self.check(footer(FB), '<a href="%s">' % FB, 'facebook.com/fjordheimbygg', 'https://facebook.com/FjordheimBygg', 'facebook', path=path)
        self.use_name('Falck Norge AS')
        self.check(footer('https://www.linkedin.com/company/falck/'), '<a href="https://www.linkedin.com/company/falck/">', 'linkedin.com/company/falck',
                   'https://linkedin.com/company/falck', 'linkedin', tokens=('falck',), score=0.95)

    def test_group_channels_on_country_label_hosts(self):
        original = self.registry_host
        for host in ('no.fjordheim.example', 'nb-no.fjordheim.example'):
            self.registry_host = host
            self.use_name(self.name)
            with self.subTest(host=host):
                self.check(footer(FB), '<a href="%s">' % FB, 'facebook.com/fjordheimbygg', 'https://facebook.com/FjordheimBygg', 'facebook', host=host)
        self.registry_host = original

    def test_json_ld_other_nodes_names_and_identifiers(self):
        ref = 'https://www.facebook.com/FjordheimBygg'
        payloads = [{'@type': 'Person', 'name': 'Jan Fjordheim', 'sameAs': [ref]},
                    {'@type': ['Thing', 'Person'], 'sameAs': [ref]},
                    {'@type': 'Organization', 'founder': {'@type': 'Person', 'sameAs': [ref]}},
                    {'@type': 'Organization', 'author': {'@type': 'Organization', 'sameAs': [ref]}},
                    {'@type': 'Organization', 'parentOrganization': {'@type': 'Organization', 'sameAs': [ref]}},
                    {'@type': 'Review', 'mainEntity': {'sameAs': [ref]}},
                    {'taxID': '999888777', 'publisher': {'sameAs': [ref]}},
                    {'taxID': '999888777', 'sameAs': [ref]},
                    {'taxID': 999888777, 'sameAs': [ref]},
                    {'identifier': {'value': '999 888 777'}, 'sameAs': [ref]},
                    {'vatID': 'NO 999 888 777 MVA', 'sameAs': [ref]},
                    {'name': 'Arendal Auto AS', 'sameAs': [ref]},
                    {'name': 'Fjordheim Bygg Notodden', 'sameAs': [ref]},
                    {'name': 'Fjordheim Bygg Skien AS', 'sameAs': [ref]},
                    {'name': 5, 'sameAs': [ref]},
                    {'@graph': {'@graph': {'founder': {'sameAs': [ref]}}}}]
        good = self.one(page('', ld({'@type': 'Organization', 'sameAs': [ref]})))
        for payload in payloads:
            with self.subTest(payload=payload):
                sid = self.save(page('', ld(payload)))
                raw, _ = self.store.open(sid)
                text = raw.decode()
                literal = '"' + ref + '"'
                start = text.index(literal)
                forged = copy.deepcopy(good)
                forged['evidence'].update(snapshot_id=sid, content_sha256=digest(raw))
                forged['evidence']['locator'].update(html_start=start, html_end=start + len(literal))
                self.rejects(forged)

    def test_json_ld_locator_must_name_script_path_and_literal(self):
        ref = 'https://www.facebook.com/FjordheimBygg'
        found = self.published(page('', ld({'@graph': [{'@type': 'Organization', 'sameAs': [ref, 'https://x.com/FjordheimBygg']}]})))
        self.assertEqual(len(found), 2)
        decision = found[0]
        self.assertEqual(decision['claim']['value'], 'facebook.com/fjordheimbygg')
        self.audit(decision)
        for change in ({'script_index': 1}, {'node_path': ['@graph', 0, 'sameAs', 1]}, {'node_path': ['@graph', 0]}, {'source': 'a_href'},
                       {'raw_url': 'https://www.facebook.com/Other'}, {'html_start': decision['evidence']['locator']['html_start'] + 1},
                       {'html_end': decision['evidence']['locator']['html_end'] + 1}, {'element_end': 5}):
            with self.subTest(change=change):
                forged = copy.deepcopy(decision)
                forged['evidence']['locator'].update(change)
                self.rejects(forged)
        forged = copy.deepcopy(decision)
        forged['evidence']['claim_span'] = '"https://www.facebook.com/FjordheimBygg/"'
        self.rejects(forged)

    def test_unanchored_page_rejects_every_scope(self):
        other = self.one(footer(FB))
        sid = self.save(footer(FB), host='elsewhere.example')
        raw, _ = self.store.open(sid)
        locator = other['evidence']['locator']
        for scope in ('registry_linked_html', 'company_owned_html'):
            forged = self.assemble(sid, 'elsewhere.example', '/', 'facebook.com/fjordheimbygg', other['evidence']['claim_span'], dict(locator), scope)
            with self.subTest(scope=scope):
                self.rejects(forged)

    def test_scope_follows_the_anchor_kind(self):
        proven = page('<footer><p>© 2026 Fjordheim Bygg AS. Org.nr 923 609 016</p><a href="%s">f</a></footer>' % FB)
        decision = self.one(proven, host='brand.example')
        forged = self.retarget(decision, scope='registry_linked_html')
        self.rejects(forged)
        plain = self.one(footer(FB))
        self.rejects(self.retarget(plain, scope='company_owned_html'))

    def test_case_variant_duplicates_publish_once_and_later_occurrences_are_rejected(self):
        html = footer('https://facebook.com/FjordheimBygg', 'https://facebook.com/fjordheimbygg')
        first = self.one(html)
        self.audit(first)
        forged = self.forged(html, '<a href="https://facebook.com/fjordheimbygg">', 'facebook.com/fjordheimbygg',
                             'https://facebook.com/fjordheimbygg', 'facebook')
        self.rejects(forged)

    def test_first_occurrence_is_the_first_non_excluded_one(self):
        fb = '<a href="%s"><i></i></a>' % FB
        html = page('<div>Laget av Byra ' + fb + '</div><footer><h4>Follow us</h4>' + fb + '</footer>')
        decision = self.one(html)
        self.audit(decision)
        forged = self.forged(html, '<a href="%s">' % FB, 'facebook.com/fjordheimbygg', 'https://facebook.com/FjordheimBygg', 'facebook')
        self.rejects(forged)

    def test_wrong_and_uncanonical_values_and_other_platform(self):
        good = self.one(footer(FB + '/'))
        for value in ('facebook.com/FjordheimBygg', 'https://facebook.com/fjordheimbygg', 'www.facebook.com/fjordheimbygg', 'facebook.com/fjordheimbygg/',
                      'x.com/fjordheimbygg', 'facebook.com/fjordheim', 'facebook.com/fjordheimbygg?x=1', 'facebook.com/other', None,
                      {'url': 'facebook.com/fjordheimbygg'}):
            with self.subTest(value=value):
                forged = self.retarget(good, value=value, item_key=value)
                self.rejects(forged)
        self.rejects(self.retarget(good, item_key='facebook.com/other'))
        stale = copy.deepcopy(good)
        stale['claim']['claim_id'] = '0' * 64
        self.rejects(stale)

    def test_locator_span_and_support_tampering(self):
        good = self.one(footer(FB + '/'))
        locator = good['evidence']['locator']
        changes = [{'html_start': locator['html_start'] + 1}, {'html_end': locator['html_end'] - 1}, {'html_start': 'x'}, {'element_end': locator['element_end'] + 1},
                   {'raw_url': FB}, {'platform': 'x'}, {'platform': 'instagram'}, {'canonical_url': 'https://facebook.com/fjordheimbygg'},
                   {'canonical_url': 'https://www.facebook.com/FjordheimBygg'}, {'source': 'data_href'}, {'source': 'iframe_src'},
                   {'handle_score': 0.99}, {'handle_score': '0.98'}]
        for change in changes:
            with self.subTest(change=change):
                forged = copy.deepcopy(good)
                forged['evidence']['locator'].update(change)
                self.rejects(forged)
        for key in ('platform', 'raw_url', 'html_start', 'element_end', 'canonical_url', 'handle_score', 'handle_tokens', 'source'):
            forged = copy.deepcopy(good)
            del forged['evidence']['locator'][key]
            self.rejects(forged)
        forged = copy.deepcopy(good)
        forged['evidence']['locator']['script_index'] = 0
        self.rejects(forged)
        for span in ('<a href="%s">' % FB, good['evidence']['claim_span'] + ' ', FB, ''):
            forged = copy.deepcopy(good)
            forged['evidence']['claim_span'] = span
            self.rejects(forged)
        for support in ({'x': 'y'}, None, {'section_context': '<div></div>'}, []):
            forged = copy.deepcopy(good)
            forged['evidence']['support_spans'] = support
            self.rejects(forged)
        forged = copy.deepcopy(good)
        del forged['evidence']['support_spans']
        self.rejects(forged)

    def test_claim_envelope_tampering(self):
        good = self.one(footer(FB))
        for change in ({'scope': 'company_owned_structured'}, {'family': 'business_products'}, {'period': '2025'}, {'field': 'verified_website'},
                       {'item_key': None}):
            with self.subTest(change=change):
                self.rejects(copy.deepcopy(good) | {'claim': dict(good['claim'], **change)})
        forged = copy.deepcopy(good)
        forged['claim']['value'] = 'facebook.com/other'
        self.rejects(forged)

    def test_method_routing_is_exclusive(self):
        good = self.one(footer(FB))
        for method in ('registry_linked_subject_html_v1', 'explicit_subject_html_v1', 'registry_linked_business_statement_v1',
                       'footer_bound_organization_jsonld_v1', 'scoped_catalogue_html_v2', 'exact_identifier_jsonld_v1', 'social_profile_link_v2'):
            with self.subTest(method=method):
                forged = copy.deepcopy(good)
                forged['evidence']['extraction_method'] = method
                self.rejects(forged)
        other_field = self.retarget(good, field='verified_website')
        self.rejects(other_field)
        for field in ('product_service', 'business_description', 'public_activity'):
            self.rejects(self.retarget(good, field=field))

    def test_evidence_origin_and_hash_come_from_the_receipt(self):
        good = self.one(footer(FB))
        forged = copy.deepcopy(good)
        forged['evidence']['source_url'] = 'https://elsewhere.example/'
        self.rejects(forged)
        forged = copy.deepcopy(good)
        forged['evidence']['content_sha256'] = '0' * 64
        self.rejects(forged)

    def test_non_utf8_page_is_rejected(self):
        good = self.one(footer(FB))
        raw = b'\xff\xfe' + footer(FB).encode()
        sid = self.store.save(raw, dict(organisation_number=SUBJECT, source_class='company_owned',
            source_url='https://%s/' % self.registry_host, effective_url='https://%s/' % self.registry_host, http_status=200,
            sha256=digest(raw), declared_host=self.registry_host, source_origin=self.registry_host, robots_checked=True,
            retrieved_at='2026-10-10T08:00:00Z', ownership_anchor_snapshot_id=self.anchor))
        forged = copy.deepcopy(good)
        forged['evidence'].update(snapshot_id=sid, content_sha256=digest(raw))
        with self.assertRaises(ValueError):
            self.audit(forged)


if __name__ == '__main__':
    unittest.main()
