"""Company-owned social profile links: canonical form, reject lists, handle gate and entity context."""
import json
import tempfile
import unittest
from pathlib import Path

from shirushi.claims import claim_id
from shirushi.snapshots import SnapshotStore, digest
from shirushi.social_sources import FIELD, canonical_profile, social_links, social_values
from shirushi.web_sources import check_web

SUBJECT, NAME = '923609016', 'Fjordheim Bygg AS'
URL = 'https://www.fjordheim.example/'


def page(body, head=''):
    return ('<!doctype html><html><head><title>Fjordheim</title>' + head + '</head><body>' + body + '</body></html>').encode()


def urls(raw, name=NAME, url=URL, **kw):
    return [l['canonical_url'] for _, _, _, l, _ in social_values(raw, SUBJECT, name, url, **kw)]


def values(raw, name=NAME, url=URL, **kw):
    return [v for _, v, _, _, _ in social_values(raw, SUBJECT, name, url, **kw)]


def links(*hrefs):
    return page('<footer><div class="social">' + ''.join('<a href="%s">x</a>' % h for h in hrefs) + '</div></footer>')


class Canonicalisation(unittest.TestCase):
    def test_canonical_form_table(self):
        cases = {
            'https://www.facebook.com/FjordheimBygg/': 'https://facebook.com/FjordheimBygg',
            'http://facebook.com/FjordheimBygg?ref=page_internal&utm_source=x#top': 'https://facebook.com/FjordheimBygg',
            'https://m.facebook.com/FjordheimBygg': 'https://facebook.com/FjordheimBygg',
            'https://nb-no.facebook.com/FjordheimBygg/about': 'https://facebook.com/FjordheimBygg',
            '//www.facebook.com/FjordheimBygg': 'https://facebook.com/FjordheimBygg',
            'https://www.facebook.com/people/Fjordheim-Bygg-AS/100063812345678/': 'https://facebook.com/people/Fjordheim-Bygg-AS/100063812345678',
            'https://www.facebook.com/pages/Fjordheim-Bygg/123456789': 'https://facebook.com/pages/Fjordheim-Bygg/123456789',
            'https://www.linkedin.com/company/fjordheim-bygg-as/': 'https://linkedin.com/company/fjordheim-bygg-as',
            'https://no.linkedin.com/company/Fjordheim-Bygg-AS/admin/feed?trk=x': 'https://linkedin.com/company/Fjordheim-Bygg-AS',
            'https://www.instagram.com/Fjordheim.Bygg/': 'https://instagram.com/Fjordheim.Bygg',
            'https://instagram.com/fjordheimbygg/reels/': 'https://instagram.com/fjordheimbygg',
            'https://twitter.com/FjordheimBygg': 'https://x.com/FjordheimBygg',
            'https://www.x.com/FjordheimBygg/': 'https://x.com/FjordheimBygg',
            'https://www.youtube.com/channel/UC1234abcd/featured': 'https://youtube.com/channel/UC1234abcd',
            'https://www.youtube.com/@FjordheimBygg': 'https://youtube.com/@FjordheimBygg',
            'https://www.youtube.com/user/FjordheimBygg/videos': 'https://youtube.com/user/FjordheimBygg',
            'https://www.youtube.com/c/FjordheimBygg': 'https://youtube.com/c/FjordheimBygg',
            'https://www.tiktok.com/@fjordheimbygg': 'https://tiktok.com/@fjordheimbygg',
            'HTTPS://WWW.FACEBOOK.COM/FjordheimBygg/': 'https://facebook.com/FjordheimBygg',
        }
        for link, expected in cases.items():
            with self.subTest(link=link):
                found = canonical_profile(link)
                self.assertEqual(found and found['url'], expected)
                self.assertEqual(found['handle_key'], expected.split('://')[1].lower())

    def test_platform_and_percent_encoded_handle(self):
        self.assertEqual(canonical_profile('https://twitter.com/Fjord')['platform'], 'x')
        found = canonical_profile('https://www.facebook.com/Bj%C3%B8rn-Bygg-AS')
        self.assertEqual(found['url'], 'https://facebook.com/Bjørn-Bygg-AS')

    def test_reject_lists(self):
        rejected = [
            'https://www.facebook.com/sharer/sharer.php?u=https%3A%2F%2Ffjordheim.example',
            'https://www.facebook.com/sharer.php?u=x', 'https://www.facebook.com/share.php?u=x',
            'https://www.facebook.com/share/p/abc', 'https://www.facebook.com/dialog/share?href=x',
            'https://www.facebook.com/login.php', 'https://www.facebook.com/login/?next=x',
            'https://www.facebook.com/plugins/like.php?href=x', 'https://www.facebook.com/policy.php',
            'https://www.facebook.com/privacy/policy', 'https://www.facebook.com/profile.php?id=100012345',
            'https://www.facebook.com/events/123', 'https://www.facebook.com/groups/fjordheim',
            'https://www.facebook.com/tr?id=1&ev=PageView', 'https://www.facebook.com/',
            'https://www.facebook.com/hashtag/bygg', 'https://www.facebook.com/people/', 'https://www.facebook.com/pages/category/Construction/',
            'https://www.facebook.com/FjordheimBygg/posts/123456', 'https://l.facebook.com/l.php?u=https%3A%2F%2Fa.example',
            'https://business.facebook.com/FjordheimBygg', 'https://developers.facebook.com/docs',
            'https://www.linkedin.com/in/jan-hansen/', 'https://www.linkedin.com/company/', 'https://www.linkedin.com/company',
            'https://www.linkedin.com/shareArticle?mini=true&url=x', 'https://www.linkedin.com/sharing/share-offsite/?url=x',
            'https://www.linkedin.com/showcase/fjordheim-lab/', 'https://www.linkedin.com/school/fjordheim-skole/', 'https://www.linkedin.com/pub/jan/1/2/3',
            'https://www.linkedin.com/feed/', 'https://www.linkedin.com/jobs/view/1',
            'https://twitter.com/intent/tweet?text=x', 'https://twitter.com/share?url=x', 'https://x.com/home',
            'https://x.com/search?q=x', 'https://x.com/i/flow/login', 'https://x.com/FjordheimBygg/status/12345',
            'https://x.com/a/b', 'https://twitter.com/', 'https://platform.twitter.com/widgets.js',
            'https://www.instagram.com/p/CXabc123/', 'https://www.instagram.com/reel/CXabc/', 'https://www.instagram.com/stories/x/1',
            'https://www.instagram.com/explore/tags/bygg/', 'https://www.instagram.com/accounts/login/', 'https://www.instagram.com/',
            'https://www.instagram.com/fjordheim/p/CXabc/',
            'https://www.youtube.com/watch?v=abc', 'https://www.youtube.com/embed/abc', 'https://www.youtube.com/playlist?list=1',
            'https://www.youtube.com/shorts/abc', 'https://www.youtube.com/results?search_query=x', 'https://youtu.be/abc',
            'https://www.youtube-nocookie.com/embed/abc', 'https://www.youtube.com/',
            'https://www.tiktok.com/music/x-123', 'https://www.tiktok.com/@fjordheim/video/123', 'https://www.tiktok.com/',
            'mailto:post@fjordheim.example', 'javascript:void(0)', 'ftp://facebook.com/Fjord', '#facebook', '',
            'https://fjordheim.example/facebook.com/Fjord', 'https://notfacebook.com/Fjord',
            'https://facebook.com.evil.example/Fjord', 'https://example.com/?u=https://facebook.com/Fjord',
        ]
        for link in rejected:
            with self.subTest(link=link):
                self.assertIsNone(canonical_profile(link))

    def test_hostile_urls_never_raise(self):
        for link in ('https://[::1/x', 'https://facebook.com:99999/x', 'http://facebook.com:abc/x', 'https://facebook.com/%zz',
                     'https://facebook.com/' + 'a' * 5000, 'https://facebook.com/\x00x', 'https://facebook.com/a b', None):
            with self.subTest(link=link):
                canonical_profile(link)


class ScalarValue(unittest.TestCase):
    def test_value_is_the_lower_case_host_and_path_without_scheme_www_slash_or_query(self):
        cases = {'https://www.facebook.com/MtmSkogservice/?ref=x#y': 'facebook.com/mtmskogservice',
                 'http://m.facebook.com/MtmSkogservice': 'facebook.com/mtmskogservice',
                 'https://no.linkedin.com/company/G3-Gausdal-Treindustrier-SA/admin/feed': 'linkedin.com/company/g3-gausdal-treindustrier-sa',
                 'https://twitter.com/MTMSkogservice': 'x.com/mtmskogservice',
                 'https://www.youtube.com/@MtmSkogservice': 'youtube.com/@mtmskogservice'}
        for link, expected in cases.items():
            with self.subTest(link=link):
                name = 'G3 Gausdal Treindustrier SA' if 'g3' in link.lower() else 'MTM Skogservice AS'
                self.assertEqual(values(links(link), name=name), [expected])

    def test_case_variants_are_one_value_across_pages_and_within_a_page(self):
        first = values(links('https://facebook.com/FjordheimBygg'))
        second = values(links('https://www.facebook.com/fjordheimbygg/'))
        self.assertEqual(first, second)
        self.assertEqual(values(links('https://facebook.com/FjordheimBygg', 'https://facebook.com/fjordheimbygg')), first)

    def test_platform_and_the_case_preserved_url_stay_in_the_locator(self):
        found = list(social_values(links('https://twitter.com/FjordheimBygg'), SUBJECT, NAME, URL))
        self.assertEqual(found[0][3]['platform'], 'x')
        self.assertEqual(found[0][3]['canonical_url'], 'https://x.com/FjordheimBygg')


class GroupChannels(unittest.TestCase):
    FB = 'https://www.facebook.com/FjordheimBygg'

    def test_multi_country_group_site_pages_do_not_publish_their_channels(self):
        for url in ('https://www.fjordheim.com/nb-no/vilkar', 'https://www.fjordheim.com/en-gb/', 'https://no.fjordheim.com/', 'https://nb-no.fjordheim.com/'):
            with self.subTest(url=url):
                self.assertEqual(urls(links(self.FB), url=url), [])
        self.assertEqual(len(social_links(links(self.FB), NAME, 'https://www.fjordheim.com/nb-no/vilkar')), 1)

    def test_norwegian_hosts_and_single_language_sites_still_publish(self):
        for url in ('https://www.fjordheim.no/nb-no/vilkar', 'https://www.fjordheim.com/', 'https://www.fjordheim.com/kontakt', 'https://fjordheim.no/en/'):
            with self.subTest(url=url):
                self.assertEqual(urls(links(self.FB), url=url), ['https://facebook.com/FjordheimBygg'])

    def test_market_specific_channels_on_a_global_site_publish(self):
        url = 'https://www.fjordheim.com/nb-no/'
        for link in ('https://facebook.com/FjordheimBygg.no', 'https://facebook.com/FjordheimBygg-Norge', 'https://facebook.com/FjordheimByggNorway'):
            with self.subTest(link=link):
                self.assertEqual(len(urls(links(link), url=url)), 1)

    def test_national_subsidiary_does_not_take_the_global_handle(self):
        self.assertEqual(urls(links('https://www.linkedin.com/company/falck/'), name='Falck Norge AS', url='https://www.falck.com/careers/'), [])

    def test_json_ld_owner_node_must_carry_the_company_name_when_it_has_one(self):
        def ld(name):
            node = {'@type': 'AutoDealer', 'sameAs': ['https://www.facebook.com/FjordheimBygg']}
            if name:
                node['name'] = name
            return page('', '<script type="application/ld+json">' + json.dumps([node]) + '</script>')
        self.assertEqual(len(urls(ld('Fjordheim Bygg AS'))), 1)
        self.assertEqual(len(urls(ld('FJORDHEIM BYGG'))), 1)
        self.assertEqual(len(urls(ld(None))), 1)
        for other in ('Fjordheim Bygg Notodden', 'Arendal Auto AS', 'Fjordheim Bygg Skien AS'):
            with self.subTest(name=other):
                self.assertEqual(urls(ld(other)), [])


class Sources(unittest.TestCase):
    def test_footer_icons_json_ld_plugin_and_data_href_are_extracted(self):
        raw = page(
            '<footer><ul class="some">'
            '<li><a class="ico" href="https://www.facebook.com/FjordheimBygg/" target="_blank"><svg viewBox="0 0 1 1"></svg></a></li>'
            '<li><a href="https://www.linkedin.com/company/fjordheim-bygg-as/">LinkedIn</a></li>'
            '</ul></footer>'
            '<iframe src="https://www.facebook.com/plugins/page.php?href=https%3A%2F%2Fwww.facebook.com%2FFjordheimBygg%2F&tabs=timeline"></iframe>'
            '<div class="fb-page" data-href="https://www.instagram.com/fjordheimbygg/"></div>'
            '<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Organization","name":"Fjordheim Bygg AS",'
            '"sameAs":["https://www.youtube.com/@FjordheimBygg","https://x.com/FjordheimBygg"]}]}</script>')
        found = list(social_values(raw, SUBJECT, NAME, URL))
        self.assertEqual([v for _, v, _, _, _ in found], [
            'facebook.com/fjordheimbygg', 'instagram.com/fjordheimbygg', 'linkedin.com/company/fjordheim-bygg-as',
            'x.com/fjordheimbygg', 'youtube.com/@fjordheimbygg'])
        self.assertEqual({f for f, *_ in found}, {FIELD})
        self.assertEqual([l['platform'] for *_, l, _ in found], ['facebook', 'instagram', 'linkedin', 'x', 'youtube'])
        self.assertEqual(found[0][3]['canonical_url'], 'https://facebook.com/FjordheimBygg')

    def test_evidence_span_and_locator_point_at_the_retained_bytes(self):
        raw = page('<footer><a class="fb" href="https://www.facebook.com/FjordheimBygg/"><i></i></a>'
                   '<a href="https://www.linkedin.com/company/fjordheim-bygg-as/">in</a></footer>'
                   '<div class="fb-page" data-href="https://www.instagram.com/fjordheimbygg/"></div>'
                   '<iframe src="https://www.facebook.com/plugins/page.php?href=https%3A%2F%2Ffacebook.com%2FFjordheimBygg"></iframe>'
                   '<script type="application/ld+json">{"sameAs":["https:\\/\\/x.com\\/FjordheimBygg"]}</script>')
        source = raw.decode('utf-8')
        for _, value, span, locator, support in social_values(raw, SUBJECT, NAME, URL):
            with self.subTest(url=value):
                self.assertEqual(source[locator['html_start']:locator['html_end']], span)
                self.assertIn(locator['source'], {'a_href', 'data_href', 'iframe_src', 'json_ld_same_as'})
                if locator['source'] != 'json_ld_same_as':
                    self.assertIn(locator['raw_url'], span)
                self.assertTrue(0.9 <= locator['handle_score'] <= 0.98)
                self.assertEqual(support, {})
        by_url = {l['canonical_url']: (s, l) for _, v, s, l, _ in social_values(raw, SUBJECT, NAME, URL)}
        self.assertTrue(by_url['https://facebook.com/FjordheimBygg'][0].startswith('<a class="fb"'))
        self.assertEqual(by_url['https://x.com/FjordheimBygg'][1]['source'], 'json_ld_same_as')
        self.assertEqual(by_url['https://x.com/FjordheimBygg'][1]['script_index'], 0)
        self.assertEqual(json.loads(by_url['https://x.com/FjordheimBygg'][0]), 'https://x.com/FjordheimBygg')

    def test_relative_and_protocol_relative_hrefs_resolve_against_the_page(self):
        self.assertEqual(urls(links('//www.facebook.com/FjordheimBygg', '/redirect/fjordheim')), ['https://facebook.com/FjordheimBygg'])

    def test_text_that_is_not_a_link_is_not_extracted(self):
        raw = page('<p>Folg oss pa https://www.facebook.com/FjordheimBygg og facebook.com/FjordheimBygg</p>'
                   '<a href="/kontakt" title="https://facebook.com/FjordheimBygg">Kontakt</a>'
                   '<img src="https://www.facebook.com/tr?id=1"><link rel="me" href="https://facebook.com/FjordheimBygg">')
        self.assertEqual(urls(raw), [])

    def test_hidden_quoted_script_and_commented_content_is_ignored(self):
        fb = 'https://www.facebook.com/FjordheimBygg'
        bodies = [
            '<div style="display: none"><a href="%s">x</a></div>' % fb,
            '<div hidden><a href="%s">x</a></div>' % fb,
            '<a aria-hidden="true" href="%s">x</a>' % fb,
            '<div class="d-none"><a href="%s">x</a></div>' % fb,
            '<template><a href="%s">x</a></template>' % fb,
            '<noscript><a href="%s">x</a></noscript>' % fb,
            '<blockquote><a href="%s">x</a></blockquote>' % fb,
            '<q><a href="%s">x</a></q>' % fb,
            '<pre><a href="%s">x</a></pre>' % fb,
            '<!-- <a href="%s">x</a> -->' % fb,
            '<script>var s = \'<a href="%s">x</a>\';</script>' % fb,
            '<script type="text/template"><a href="%s">x</a></script>' % fb,
            '<!-- <script type="application/ld+json">{"sameAs":["%s"]}</script> -->' % fb,
            '<script type="application/json">{"sameAs":["%s"]}</script>' % fb,
            '<textarea><a href="%s">x</a></textarea>' % fb,
            '<div hidden><p>unclosed<a href="%s">x</a></div>' % fb,
        ]
        for body in bodies:
            with self.subTest(body=body):
                self.assertEqual(urls(page(body)), [])
        self.assertEqual(urls(page('<div hidden><span>x</div><a href="%s">x</a>' % fb)), ['https://facebook.com/FjordheimBygg'])

    def test_json_ld_same_as_is_read_at_any_depth_from_organisation_nodes_only(self):
        good = {'@context': 'https://schema.org', '@type': 'Organization', 'name': NAME,
                'sameAs': 'https://www.linkedin.com/company/fjordheim-bygg-as'}
        nested = {'@type': 'WebPage', 'publisher': {'@type': 'Organization', 'sameAs': ['https://www.facebook.com/FjordheimBygg']}}
        for payload, expected in ((good, ['https://linkedin.com/company/fjordheim-bygg-as']),
                                  ([good], ['https://linkedin.com/company/fjordheim-bygg-as']),
                                  ({'@graph': [{'@type': 'WebSite'}, good]}, ['https://linkedin.com/company/fjordheim-bygg-as']),
                                  (nested, ['https://facebook.com/FjordheimBygg'])):
            raw = page('', '<script type="application/ld+json">' + json.dumps(payload) + '</script>')
            self.assertEqual(urls(raw), expected)
        other = [
            {'@type': 'Person', 'name': 'Jan Fjordheim', 'sameAs': ['https://www.facebook.com/FjordheimBygg']},
            {'@type': 'Organization', 'founder': {'@type': 'Person', 'sameAs': ['https://www.facebook.com/FjordheimBygg']}},
            {'@type': 'Organization', 'author': {'@type': 'Organization', 'sameAs': ['https://www.facebook.com/FjordheimBygg']}},
            {'@type': 'Organization', 'parentOrganization': {'@type': 'Organization', 'sameAs': ['https://www.facebook.com/FjordheimBygg']}},
            {'@type': 'Organization', 'member': [{'@type': 'Organization', 'sameAs': ['https://www.facebook.com/FjordheimBygg']}]},
            {'@type': 'Review', 'author': {'@type': 'Person'}, 'itemReviewed': {'sameAs': ['https://www.facebook.com/FjordheimBygg']}},
            {'@type': 'Organization', 'taxID': '999888777', 'identifier': '999888777', 'sameAs': ['https://www.facebook.com/FjordheimBygg']},
        ]
        for payload in other:
            with self.subTest(payload=payload):
                raw = page('', '<script type="application/ld+json">' + json.dumps(payload) + '</script>')
                self.assertEqual(urls(raw), [])

    def test_malformed_json_ld_and_non_string_same_as_are_skipped(self):
        for text in ('{"sameAs": ["https://www.facebook.com/FjordheimBygg"', '{"sameAs": 5}', '{"sameAs": [null, {"a": 1}, 7]}', '[]', 'null'):
            self.assertEqual(urls(page('', '<script type="application/ld+json">' + text + '</script>')), [])


class HandleGate(unittest.TestCase):
    def gate(self, name, link, **kw):
        found = social_links(links(link), name, URL, **kw)
        self.assertEqual(len(found), 1, link)
        return found[0]['gate']

    def test_handle_must_contain_the_legal_name_tokens(self):
        cases = [
            ('Fjordheim Bygg AS', 'https://facebook.com/FjordheimBygg', 0.98),
            ('Fjordheim Bygg AS', 'https://www.linkedin.com/company/fjordheim-bygg-as', 0.98),
            ('Fjordheim Bygg AS', 'https://instagram.com/fjordheim.bygg', 0.98),
            ('G3 Gausdal Treindustrier SA', 'https://linkedin.com/company/g3-gausdal-treindustrier-sa/admin/feed', 0.98),
            ('MTM Skogservice AS', 'https://www.facebook.com/MtmSkogservice/', 0.98),
            ('Bjørn Åsen Elektro AS', 'https://facebook.com/BjornAsenElektro', 0.98),
            ('Fjordheim Bygg AS', 'https://facebook.com/fjordheim', 0.95),
            ('Fjordheim Bygg AS', 'https://facebook.com/Fjordheim-Eiendom', None),
            ('Fjordheim Norge AS', 'https://www.linkedin.com/company/fjordheim', None),
            ('Fjordheim Norge AS', 'https://www.linkedin.com/company/fjordheim-norge', 0.98),
            ('Narvikgården AS', 'https://facebook.com/Narvikgaarden', 0.98),
            ('Hervik Elektro Montasje Service AS', 'https://facebook.com/hervikelektromontasje', 0.90),
            ('Hervik Elektro Montasje AS', 'https://facebook.com/hervikelektro', None),
            ('Hervik Elektro Montasje AS', 'https://facebook.com/hervik', None),
            ('Hervik Elektro Montasje AS', 'https://facebook.com/otherbrand', None),
            ('Fjordheim Bygg AS', 'https://facebook.com/otherbrand', None),
            ('Fjordheim Bygg AS', 'https://facebook.com/byggmester123', None),
            ('Bygg AS', 'https://facebook.com/byggmester123', None),
            ('Norge Service AS', 'https://facebook.com/norgeservicepartner', None),
            ('Fjordheim AS', 'https://www.linkedin.com/company/1234567', None),
            ('Fjordheim AS', 'https://www.youtube.com/channel/UCfjord1234', None),
            ('Fjordheim AS', 'https://www.youtube.com/@FjordheimAS', 0.98),
        ]
        for name, link, score in cases:
            with self.subTest(name=name, link=link):
                gate = self.gate(name, link)
                self.assertEqual(gate['publishable'], score is not None)
                if score is not None:
                    self.assertEqual(gate['score'], score)
                    self.assertTrue(gate['matched'])

    def test_generic_only_match_and_group_markers_fail(self):
        # A single generic trade word is never evidence; a parent-group handle is another entity.
        for name, link in (('Bygg AS', 'https://facebook.com/bygg-og-anlegg-norge'), ('Service Norge AS', 'https://facebook.com/servicenorge-partner'),
                           ('Fjordheim AS', 'https://facebook.com/FjordheimGroup'), ('Fjordheim AS', 'https://facebook.com/fjordheim-gruppen'),
                           ('Fjordheim AS', 'https://www.linkedin.com/company/fjordheim-holding-as')):
            with self.subTest(name=name, link=link):
                self.assertFalse(self.gate(name, link)['publishable'])
        self.assertTrue(self.gate('Fjordheim Group AS', 'https://facebook.com/FjordheimGroup')['publishable'])

    def test_trade_names_extend_the_gate_only_through_the_names_argument(self):
        raw = links('https://facebook.com/FjellVekst')
        self.assertEqual(urls(raw, name='Nordic Engineering Partners AS'), [])
        self.assertEqual(urls(raw, name='Nordic Engineering Partners AS', names=('Fjell Vekst',)), ['https://facebook.com/FjellVekst'])

    def test_unpublishable_candidates_stay_visible_for_diagnostics_but_are_not_values(self):
        raw = links('https://facebook.com/otherbrand', 'https://facebook.com/FjordheimBygg')
        self.assertEqual([c['url'] for c in social_links(raw, NAME, URL)], ['https://facebook.com/FjordheimBygg', 'https://facebook.com/otherbrand'])
        self.assertEqual(urls(raw), ['https://facebook.com/FjordheimBygg'])

    def test_empty_or_unusable_names_publish_nothing(self):
        for name in ('', '   ', 'AS', 'A/S', None):
            with self.subTest(name=name):
                self.assertEqual(urls(links('https://facebook.com/as', 'https://facebook.com/FjordheimBygg'), name=name), [])


class EntityContext(unittest.TestCase):
    FB = '<a href="https://www.facebook.com/FjordheimBygg"><i></i></a>'

    def test_follow_us_footer_blocks_are_accepted(self):
        for body in ('<footer><h4>Følg oss</h4><ul><li>' + self.FB + '</li></ul></footer>',
                     '<footer><div>Follow us</div><div>' + self.FB + '</div></footer>',
                     '<footer><p>© 2026 Fjordheim Bygg AS</p><div class="some">' + self.FB + '</div></footer>',
                     '<header><div class="top">' + self.FB + '</div></header>',
                     '<footer><p>Org.nr 923 609 016</p>' + self.FB + '</footer>'):
            with self.subTest(body=body):
                self.assertEqual(urls(page(body)), ['https://facebook.com/FjordheimBygg'])

    def test_agency_credit_partner_customer_and_group_blocks_are_rejected(self):
        for body in ('<div class="credit">Laget av <a href="https://byra.example">Byra AS</a> ' + self.FB + '</div>',
                     '<footer><p>Nettside utviklet av Byra</p>' + self.FB + '</footer>'.replace('</footer>', '') + '</footer>',
                     '<div>Powered by WebHost ' + self.FB + '</div>',
                     '<section><h2>Våre partnere</h2><div class="logos">' + self.FB + '</div></section>',
                     '<section><h2>Our customers</h2><ul><li>' + self.FB + '</li></ul></section>',
                     '<section><h3>Referanser</h3><div>' + self.FB + '</div></section>',
                     '<div class="sponsor">Sponsor ' + self.FB + '</div>',
                     '<footer><h4>Følg konsernet</h4>' + self.FB + '</footer>',
                     '<footer><h4>Follow our parent company</h4>' + self.FB + '</footer>',
                     '<footer><h4>Følg Fjordheim Gruppen</h4>' + self.FB + '</footer>',
                     '<footer><p>Medlem av Bygg Norge</p>' + self.FB + '</footer>',
                     '<footer><h4>Datterselskap</h4>' + self.FB + '</footer>',
                     '<footer><p>Naboen Bygg AS</p>' + self.FB + '</footer>',
                     '<footer><p>Design: Byra AS, Org.nr 999 888 777</p>' + self.FB + '</footer>'):
            with self.subTest(body=body):
                self.assertEqual(urls(page(body)), [])

    def test_credit_elsewhere_in_the_same_footer_does_not_poison_the_company_icons(self):
        body = ('<footer><div class="copy">© 2026 Fjordheim Bygg AS</div><div class="social">' + self.FB + '</div>'
                '<div class="credit">Nettside av Byra AS</div></footer>')
        self.assertEqual(urls(page(body)), ['https://facebook.com/FjordheimBygg'])

    def test_a_clean_occurrence_wins_over_a_rejected_one_and_duplicates_collapse(self):
        body = ('<div>Laget av Byra ' + self.FB + '</div><footer><h4>Follow us</h4>' + self.FB + '</footer>'
                '<a href="https://facebook.com/fjordheimbygg/">b</a><a href="http://www.facebook.com/FjordheimBygg?x=1">c</a>')
        found = list(social_values(page(body), SUBJECT, NAME, URL))
        self.assertEqual([v for _, v, _, _, _ in found], ['facebook.com/fjordheimbygg'])
        self.assertTrue(page(body).decode()[found[0][3]['html_start']:].startswith('<a href="https://www.facebook.com/FjordheimBygg"'))
        self.assertGreater(found[0][3]['html_start'], page(body).decode().index('Follow us'))


class Determinism(unittest.TestCase):
    def test_output_is_sorted_stable_and_independent_of_link_order(self):
        hrefs = ['https://www.youtube.com/@FjordheimBygg', 'https://www.linkedin.com/company/fjordheim-bygg-as', 'https://x.com/FjordheimBygg',
                 'https://www.facebook.com/FjordheimBygg', 'https://www.instagram.com/fjordheimbygg']
        expected = urls(links(*hrefs))
        self.assertEqual(expected, sorted(expected, key=lambda u: (canonical_profile(u)['platform'], u)))
        self.assertEqual(len(expected), 5)
        for order in (hrefs[::-1], hrefs[2:] + hrefs[:2]):
            self.assertEqual(urls(links(*order)), expected)
        self.assertEqual(urls(links(*hrefs)), expected)

    def test_non_utf8_or_huge_input_fails_closed(self):
        self.assertEqual(list(social_values(b'', SUBJECT, NAME, URL)), [])
        with self.assertRaises(UnicodeDecodeError):
            list(social_values(b'\xff\xfe', SUBJECT, NAME, URL))


def shim(raw, receipt_url, anchored, scope='registry_linked_html', method='social_profile_link_v1'):
    """Local copy of the check_web wiring in package-C-wiring.md: runs only for an anchored page."""
    decisions = []
    if not anchored:
        return decisions
    sid = 'snap-1'
    for field, value, span, locator, support in social_values(raw, SUBJECT, NAME, receipt_url):
        cid = claim_id(SUBJECT, field, scope, value)
        eid = sid + ':' + cid
        claim = {'claim_id': cid, 'field': field, 'value': value, 'scope': scope, 'family': 'website_owned_profiles',
                 'item_key': value, 'period': None, 'availability': 'available', 'evidence_ids': [eid], 'freshness': 'live_source'}
        evidence = {'id': eid, 'snapshot_id': sid, 'source_url': receipt_url, 'source_class': 'company_owned', 'source_origin': 'x',
                    'retrieved_at': '2026-10-10T08:00:00Z', 'content_sha256': digest(raw), 'claim_span': span,
                    'locator': locator, 'support_spans': support, 'extraction_method': method}
        decisions.append({'field': field, 'family': 'website_owned_profiles', 'accepted': True, 'claim': claim, 'evidence': evidence})
    return decisions


class Wiring(unittest.TestCase):
    RAW = links('https://www.facebook.com/FjordheimBygg/', 'https://www.linkedin.com/company/fjordheim-bygg-as/')

    def test_one_claim_per_profile_url_keyed_by_the_canonical_url(self):
        decisions = shim(self.RAW, URL, True)
        self.assertEqual([d['claim']['item_key'] for d in decisions],
                         ['facebook.com/fjordheimbygg', 'linkedin.com/company/fjordheim-bygg-as'])
        self.assertEqual([d['claim']['value'] for d in decisions], [d['claim']['item_key'] for d in decisions])
        self.assertEqual(len({d['claim']['claim_id'] for d in decisions}), 2)
        self.assertEqual(decisions, shim(self.RAW, URL, True))
        for d in decisions:
            self.assertIn(d['evidence']['claim_span'], self.RAW.decode())
            self.assertEqual(d['claim']['family'], 'website_owned_profiles')

    def test_claim_identity_is_the_same_on_every_page_that_shows_the_link(self):
        other = shim(page('<footer><h4>Kontakt</h4><a href="https://facebook.com/FjordheimBygg">fb</a></footer>'), URL + 'kontakt', True)
        self.assertEqual(other[0]['claim']['claim_id'], shim(self.RAW, URL, True)[0]['claim']['claim_id'])

    def test_unanchored_pages_yield_nothing(self):
        self.assertEqual(shim(self.RAW, 'https://other.example/', False), [])

    def test_check_web_refuses_pages_not_anchored_to_the_company(self):
        # check_web raises before any extraction when the page is neither registry-hosted nor proven: the wiring inherits that gate.
        with tempfile.TemporaryDirectory() as temp:
            store = SnapshotStore(Path(temp))
            registry = json.dumps({'organisasjonsnummer': SUBJECT, 'navn': NAME, 'hjemmeside': 'fjordheim.example'}).encode()
            anchor = store.save(registry, dict(organisation_number=SUBJECT, source_class='brreg_entity',
                source_url='https://data.brreg.no/enhetsregisteret/api/enheter/' + SUBJECT, http_status=200,
                sha256=digest(registry), retrieved_at='2026-10-10T08:00:00Z'))
            sid = store.save(self.RAW, dict(organisation_number=SUBJECT, source_class='company_owned',
                source_url='https://elsewhere.example/', effective_url='https://elsewhere.example/', http_status=200,
                sha256=digest(self.RAW), declared_host='elsewhere.example', source_origin='elsewhere.example',
                robots_checked=True, retrieved_at='2026-10-10T08:00:00Z', ownership_anchor_snapshot_id=anchor))
            with self.assertRaises(ValueError):
                check_web(store, SUBJECT, sid)


if __name__ == '__main__':
    unittest.main()
