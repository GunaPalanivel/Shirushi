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

    def test_legal_footer_does_not_attribute_customer_or_group_products(self):
        for content in ('<p>Parent AS produces pumps for Example Pumps AS.</p>',
                        '<p>Example Pumps AS is a customer of Vendor AS which offers pumps.</p>',
                        '<p>Example Pumps AS does not produce pumps.</p>',
                        '<p>Example Pumps AS Parent offers pumps.</p>'):
            decisions = check_web(self.store, SUBJECT, self.save(self.footer() + content))
            self.assertEqual([d['field'] for d in decisions], ['verified_website'])

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

    def registered_site(self):
        raw = json.dumps({'organisasjonsnummer': SUBJECT, 'navn': NAME,
                          'hjemmeside': 'www.example.com'}).encode()
        _, receipt = self.store.open(self.anchor)
        self.anchor = self.store.save(raw, dict(receipt, sha256=digest(raw)))

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
