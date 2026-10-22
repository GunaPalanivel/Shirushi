"""Exact subject, literal HTML provenance and independent checker attacks."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from shirushi.html_sources import operator_proof
from shirushi.live import covered_families
from shirushi.snapshots import SnapshotStore, digest
from shirushi.web_sources import check_web, page_links
from shirushi_eval.html_support import legal_operator
from shirushi_eval.support import SourceAudit

SUBJECT = '923609016'
NAME = 'Example Pumps AS'


class ExternalHTMLTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(Path(self.temp.name))
        raw = json.dumps({'organisasjonsnummer': SUBJECT, 'navn': NAME}).encode()
        url = 'https://data.brreg.no/enhetsregisteret/api/enheter/' + SUBJECT
        self.anchor = self.store.save(raw, {'organisation_number': SUBJECT, 'source_class': 'brreg_entity',
            'source_url': url, 'effective_url': url, 'http_status': 200, 'sha256': digest(raw),
            'retrieved_at': '2026-10-08T08:00:00Z'})

    def save(self, html, **extra):
        raw = html.encode()
        metadata = {'organisation_number': SUBJECT, 'source_class': 'company_owned',
            'source_url': 'https://example.com/', 'effective_url': 'https://example.com/',
            'http_status': 200, 'sha256': digest(raw), 'source_origin': 'example.com',
            'declared_host': 'example.com', 'robots_checked': True,
            'retrieved_at': '2026-10-08T08:00:00Z', 'ownership_anchor_snapshot_id': self.anchor}
        metadata.update(extra)
        return self.store.save(raw, metadata)

    def footer(self):
        return '<footer>Copyright Example Pumps AS. Org.nr. 923 609 016 MVA</footer>'

    def audit(self, decisions):
        for decision in decisions:
            SourceAudit(self.store.root, [SUBJECT]).claim(SUBJECT, decision['claim'],
                {decision['evidence']['id']: decision['evidence']})

    def test_discovered_domain_html_supports_two_content_families(self):
        raw = (self.footer() + '<p>Example Pumps AS produces industrial pumps &amp; valves.</p>'
               '<p>On 2026-10-01, Example Pumps AS opened a new factory.</p>')
        decisions = check_web(self.store, SUBJECT, self.save(raw))
        self.assertEqual(covered_families([d['claim'] for d in decisions]),
                         {'website_owned_profiles', 'business_products', 'jobs_dated_activity'})
        self.audit(decisions)

    def test_operator_number_is_not_a_phone_customer_or_parent_identity(self):
        for html in ('<footer>Copyright Example Pumps AS. Phone 923609016</footer>',
                     '<p>Customer Example Pumps AS. Org.nr. 923609016</p>',
                     '<footer>Copyright Parent AS. Org.nr. 990888213</footer>',
                     '<footer>Copyright Example Pumps AS. Org.nr. 923609016. Org.nr. 990888213</footer>'):
            self.assertIsNone(operator_proof(html.encode(), SUBJECT, NAME))
            with self.assertRaises(ValueError):
                check_web(self.store, SUBJECT, self.save(html))

    def test_explicit_publisher_and_named_shop_operator_preserve_exact_identity(self):
        for html in ('<p>Example Pumps AS som driver denne nettbutikken er selgeren. '
                     'Vi er registrert med org.nr 923 609 016 MVA.</p>',):
            decisions = check_web(self.store, SUBJECT, self.save(html))
            self.assertEqual([d['field'] for d in decisions], ['verified_website'])
            self.audit(decisions)
        for text in ('Utgiver er ikke Example Pumps AS, med organisasjonsnummer 923609016.',
                     'Utgiver er Parent AS, med organisasjonsnummer 923609016.',
                     'Utgiver er Example Pumps AS, med organisasjonsnummer 990888213.',
                     'Example Pumps AS som ikke driver denne nettbutikken. Org.nr 923609016.',
                     'Example Pumps AS som driver denne nettbutikken p\u00e5 vegne av Parent AS. Org.nr 923609016.',
                     'Example Pumps AS er behandlingsansvarlig. Org.nr 923609016.'):
            self.assertIsNone(operator_proof(('<p>' + text + '</p>').encode(), SUBJECT, NAME))

    def test_magazine_publisher_and_conditional_shop_do_not_prove_ownership(self):
        for text in ('Utgiver er Example Pumps AS for fagbladet Pump News, med organisasjonsnummer '
                     '923609016. Dette nettstedet drives av Parent AS.',
                     'Hvis Example Pumps AS driver denne nettbutikken, gjelder disse kjopsvilkarene '
                     'for selgeren. Org.nr. 923609016.',
                     'Det er mulig at Example Pumps AS driver denne nettbutikken for selgeren. Org.nr. 923609016.',
                     'Example Pumps AS driver denne nettbutikken for selgeren? Nei. Org.nr. 923609016.',
                     'Utgiver er Example Pumps AS, med organisasjonsnummer 923609016.'):
            html = '<p>' + text + '</p>'
            self.assertIsNone(operator_proof(html.encode(), SUBJECT, NAME))
            self.assertIsNone(legal_operator(html.encode(), SUBJECT, NAME))
            with self.assertRaises(ValueError):
                check_web(self.store, SUBJECT, self.save(html))

    def test_registered_website_operation_is_separate_from_magazine_publication(self):
        self.registered_site()
        statement = '<p>Nettstedet drives av Example Pumps AS, som ogs\u00e5 utgir fagbladet Pump News.</p>'
        publisher = '<p>Utgiver er Example Pumps AS, med organisasjonsnummer\u00a0923 609 016.</p>'
        decisions = check_web(self.store, SUBJECT, self.save(statement + publisher))
        self.assertEqual([d['field'] for d in decisions], ['verified_website', 'product_service'])
        self.assertEqual(decisions[0]['evidence']['claim_span'], statement)
        self.audit(decisions)
        for html in (publisher,
                     statement.replace('Nettstedet drives', 'Hvis nettstedet drives'),
                     statement.replace('drives av', 'drives ikke av'),
                     statement.replace('Example Pumps AS', 'Parent AS'),
                     statement + '<p>Dette nettstedet drives av Parent AS.</p>',
                     statement + '<div>Dette nettstedet drives av Parent AS.</div>',
                     statement + '<p>Dette nettstedet drives av Example Pumps AS Holding.</p>',
                     statement + '<div>Org.nr. 990888213.</div>',
                     statement.replace(', som ogs\u00e5 utgir fagbladet Pump News.', '? Nei.'),
                     statement + '<p>Org.nr. 990888213.</p>'):
            self.assertNotIn('verified_website', [d['field'] for d in check_web(self.store, SUBJECT, self.save(html))])

    def test_legal_footer_does_not_attribute_customer_or_group_products(self):
        for content in ('<p>Parent AS produces pumps for Example Pumps AS.</p>',
                        '<p>Example Pumps AS is a customer of Vendor AS which offers pumps.</p>',
                        '<p>Example Pumps AS does not produce pumps.</p>',
                        '<p>Example Pumps AS Parent offers pumps.</p>'):
            decisions = check_web(self.store, SUBJECT, self.save(self.footer() + content))
            self.assertEqual([d['field'] for d in decisions], ['verified_website'])

    def test_named_publisher_clauses_support_literal_services_without_group_transfer(self):
        for content in ('Nettstedet drives av Example Pumps AS, som ogs\u00e5 utgir fagbladet Pump News.',
                        'Bak nettavisen st\u00e5r Example Pumps AS, som ogs\u00e5 er utgiverselskapet for Pump News.'):
            decisions = check_web(self.store, SUBJECT, self.save(self.footer() + '<p>' + content + '</p>'))
            self.assertEqual([d['field'] for d in decisions], ['verified_website', 'product_service'])
            self.assertEqual(decisions[-1]['claim']['value'], content)
            self.audit(decisions)
        for content in ('Parent AS, som ogs\u00e5 utgir fagbladet Pump News for Example Pumps AS.',
                        'Example Pumps AS, som ikke utgir fagbladet Pump News.',
                        'Example Pumps AS er kunde av Parent AS, som utgir fagbladet Pump News.',
                        'Det er ikke Example Pumps AS som utgir fagbladet Pump News.',
                        'Det er ikke Example Pumps AS som er utgiverselskapet for Pump News.',
                        'Hvis Example Pumps AS utgir fagbladet Pump News, vil vi annonsere der.',
                        'Example Pumps AS utgir fagbladet Pump News? Nei.',
                        'Det er mulig at Example Pumps AS utgir fagbladet Pump News.'):
            decisions = check_web(self.store, SUBJECT, self.save(self.footer() + '<p>' + content + '</p>'))
            self.assertEqual([d['field'] for d in decisions], ['verified_website'])
            self.audit(decisions)

    def test_independent_audit_rejects_negated_or_hypothetical_publisher_claim(self):
        positive = '<p>Example Pumps AS utgir fagbladet Pump News.</p>'
        original = check_web(self.store, SUBJECT, self.save(self.footer() + positive))[-1]
        for text in ('Det er ikke Example Pumps AS som utgir fagbladet Pump News.',
                     'Det er ikke Example Pumps AS som er utgiverselskapet for Pump News.',
                     'Hvis Example Pumps AS utgir fagbladet Pump News, vil vi annonsere der.',
                     'Example Pumps AS utgir fagbladet Pump News? Nei.',
                     'Det er mulig at Example Pumps AS utgir fagbladet Pump News.'):
            span = '<p>' + text + '</p>'
            html = self.footer() + span
            sid = self.save(html)
            bad = copy.deepcopy(original)
            claim, evidence = bad['claim'], bad['evidence']
            claim.update(value=text, item_key=digest(text.encode()))
            claim['claim_id'] = digest(json.dumps([SUBJECT, 'product_service', 'company_owned_html',
                claim['item_key'], None], ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())
            eid = sid + ':' + claim['claim_id']
            claim['evidence_ids'] = [eid]
            evidence.update(id=eid, snapshot_id=sid, content_sha256=digest(html.encode()), claim_span=span)
            evidence['locator'].update(html_start=len(self.footer()), html_end=len(html))
            with self.assertRaisesRegex(ValueError, 'unsupported product/service attribution'):
                self.audit([bad])

    def test_hidden_scripts_templates_and_inline_styles_never_publish(self):
        for hidden in ('<div hidden><p>Example Pumps AS produces pumps.</p></div>',
                       '<div style="display: none"><p>Example Pumps AS produces pumps.</p></div>',
                       '<script>Example Pumps AS produces pumps.</script>',
                       '<template><p>Example Pumps AS produces pumps.</p></template>'):
            decisions = check_web(self.store, SUBJECT, self.save(self.footer() + hidden))
            self.assertEqual([d['field'] for d in decisions], ['verified_website'])
            self.audit(decisions)

    def test_empty_style_attribute_does_not_discard_visible_company_facts(self):
        html = '<div style><p>Unrelated introduction.</p></div>' + self.footer()
        decisions = check_web(self.store, SUBJECT, self.save(html))
        self.assertEqual([d['field'] for d in decisions], ['verified_website'])
        self.audit(decisions)

    def test_dated_activity_rejects_future_invalid_and_multiple_dates(self):
        for text in ('2099-01-01', '2026-02-30', '2026-10-01 and 2026-10-02'):
            decisions = check_web(self.store, SUBJECT, self.save(self.footer() +
                '<p>Example Pumps AS opened a factory on ' + text + '.</p>'))
            self.assertEqual([d['field'] for d in decisions], ['verified_website'])

    def test_child_keeps_original_operator_evidence_chain(self):
        root = self.save(self.footer())
        child = self.save('<p>Example Pumps AS offers industrial pumps.</p>', operator_snapshot_id=root,
                          source_url='https://example.com/products', effective_url='https://example.com/products')
        decisions = check_web(self.store, SUBJECT, child)
        self.assertEqual([d['field'] for d in decisions], ['product_service'])
        self.audit(decisions)
        bad = self.save('<p>Example Pumps AS offers industrial pumps.</p>', operator_snapshot_id=root,
                        source_url='https://wrong.com/products', effective_url='https://wrong.com/products',
                        declared_host='wrong.com')
        with self.assertRaises(ValueError):
            check_web(self.store, SUBJECT, bad)

    def test_independent_audit_rejects_forged_value_locator_family_and_hash(self):
        decisions = check_web(self.store, SUBJECT, self.save(self.footer() +
                            '<p>Example Pumps AS offers industrial pumps.</p>'))
        original = next(d for d in decisions if d['field'] == 'product_service')
        for target, key, value in [('claim', 'value', 'Fake product'), ('claim', 'family', 'people'),
                                   ('claim', 'claim_id', '0' * 64), ('evidence', 'claim_span', self.footer())]:
            damaged = copy.deepcopy(original)
            damaged[target][key] = value
            with self.assertRaises(ValueError):
                self.audit([damaged])

    def test_product_links_are_bounded_to_same_safe_host(self):
        html = b'<a href="/products">Products</a><a href="/services">Services</a><a href="https://other.com/products">Other</a>'
        self.assertEqual(page_links(html, 'https://example.com/'),
                         ['https://example.com/products', 'https://example.com/services'])

    def test_query_based_content_links_remain_retrieval_leads(self):
        html = b'<a href="/index.php?page=products">Products</a><a href="https://other.com/?page=products">Other</a>'
        self.assertEqual(page_links(html, 'https://example.com/'),
                         ['https://example.com/index.php?page=products'])

    def registered_site(self):
        raw = json.dumps({'organisasjonsnummer': SUBJECT, 'navn': NAME,
                          'hjemmeside': 'www.example.com'}).encode()
        _, receipt = self.store.open(self.anchor)
        self.anchor = self.store.save(raw, dict(receipt, sha256=digest(raw)))

    def test_registered_page_attributes_named_facts_without_claiming_ownership(self):
        self.registered_site()
        html = ('<p>Example Pumps AS offers industrial pumps.</p>'
                '<p>Example Pumps AS opened a factory on 2026-10-01.</p>'
                '<p>Parent AS supplies warehouse services for Example Pumps AS.</p>')
        decisions = check_web(self.store, SUBJECT, self.save(html))
        self.assertEqual([d['field'] for d in decisions], ['product_service', 'public_activity'])
        self.assertTrue(all(d['claim']['scope'] == 'registry_linked_html' for d in decisions))
        self.audit(decisions)

    def test_exact_named_heading_offer_keeps_literal_layout_span(self):
        self.registered_site()
        for tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            span = '<' + tag + '>Example Pumps AS leverer pumps and valves.</' + tag + '>'
            decisions = check_web(self.store, SUBJECT, self.save(span))
            self.assertEqual([d['field'] for d in decisions], ['product_service'])
            self.assertEqual(decisions[0]['evidence']['claim_span'], span)
            self.audit(decisions)
        for span in ('<h3>Parent AS leverer pumps for Example Pumps AS.</h3>',
                     '<h3>Example Pumps AS leverer ikke pumps.</h3>',
                     '<h3>Example Pumps AS offers no industrial pumps.</h3>',
                     '<h3>Example Pumps AS tilbyr ingen pumper.</h3>',
                     '<h3>Example Pumps AS offers pumps as agent for Parent AS.</h3>',
                     '<blockquote><h3>Example Pumps AS leverer pumps.</h3></blockquote>',
                     '<div hidden><h3>Example Pumps AS leverer pumps.</h3></div>',
                     '<h3>Example Pumps AS leverer <q>no</q> pumps.</h3>',
                     '<h3>Example Pumps AS leverer pumps. Org.nr. 990888213.</h3>'):
            self.assertEqual(check_web(self.store, SUBJECT, self.save(span)), [])

    def test_independent_audit_rejects_negative_and_agency_heading_claims(self):
        self.registered_site()
        original = check_web(self.store, SUBJECT, self.save('<h3>Example Pumps AS offers pumps.</h3>'))[0]
        for text in ('Example Pumps AS offers no industrial pumps.',
                     'Example Pumps AS tilbyr ingen pumper.',
                     'Example Pumps AS offers pumps as agent for Parent AS.'):
            span = '<h3>' + text + '</h3>'
            sid = self.save(span)
            bad = copy.deepcopy(original)
            claim, evidence = bad['claim'], bad['evidence']
            claim.update(value=text, item_key=digest(text.encode()))
            claim['claim_id'] = digest(json.dumps([SUBJECT, 'product_service', 'registry_linked_html',
                claim['item_key'], None], ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())
            eid = sid + ':' + claim['claim_id']
            claim['evidence_ids'] = [eid]
            evidence.update(id=eid, snapshot_id=sid, content_sha256=digest(span.encode()), claim_span=span)
            evidence['locator'].update(html_start=0, html_end=len(span))
            with self.assertRaisesRegex(ValueError, 'unsupported product/service attribution'):
                self.audit([bad])

    def test_named_paragraph_binds_first_person_offer_without_footer_inference(self):
        self.registered_site()
        for text in ('Example Pumps AS er et selskap. Vi leverer pumps and valves.',
                     'Example Pumps AS is a company. We provide industrial pumps.',
                     'Example Pumps AS er representant for Pump Fair. Vi gir r\u00e5d til bedrifter.',
                     'Example Pumps AS er representant for Pump Fair. V\u00e5r oppgave er markedsf\u00f8ring. Vi gir r\u00e5d til bedrifter.'):
            span = '<p>' + text + '</p>'
            decisions = check_web(self.store, SUBJECT, self.save(span))
            self.assertEqual([d['field'] for d in decisions], ['product_service'])
            self.assertEqual(decisions[0]['evidence']['claim_span'], span)
            self.audit(decisions)
        for text in ('Vi leverer pumps and valves.',
                     'Parent AS er et selskap. Vi leverer pumps for Example Pumps AS.',
                     'Example Pumps AS er kunde hos Parent AS. Vi leverer pumps.',
                     'Example Pumps AS er et selskap. Vi leverer ingen pumps.',
                     'Hvis Example Pumps AS er et selskap. Vi leverer pumps.',
                     'Example Pumps AS er et selskap. Vi leverer pumps p\u00e5 vegne av Parent AS.',
                     'Example Pumps AS er et selskap. Parent sier: Vi leverer pumps.',
                     'Example Pumps AS is mentioned by Acme: "Business is growing. We provide industrial pumps."',
                     'Example Pumps AS er omtalt av Partner: "Virksomheten vokser. Vi leverer pumper."',
                     'Example Pumps AS is an investor in Parent PLC. We provide industrial pumps.',
                     'Example Pumps AS er et selskap eid av Other as. Vi leverer pumper.',
                     "Example Pumps AS is a company discussed by Acme in the statement 'Business is growing. We provide industrial pumps.'",
                     'Example Pumps AS is a company discussed by Acme in the statement \u2018Business is growing. We provide industrial pumps.\u2019',
                     'Example Pumps AS er del av konsernet. Vi leverer pumps.'):
            self.assertEqual(check_web(self.store, SUBJECT, self.save('<p>' + text + '</p>')), [])
        separate = '<p>Example Pumps AS er et selskap.</p><p>Vi leverer pumps.</p>'
        self.assertEqual(check_web(self.store, SUBJECT, self.save(separate)), [])

    def test_independent_audit_rejects_wrong_speaker_first_person_claim(self):
        self.registered_site()
        original = check_web(self.store, SUBJECT, self.save(
            '<p>Example Pumps AS is a company. We provide industrial pumps.</p>'))[0]
        for text in ('Example Pumps AS is mentioned by Acme: "Business is growing. We provide industrial pumps."',
                     'Example Pumps AS is an investor in Parent PLC. We provide industrial pumps.',
                     'Example Pumps AS er et selskap eid av Other as. Vi leverer pumper.'):
            span = '<p>' + text + '</p>'
            sid = self.save(span)
            bad = copy.deepcopy(original)
            claim, evidence = bad['claim'], bad['evidence']
            claim.update(value=text, item_key=digest(text.encode()))
            claim['claim_id'] = digest(json.dumps([SUBJECT, 'product_service', 'registry_linked_html',
                claim['item_key'], None], ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())
            eid = sid + ':' + claim['claim_id']
            claim['evidence_ids'] = [eid]
            evidence.update(id=eid, snapshot_id=sid, content_sha256=digest(span.encode()), claim_span=span)
            evidence['locator'].update(html_start=0, html_end=len(span))
            with self.assertRaisesRegex(ValueError, 'unsupported product/service attribution'):
                self.audit([bad])

    def test_registered_page_does_not_turn_controller_or_name_similarity_into_facts(self):
        self.registered_site()
        for text in ('OtherExample Pumps AS offers valves.',
                     'Example Pumps AS does not offer valves.',
                     'Example Pumps AS offers valves. Org.nr. 990888213.',
                     'Parent AS offers valves to Example Pumps AS.',
                     'Example Pumps AS is the data controller.',
                     '<blockquote>Example Pumps AS offers valves.</blockquote>',
                     '<div hidden>Example Pumps AS offers valves.</div>'):
            self.assertEqual(check_web(self.store, SUBJECT, self.save('<p>' + text + '</p>')), [])

    def test_visible_quotation_is_not_deleted_to_manufacture_a_positive_assertion(self):
        self.registered_site()
        for text in ('Example Pumps AS offers <q>no</q> industrial pumps.',
                     'Example Pumps AS offers <q>never</q> industrial pumps.'):
            self.assertEqual(check_web(self.store, SUBJECT, self.save('<p>' + text + '</p>')), [])
        decisions = check_web(self.store, SUBJECT, self.save(
            '<p>Example Pumps AS offers <q>no</q> pumps.</p>'
            '<p>Example Pumps AS offers valves.</p>'))
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]['claim']['value'], 'Example Pumps AS offers valves.')
        self.audit(decisions)

    def test_named_fact_on_unregistered_host_still_requires_source_attribution(self):
        self.registered_site()
        with self.assertRaises(ValueError):
            check_web(self.store, SUBJECT, self.save('<p>Example Pumps AS offers valves.</p>',
                source_url='https://wrong.com/', effective_url='https://wrong.com/', declared_host='wrong.com'))

    def test_independent_audit_rejects_forged_registry_linked_content(self):
        self.registered_site()
        original = check_web(self.store, SUBJECT, self.save('<p>Example Pumps AS offers valves.</p>'))[0]
        self.audit([original])
        for target, key, value in [('claim', 'value', 'Unknown product'),
                                   ('claim', 'scope', 'company_owned_html'),
                                   ('evidence', 'claim_span', '<p>Parent AS offers valves.</p>'),
                                   ('evidence', 'extraction_method', 'explicit_subject_html_v1')]:
            damaged = copy.deepcopy(original)
            damaged[target][key] = value
            with self.assertRaises(ValueError):
                self.audit([damaged])

    def test_independent_audit_rejects_unpermitted_registry_linked_receipts(self):
        self.registered_site()
        html = '<p>Example Pumps AS offers valves.</p>'
        good = check_web(self.store, SUBJECT, self.save(html))[0]
        for extra in ({'http_status': 403}, {'robots_checked': False},
                      {'declared_host': 'wrong.com'}, {'sha256': '0' * 64}):
            sid = self.save(html, **extra)
            _, receipt = self.store.open(sid)
            bad = copy.deepcopy(good)
            eid = sid + ':' + bad['claim']['claim_id']
            bad['claim']['evidence_ids'] = [eid]
            bad['evidence'].update(id=eid, snapshot_id=sid, content_sha256=receipt['content_sha256'])
            with self.assertRaises(ValueError):
                self.audit([bad])

    def controller(self):
        return ('<p>Example Pumps AS (Example Road 1), ved daglig leder, er '
                'behandlingsansvarlig for behandling av personopplysninger i forbindelse '
                'med drift og vedlikehold av example.com.</p>')

    def test_registered_site_and_explicit_domain_operator_support_content(self):
        self.registered_site()
        owner = self.save(self.controller(), source_url='https://example.com/personvern',
                          effective_url='https://example.com/personvern')
        decisions = check_web(self.store, SUBJECT, owner)
        self.assertEqual([d['field'] for d in decisions], ['verified_website'])
        child = self.save('<p>Example Pumps AS er et moderne konsulentselskap som leverer IT-systemer.</p>',
                          operator_snapshot_id=owner)
        decisions += check_web(self.store, SUBJECT, child)
        self.assertEqual([d['field'] for d in decisions], ['verified_website', 'business_description'])
        self.audit(decisions)

    def test_controller_alone_does_not_prove_website_operation(self):
        self.assertIsNone(operator_proof(self.controller().encode(), SUBJECT, NAME))
        self.registered_site()
        for html in (self.controller().replace('example.com', 'other.com'),
                     self.controller().replace('example.com', 'example.com.evil.test'),
                     self.controller().replace('er behandlingsansvarlig', 'er ikke behandlingsansvarlig'),
                     self.controller().replace('Example Pumps AS', 'Parent AS'),
                     self.controller().replace('drift og vedlikehold av example.com', 'kundedata'),
                     self.controller().replace('example.com.', 'example.com på vegne av Parent AS.'),
                     self.controller().replace('</p>', ' Org.nr. 990888213</p>'),
                     self.controller() + '<footer>Parent AS. Org.nr. 990888213</footer>',
                     '<div hidden>' + self.controller() + '</div>'):
            self.assertEqual(check_web(self.store, SUBJECT, self.save(html)), [])
        wrong_host = self.save(self.controller(), source_url='https://wrong.com/',
                               effective_url='https://wrong.com/', declared_host='wrong.com')
        with self.assertRaises(ValueError):
            check_web(self.store, SUBJECT, wrong_host)

    def test_independent_audit_rejects_registered_site_controller_on_wrong_host(self):
        self.registered_site()
        good = check_web(self.store, SUBJECT, self.save(self.controller()))[0]
        sid = self.save(self.controller(), source_url='https://wrong.com/',
                        effective_url='https://wrong.com/', declared_host='wrong.com')
        _, receipt = self.store.open(sid)
        bad = copy.deepcopy(good)
        bad['evidence'].update(snapshot_id=sid, source_url=receipt['source_url'],
                               content_sha256=receipt['content_sha256'])
        with self.assertRaises(ValueError):
            self.audit([bad])

    def test_company_definition_rejects_customer_parent_and_negation(self):
        for content in ('Example Pumps AS er en kunde av et konsulentselskap.',
                        'Example Pumps AS er ikke et konsulentselskap.',
                        'Customer Example Pumps AS. OtherExample Pumps AS er et moderne konsulentselskap.',
                        'Parent AS er et konsulentselskap for Example Pumps AS.'):
            decisions = check_web(self.store, SUBJECT, self.save(self.footer() + '<p>' + content + '</p>'))
            self.assertEqual([d['field'] for d in decisions], ['verified_website'])
            self.audit(decisions)

    def test_observed_legal_and_contact_forms_are_retrieval_leads(self):
        paths = ['/conditionsofuse', '/personvernerklaering/', '/contactus', '/privacy-notice', '/betingelser']
        html = ''.join('<a href="' + path + '">Read</a>' for path in paths).encode()
        self.assertEqual(set(page_links(html, 'https://example.com/')),
                         {'https://example.com' + path for path in paths})

    def test_character_locators_preserve_unicode_and_crlf(self):
        html = '<div>Norwegian \u00e5 and separator \u2028</div>\r\n' + self.footer() + '\r\n<p>Example Pumps AS offers valves.</p>'
        decisions = check_web(self.store, SUBJECT, self.save(html))
        self.assertEqual(len(decisions), 2)
        self.audit(decisions)
