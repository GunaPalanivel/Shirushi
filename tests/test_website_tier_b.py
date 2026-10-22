"""Registry-corroborated website publication: positive controls, hard identifiers and abstentions."""
import json
import tempfile
import unittest
from pathlib import Path

from shirushi.snapshots import SnapshotStore, digest
from shirushi.web_sources import check_web
from shirushi.website_sources import website_assessment

FILLER = ('<p>Vi leverer pumper, tjenester og vedlikehold til bedrifter i hele landet, og har gjort det i mange år. '
          'Ta kontakt for en uforpliktende prat om dine behov.</p>')
ID_FOOTER = '<footer>Org.nr 923 609 016</footer>'
ADDRESS = {'adresse': ['Storgata 1'], 'postnummer': '1234', 'poststed': 'TESTBY', 'kommune': 'TESTBY'}


class WebsiteTierBTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(Path(self.temp.name))
        self.subject, self.name = '923609016', 'EXAMPLE PUMPS AS'

    def anchor(self, website='example.no', email='post@example.no', name=None, address=ADDRESS):
        row = {'organisasjonsnummer': self.subject, 'navn': name or self.name}
        if website is not None:
            row['hjemmeside'] = website
        if email is not None:
            row['epostadresse'] = email
        if address is not None:
            row['forretningsadresse'] = address
        raw = json.dumps(row).encode()
        return self.store.save(raw, dict(organisation_number=self.subject, source_class='brreg_entity',
            source_url='https://data.brreg.no/enhetsregisteret/api/enheter/' + self.subject,
            http_status=200, sha256=digest(raw), retrieved_at='2026-10-10T08:00:00Z'))

    def page(self, html, host='example.no', path='/', **registry):
        anchor = self.anchor(**registry)
        raw = html.encode()
        return self.store.save(raw, dict(organisation_number=self.subject, source_class='company_owned',
            source_url='https://' + host + path, effective_url='https://' + host + path, content_type='text/html',
            http_status=200, sha256=digest(raw), declared_host=host, source_origin=host, robots_checked=True,
            retrieved_at='2026-10-10T08:00:00Z', ownership_anchor_snapshot_id=anchor)), anchor

    def website(self, html, **kwargs):
        sid, anchor = self.page(html, **kwargs)
        self.page_sid, self.anchor_sid = sid, anchor
        return [d for d in check_web(self.store, self.subject, sid) if d['field'] == 'verified_website']

    def doc(self, title='Pumper og service', body=FILLER, head='', h1='', ident=ID_FOOTER):
        return ('<!doctype html><html lang="no"><head><title>' + title + '</title>' + head + '</head><body>'
                + (('<h1>' + h1 + '</h1>') if h1 else '') + body + ident + '</body></html>')

    # positive controls: registry corroboration plus a hard identifier on the page
    def test_org_number_on_the_page_and_registry_email_domain_publish_with_assessment(self):
        decisions = self.website(self.doc())
        self.assertEqual(len(decisions), 1)
        claim, evidence = decisions[0]['claim'], decisions[0]['evidence']
        self.assertEqual((claim['field'], claim['value'], claim['scope'], claim['family'], claim['availability']),
                         ('verified_website', 'https://example.no/', 'registry_declared_host_name_gate',
                          'website_owned_profiles', 'available'))
        self.assertEqual(evidence['extraction_method'], 'registry_host_corroboration_v1')
        self.assertEqual(evidence['snapshot_id'], self.page_sid)
        self.assertEqual(evidence['claim_span'], ID_FOOTER)
        raw, _ = self.store.open(self.page_sid)
        loc = evidence['locator']
        self.assertEqual(raw.decode()[loc['html_start']:loc['html_end']], evidence['claim_span'])
        self.assertEqual(loc['identity_part'], 'org_number')
        assessment = evidence['identity_assessment']
        self.assertEqual((assessment['score'], assessment['status'], assessment['path']), (0.95, 'exact', 'registry_corroborated'))
        self.assertEqual(assessment['anchor_snapshot_id'], self.anchor_sid)
        self.assertEqual(assessment['identifier']['kind'], 'org_number')
        self.assertEqual(assessment['corroboration'], [{'kind': 'email_domain', 'registry_field': 'epostadresse',
                                                        'registry_value': 'post@example.no', 'domain': 'example.no'}])
        self.assertRegex(assessment['visible_text_sha256'], r'^[0-9a-f]{64}$')
        self.assertTrue(assessment['reasons'])

    def test_visible_text_hash_joins_inline_tags_without_a_gap(self):
        from shirushi_eval.website_support import Page
        raw = (b'<html><head><title>T</title></head><body><p>a</p><p>b<b>c</b></p>'
               b'<span hidden>x</span><script>y</script><!-- z --> d&nbsp;e</body></html>')
        anchor = {'navn': self.name, 'hjemmeside': 'example.no', 'epostadresse': 'post@example.no',
                  'forretningsadresse': ADDRESS}
        assessment = website_assessment(raw, self.subject, anchor, 'https://example.no/')
        self.assertEqual(Page(raw).visible, 'a bc d e')
        self.assertEqual(assessment['visible_text_sha256'], digest(Page(raw).visible.encode()))

    def test_every_recognised_org_number_format_is_a_hard_identifier(self):
        for text in ('Org.nr 923 609 016', 'Org nr: 923609016', 'Organisasjonsnummer: 923.609.016',
                     'NO 923 609 016 MVA', 'NO923609016MVA', 'Faktura: 923 609 016'):
            decisions = self.website(self.doc(ident='<footer>' + text + '</footer>'))
            self.assertEqual(len(decisions), 1, text)
            self.assertEqual(decisions[0]['evidence']['locator']['identity_part'], 'org_number', text)

    def test_registry_street_with_postcode_or_town_is_a_hard_identifier(self):
        for text in ('Storgata 1, 1234 Oslo', 'STORGATA 1 Testby', 'Besøk oss: Storgata 1, 1234',
                     'Storgåta 1, 1234'.replace('å', 'a')):
            decisions = self.website(self.doc(ident='<footer>' + text + '</footer>'))
            self.assertEqual(len(decisions), 1, text)
            self.assertEqual(decisions[0]['evidence']['locator']['identity_part'], 'registry_address', text)
        # c/o lines and post boxes are not street names; the next line is
        decisions = self.website(self.doc(ident='<footer>Storgata 1, 1234 Oslo</footer>'),
                                 address=dict(ADDRESS, adresse=['c/o Noen', 'Storgata 1']))
        self.assertEqual(len(decisions), 1)

    def test_street_alone_postcode_alone_town_alone_or_another_number_are_not_identifiers(self):
        for text in ('Storgata 1', 'Storgata, 1234 Oslo', '1234 Testby', 'Storgata 12, 1234 Oslo',
                     'Drammensveien 130, 0277 Oslo', 'Besøk Testby kommune'):
            self.assertEqual(self.website(self.doc(ident='<footer>' + text + '</footer>')), [], text)
        self.assertEqual(self.website(self.doc(ident='<footer>Storgata 1, 1234 Oslo</footer>'), address=None), [])

    def test_exact_legal_name_with_form_in_title_heading_footer_copyright_or_contact_block(self):
        cases = ((self.doc(title='Example Pumps AS - Pumper', ident=''), 'title'),
                 (self.doc(h1='Velkommen til Example Pumps AS', ident=''), 'h1'),
                 (self.doc(ident='<footer>Example Pumps AS</footer>'), 'footer'),
                 (self.doc(ident='<div>© 2026 Example Pumps AS</div>'), 'copyright'),
                 (self.doc(ident='<div>Example Pumps AS, kontakt: post@example.no, tlf 22 22 22 22</div>'), 'contact_block'))
        for html, part in cases:
            decisions = self.website(html)
            self.assertEqual(len(decisions), 1, html)
            self.assertEqual(decisions[0]['evidence']['locator']['identity_part'], part, html)
        self.assertEqual(self.website(cases[0][0])[0]['evidence']['identity_assessment']['score'], 0.95)

    def test_separators_labels_and_adjacent_blocks_do_not_hide_an_identifier(self):
        for html, part in ((self.doc(title='Jobb — Example Pumps AS', ident=''), 'title'),
                           (self.doc(ident='<footer>Besøksadresse Oslo Example Pumps AS Storgata 5</footer>'), 'footer'),
                           (self.doc(ident='<footer><div>Example Pumps AS</div><div>Storgata 1</div><div>1234 Oslo</div></footer>'),
                            'registry_address')):
            decisions = self.website(html)
            self.assertEqual(len(decisions), 1, html)
            self.assertEqual(decisions[0]['evidence']['locator']['identity_part'], part, html)
        decisions = self.website(self.doc(ident='<footer>Storgata 1 Testby</footer>'),
                                 address=dict(ADDRESS, poststed='TESTBY N'))
        self.assertEqual(len(decisions), 1)

    def test_brand_or_trade_name_and_plain_mentions_are_not_identifiers(self):
        for html in (self.doc(title='Example Pumps - Pumper', ident=''),
                     self.doc(ident='<footer>© 2026 Example Pumps</footer>'),
                     self.doc(ident='<p>Vi selger pumper fra Example Pumps AS.</p>'),
                     self.doc(ident='<blockquote><p>Example Pumps AS, kontakt: post@example.no</p></blockquote>'),
                     self.doc(ident='<footer>Example Pumps AS Holding</footer>'),
                     self.doc(title='Nordic Example Pumps AS', ident=''),
                     self.doc(h1='Nordic Example Pumps AS', ident=''),
                     self.doc(ident='<div hidden>Example Pumps AS © 2026</div>')):
            self.assertEqual(self.website(html), [], html)

    def test_corroboration_alone_never_publishes(self):
        self.assertEqual(self.website(self.doc(ident='')), [])
        self.assertEqual(self.website(self.doc(ident=''), website='examplepumps.no', email=None,
                                      host='examplepumps.no'), [])

    def test_registry_name_equal_to_bare_host_label_publishes_with_an_identifier(self):
        decisions = self.website(self.doc(), website='examplepumps.no', email=None, host='examplepumps.no')
        self.assertEqual([d['claim']['value'] for d in decisions], ['https://examplepumps.no/'])
        kinds = [c['kind'] for c in decisions[0]['evidence']['identity_assessment']['corroboration']]
        self.assertEqual(kinds, ['name_host_label'])

    def test_vendor_or_provider_domain_only_corroborates_by_the_companys_own_name(self):
        decisions = self.website(self.doc(), website='poweroffice.no', email='post@poweroffice.no',
                                 host='poweroffice.no', name='POWEROFFICE AS')
        kinds = [c['kind'] for c in decisions[0]['evidence']['identity_assessment']['corroboration']]
        self.assertEqual(kinds, ['name_host_label'])

    def test_score_is_lower_for_an_address_than_for_a_number_or_title_name(self):
        address = self.website(self.doc(ident='<footer>Storgata 1, 1234 Oslo</footer>'))
        self.assertEqual(address[0]['evidence']['identity_assessment']['score'], 0.9)
        both = self.website(self.doc(ident='<footer>Storgata 1, 1234 Oslo</footer>'), website='examplepumps.no',
                            email='post@examplepumps.no', host='examplepumps.no')
        self.assertEqual(both[0]['evidence']['identity_assessment']['score'], 0.95)

    def test_www_alias_mail_subdomain_and_page_without_title(self):
        self.assertEqual([d['claim']['value'] for d in self.website(self.doc(), host='www.example.no')],
                         ['https://www.example.no/'])
        self.assertEqual(len(self.website(self.doc(), email='Post@Kontor.Example.NO ')), 1)
        decisions = self.website('<html><body>' + FILLER + ID_FOOTER + '</body></html>')
        self.assertEqual(decisions[0]['evidence']['claim_span'], ID_FOOTER)

    def test_same_bytes_give_identical_decisions(self):
        first = self.website(self.doc())
        second = self.website(self.doc())
        self.assertEqual(first, second)

    # registry corroboration must come from the registry row
    def test_unrelated_free_shared_platform_public_and_accountant_mail_domains_do_not_corroborate(self):
        for website, email in (('example.no', 'example@gmail.com'), ('example.no', 'post@online.no'),
                               ('example.no', 'post@other.no'), ('example.no', None), ('example.no', 'not an email'),
                               ('example.no', 'a@b@example.no'),
                               ('shop.wixsite.com', 'x@shop.wixsite.com'), ('wixsite.com', 'x@wixsite.com'),
                               ('bergen.kommune.no', 'post@bergen.kommune.no'),
                               ('tripletex.no', 'post@tripletex.no'), ('proff.no', 'post@proff.no'),
                               ('facebook.com', 'a@facebook.com'), ('telenor.no', 'x@telenor.no'),
                               ('example.no', 'post@exampel.no')):
            self.assertEqual(self.website(self.doc(), website=website, email=email, host=website), [], (website, email))

    def test_name_tie_needs_the_bare_ascii_host_label_and_a_distinct_name(self):
        for website, name in (('pumps.example.no', 'EXAMPLE PUMPS AS'), ('examplepumps.com', 'EXAMPLE PUMPS TRONDHEIM AS'),
                              ('ex.no', 'EX AS'), ('xn--exmplepumps-yzb.no', 'EXAMPLEPUMPS AS')):
            self.assertEqual(self.website(self.doc(), website=website, email=None, host=website, name=name), [],
                             (website, name))

    # the page must load and be readable
    def test_placeholder_parked_and_unreadable_pages_abstain(self):
        pages = (self.doc(body='<p>This domain is for sale. ' + 'x ' * 80 + '</p>'),
                 self.doc(body='<p>Domenet er til salgs. Kontakt oss. ' + 'x ' * 80 + '</p>'),
                 self.doc(body='<p>Coming soon</p>'),
                 self.doc(body='<div id="root"></div><script>document.title="Example Pumps AS"; ' + 'x' * 400 + '</script>'),
                 self.doc(body='<noscript>' + FILLER + '</noscript>'),
                 self.doc(body='<div hidden>' + FILLER + '</div>'),
                 self.doc(body='<!-- ' + FILLER + ' -->'))
        for html in pages:
            self.assertEqual(self.website(html), [], html)

    # conflicts abstain
    def test_other_organisation_number_other_legal_entity_and_group_markers_abstain(self):
        for html in (self.doc(body=FILLER + '<footer>Org.nr 987 654 321</footer>'),
                     self.doc(body=FILLER + '<footer>NO 987654321 MVA</footer>'),
                     self.doc(head='<script type="application/ld+json">{"@type":"Organization","vatID":"NO987654321MVA"}</script>'),
                     self.doc(title='Parent Group AS - Pumper'),
                     self.doc(h1='Welcome to Parent Group AS'),
                     self.doc(head='<meta property="og:site_name" content="Parent Group AS">'),
                     self.doc(h1='Pumper, et datterselskap'),
                     self.doc(title='Pumper - del av Parent'),
                     self.doc(body=FILLER + '<footer>Example Pumps AS er et datterselskap i Parent</footer>'),
                     self.doc(body=FILLER + '<footer>Part of the Parent family</footer>'),
                     self.doc(body=FILLER + '<footer>Medlem av konsernet</footer>')):
            self.assertEqual(self.website(html), [], html)

    def test_subject_number_and_own_name_are_not_conflicts(self):
        html = self.doc(title='Example Pumps AS', body=FILLER + '<footer>© 2026 Example Pumps AS. Org.nr 923 609 016</footer>')
        # the legal operator proof is the stronger path and keeps the website claim
        decisions = self.website(html)
        self.assertEqual([d['claim']['scope'] for d in decisions], ['company_owned_html'])
        self.assertEqual(len(self.website(self.doc(title='Example Pumps AS', body=FILLER + '<p>Org.nr 923 609 016</p>'))), 1)

    # host and page scope
    def test_wrong_host_and_registry_path_abstain(self):
        with self.assertRaisesRegex(ValueError, 'not anchored'):
            self.website(self.doc(), host='other.no')
        with self.assertRaisesRegex(ValueError, 'not anchored'):
            self.website(self.doc(), host='shop.example.no')
        # any page of the corroborated host supports the one site-root claim
        self.assertEqual([d['claim']['value'] for d in self.website(self.doc(), path='/om-oss')], ['https://example.no/'])
        self.assertEqual(self.website(self.doc(), website='example.no/shop'), [])

    def test_no_registry_website_abstains(self):
        with self.assertRaises(ValueError):
            self.website(self.doc(), website=None)

    # six adjudicated regressions (paraphrased pages): none may publish
    def test_global_parent_site_with_only_the_registry_email_domain_abstains(self):
        html = ('<html><head><title>Falck</title></head><body><nav>Careers News Services</nav>'
                '<p>We save lives, help people in need and keep societies running every day around the world, '
                'with ambulances, assistance and healthcare services in many countries.</p>'
                '<footer>© 2020 Falck A/S</footer></body></html>')
        self.assertEqual(self.website(html, website='falck.com', email='kundesenter@falck.com', host='falck.com',
                                      name='FALCK NORGE AS'), [])
        anchor = {'navn': 'FALCK NORGE AS', 'hjemmeside': 'falck.com', 'epostadresse': 'kundesenter@falck.com'}
        result = website_assessment(html.encode(), self.subject, anchor, 'https://falck.com/')
        self.assertFalse(result['publishable'])
        self.assertIn('foreign', ' '.join(result['reasons']))

    def test_foreign_parent_footer_does_not_veto_a_page_that_shows_the_norwegian_entity(self):
        html = self.doc(ident='<footer>© 2020 Parent A/S. Org.nr 923 609 016</footer>')
        self.assertEqual(len(self.website(html)), 1)

    def test_brand_only_copyright_line_abstains(self):
        html = self.doc(title='Ekstralys', body=FILLER, ident='<footer>Copyright © 2026 All rights Reserved Ekstralys</footer>')
        self.assertEqual(self.website(html, website='ekstralys.no', email=None, host='ekstralys.no', name='EKSTRALYS AS'), [])

    def test_script_shell_menu_pages_abstain_and_count_as_one_text(self):
        menu = '<nav>' + ' '.join('<a href="/s%d">Meny punkt %d</a>' % (i, i) for i in range(40)) + '</nav>'
        first = self.doc(title='Apotek 1', body=menu, ident='')
        second = self.doc(title='Apotek 1 - Kontakt', body=menu, ident='')
        for html in (first, second):
            self.assertEqual(self.website(html, website='apotek1.no', email='post@apotek1.no', host='apotek1.no',
                                          name='APOTEK 1 GRUPPEN AS'), [])
        anchor = {'navn': 'APOTEK 1 GRUPPEN AS', 'hjemmeside': 'apotek1.no', 'epostadresse': 'post@apotek1.no'}
        shas = {website_assessment(h.encode(), self.subject, anchor, 'https://apotek1.no/')['visible_text_sha256']
                for h in (first, second)}
        self.assertEqual(len(shas), 1)

    def test_landing_page_with_another_address_and_two_brands_abstains(self):
        html = ('<html><head><title>3D</title></head><body><h2>Bang &amp; Olufsen | Oslo Vest</h2>'
                '<p>Drammensveien 130, 0277 Oslo - MOBIT Follo - se våre butikker og velg avdeling for mer informasjon.</p>'
                '</body></html>')
        self.assertEqual(self.website(html, website='3d.no', email='regnskap@3d.no', host='3d.no',
                                      name='3D-BEDRIFT AS', address=dict(ADDRESS, adresse=['Industriveien 5'])), [])

    def test_under_construction_page_with_distinctive_name_abstains(self):
        html = ('<html><head><title>Romlaboratoriet</title></head><body><p>Vi er Romlaboratoriet, et tverrfaglig kontor '
                'for arkitektur og interiørarkitektur. Vi jobber med en ny nettside, og den kommer snart. '
                'Ta gjerne kontakt for et prosjekt.</p></body></html>')
        self.assertEqual(self.website(html, website='romlab.no', email='post@romlab.no', host='romlab.no',
                                      name='ROMLABORATORIET AS'), [])

    def test_chain_brand_site_without_legal_form_address_or_number_abstains(self):
        html = ('<html><head><title>HJEM | Bislett Kebab House</title></head><body><h1>Bislett Kebab House</h1>'
                '<p>Våre avdelinger finner du i flere bydeler. Bestill bord eller ta med hjem, vi lager alt fra bunnen.</p>'
                '<footer>© 2026 Bislett Kebab House</footer></body></html>')
        self.assertEqual(self.website(html, website='bislettkebabhouse.no', email='tariq@bislettkebabhouse.no',
                                      host='bislettkebabhouse.no', name='BISLETT KEBAB HOUSE AS'), [])

    def test_assessment_function_explains_each_abstention(self):
        anchor = {'navn': self.name, 'hjemmeside': 'example.no', 'epostadresse': 'post@example.no',
                  'forretningsadresse': ADDRESS}
        good = website_assessment(self.doc().encode(), self.subject, anchor, 'https://example.no/')
        self.assertTrue(good['publishable'])
        for html, reason in ((self.doc(body='<p>Coming soon</p>'), 'readable'),
                             (self.doc(title='Parent Group AS'), 'legal entity'),
                             (self.doc(body=FILLER + '<footer>Org.nr 987 654 321</footer>'), 'organisation number'),
                             (self.doc(ident=''), 'hard identifier')):
            result = website_assessment(html.encode(), self.subject, anchor, 'https://example.no/')
            self.assertFalse(result['publishable'])
            self.assertIn(reason, ' '.join(result['reasons']))
        none = website_assessment(self.doc().encode(), self.subject, dict(anchor, epostadresse='a@gmail.com'),
                                  'https://example.no/')
        self.assertFalse(none['publishable'])
        self.assertIn('corroborat', ' '.join(none['reasons']))


if __name__ == '__main__':
    unittest.main()
