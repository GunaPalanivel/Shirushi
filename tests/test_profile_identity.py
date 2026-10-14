"""Cross-span organization identity, without inferred website ownership."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shirushi.snapshots import SnapshotStore, digest
from shirushi.web_sources import check_web
from shirushi_eval.support import SourceAudit


class ProfileIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(Path(self.temp.name))
        self.subject, self.name = '923609016', 'Example Pumps AS'
        raw = json.dumps({'organisasjonsnummer': self.subject, 'navn': self.name, 'hjemmeside': 'example.com'}).encode()
        self.anchor = self.store.save(raw, dict(organisation_number=self.subject, source_class='brreg_entity',
            source_url='https://data.brreg.no/enhetsregisteret/api/enheter/' + self.subject,
            http_status=200, sha256=digest(raw), retrieved_at='2026-10-10T08:00:00Z'))

    def node(self):
        return {'@context': 'https://schema.org', '@type': 'Organization', '@id': 'https://example.com/#organization',
            'name': self.name, 'url': 'https://example.com/', 'description': 'We supply industrial pumps.',
            'address': {'@type': 'PostalAddress', 'streetAddress': 'Example Road 14',
                        'postalCode': '8624', 'addressLocality': 'Example City'}}

    def footer(self):
        return ('<footer><div><p>Example Pumps AS</p> <p>Example Road 14, 8624 Example City</p> '
                '<p>Org.nr: 923609016</p></div></footer>')

    def save(self, node=None, footer=None, host='example.com', prefix=''):
        node = self.node() if node is None else node
        footer = self.footer() if footer is None else footer
        html = prefix + '<script type="application/ld+json">' + json.dumps(node) + '</script>' + footer
        raw = html.encode()
        return self.store.save(raw, dict(organisation_number=self.subject, source_class='company_owned',
            source_url='https://' + host + '/', effective_url='https://' + host + '/',
            http_status=200, sha256=digest(raw), declared_host=host, source_origin=host, robots_checked=True,
            retrieved_at='2026-10-10T08:00:00Z', ownership_anchor_snapshot_id=self.anchor))

    def audit(self, decisions):
        audit = SourceAudit(self.store.root, [self.subject])
        for d in decisions:
            audit.claim(self.subject, d['claim'], {d['evidence']['id']: d['evidence']})

    def test_name_address_and_visible_org_join_preserves_both_spans(self):
        decisions = check_web(self.store, self.subject, self.save())
        self.assertEqual([d['field'] for d in decisions], ['business_description'])
        self.assertEqual(decisions[0]['claim']['value'], self.node()['description'])
        self.assertEqual(decisions[0]['claim']['scope'], 'registry_linked_structured')
        self.assertIn('Org.nr: 923609016', decisions[0]['evidence']['support_spans']['legal_identity'])
        self.audit(decisions)

    def test_parent_name_address_id_and_quoted_customer_records_do_not_bind(self):
        for key, value in (('name', 'Parent AS'), ('@id', 'https://other.com/#organization'),
                           ('@context', 'https://other.com/schema'), ('@context', {'description': 'https://other.com'}),
                           ('taxID', '990888213'), ('identifier', {'value': '990888213'})):
            node = self.node()
            node[key] = value
            self.assertEqual(check_web(self.store, self.subject, self.save(node)), [])
        for key, value in (('streetAddress', 'Other Road 14'), ('postalCode', '9999'), ('addressLocality', 'Other City')):
            node = self.node()
            node['address'][key] = value
            self.assertEqual(check_web(self.store, self.subject, self.save(node)), [])
        for footer in ('', self.footer().replace('Org.nr:', 'Phone:'),
                       self.footer().replace('923609016', '990888213'),
                       self.footer().replace('Example Pumps AS', 'Customer Example Pumps AS'),
                       self.footer().replace('Example Pumps AS', 'Example Pumps AS Holding'),
                       self.footer().replace('Example Road 14', 'OtherExample Road 145'),
                       self.footer().replace('8624', '86240'),
                       '<div hidden>' + self.footer() + '</div>',
                       '<blockquote>' + self.footer() + '</blockquote>',
                       self.footer().replace('Example Pumps AS', 'Example Pumps AS<q>customer</q>')):
            self.assertEqual(check_web(self.store, self.subject, self.save(footer=footer)), [])
        with self.assertRaises(ValueError):
            check_web(self.store, self.subject, self.save(host='other.com'))

    def test_independent_audit_rejects_forged_identity_span_description_and_locator(self):
        original = check_web(self.store, self.subject, self.save())[0]
        for kind, value in (('span', '<footer>Different identity</footer>'), ('description', 'We manufacture aircraft.'),
                            ('locator', -1)):
            bad = copy.deepcopy(original)
            if kind == 'span':
                bad['evidence']['support_spans']['legal_identity'] = value
            elif kind == 'description':
                bad['claim']['value'] = value
            else:
                bad['evidence']['locator']['identity_html_start'] = value
            with self.assertRaises(ValueError):
                self.audit([bad])

    def test_nullable_unrelated_script_type_does_not_break_profile_audit(self):
        decisions = check_web(self.store, self.subject, self.save(prefix='<script type>unrelated</script>'))
        self.assertEqual(len(decisions), 1)
        self.audit(decisions)

    def test_enclosing_footer_role_cannot_be_lost_by_selecting_contact_div(self):
        from shirushi.html_sources import Sections
        for label in ('Customer', 'Our customers', 'Parent company', 'Subsidiary',
                      'This is not our legal identity:', 'Quoted record: "', "Quoted record: '",
                      'Quoted record: \u201c'):
            with self.subTest(label=label):
                footer = self.footer().replace('<footer>', '<footer><h2>' + label + '</h2>')
                sid = self.save(footer=footer)
                self.assertEqual(check_web(self.store, self.subject, sid), [])
                raw, _ = self.store.open(sid)
                contact = next(n for n in Sections(raw).nodes if n['tag'] == 'div')
                with patch('shirushi.profile_sources.contact_proof', return_value=contact):
                    forged = check_web(self.store, self.subject, sid)
                with self.assertRaises(ValueError):
                    self.audit(forged)

    def test_quoted_and_customer_containers_outside_footer_do_not_bind(self):
        from shirushi.html_sources import Sections
        for wrapper in ('<div>Quoted record: "{}</div>', '<section><h2>Customer</h2>{}</section>',
                        '<div><section><h2>Parent company</h2>{}</section></div>'):
            with self.subTest(wrapper=wrapper):
                sid = self.save(footer=wrapper.format(self.footer()))
                self.assertEqual(check_web(self.store, self.subject, sid), [])
                raw, _ = self.store.open(sid)
                contact = next(n for n in Sections(raw).nodes if n['tag'] == 'footer')
                with patch('shirushi.profile_sources.contact_proof', return_value=contact):
                    forged = check_web(self.store, self.subject, sid)
                with self.assertRaises(ValueError):
                    self.audit(forged)

    def test_closed_neutral_wrapper_is_retained_and_unclosed_wrapper_abstains(self):
        decisions = check_web(self.store, self.subject, self.save(footer='<div>Contact' + self.footer() + '</div>'))
        self.assertEqual(len(decisions), 1)
        self.assertTrue(decisions[0]['evidence']['support_spans']['legal_identity'].startswith('<div>Contact'))
        self.audit(decisions)
        self.assertEqual(check_web(self.store, self.subject, self.save(footer='<div>' + self.footer())), [])
