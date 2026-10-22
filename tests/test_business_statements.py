"""Company-led business statements on a registry-linked website."""
import json
import tempfile
import unittest
from pathlib import Path

from shirushi.snapshots import SnapshotStore, digest
from shirushi.web_sources import check_web


class BusinessStatementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(Path(self.temp.name))
        self.subject, self.name = '923609016', getattr(self, 'company_name', 'Example Pumps AS')
        raw = json.dumps({'organisasjonsnummer': self.subject, 'navn': self.name,
                          'hjemmeside': 'example.com'}).encode()
        self.anchor = self.store.save(raw, dict(organisation_number=self.subject, source_class='brreg_entity',
            source_url='https://data.brreg.no/enhetsregisteret/api/enheter/' + self.subject,
            http_status=200, sha256=digest(raw), retrieved_at='2026-10-10T08:00:00Z'))

    def decisions(self, html, host='example.com', path='/about'):
        raw = html.encode()
        sid = self.store.save(raw, dict(organisation_number=self.subject, source_class='company_owned',
            source_url='https://' + host + path, effective_url='https://' + host + path,
            http_status=200, sha256=digest(raw), declared_host=host, source_origin=host,
            robots_checked=True, retrieved_at='2026-10-10T08:00:00Z', ownership_anchor_snapshot_id=self.anchor))
        return check_web(self.store, self.subject, sid)

    def values(self, paragraph, wrapper='<div><p>{}</p></div>', path='/about'):
        return [(d['field'], d['claim']['value']) for d in self.decisions(wrapper.format(paragraph), path=path)]

    def test_legal_name_with_working_verb_publishes_first_sentence(self):
        text = 'Example Pumps AS arbeider hovedsaklig med levering, installasjon og service av pumper og kompressorer til industri.'
        self.assertEqual(self.values(text + ' Vi har verksted i Bergen.'), [('product_service', text)])

    def test_trade_name_without_legal_form_is_bound_on_the_registered_host(self):
        text = 'Example Pumps leverer dokumenterte pumper, teknisk støtte og vedlikehold innen vannforsyning.'
        self.assertEqual(self.values(text), [('product_service', text)])

    def test_definition_with_compound_business_noun(self):
        text = 'Example Pumps AS er en velkjent kvalitetsleverandør av industripumper i Norge.'
        self.assertEqual(self.values(text), [('business_description', text)])

    def test_cumulative_history_with_since_year_and_product(self):
        text = 'EXAMPLE PUMPS AS har siden 1989 produsert over 240 kundetilpassede pumper i rustfritt stål.'
        self.assertEqual(self.values(text), [('product_service', text)])

    def test_definition_complement_may_contain_ordinary_coordination(self):
        text = 'Example Pumps AS er et sammensveiset pumpeteam med 5 faglærte montører og en driftsleder.'
        self.assertEqual(self.values(text), [('business_description', text)])

    def test_sentence_split_does_not_truncate_at_initials(self):
        text = 'Example Pumps lager pumper og systemer for kunder som Bertel O. Steen og Eplehuset.'
        self.assertEqual(self.values(text), [('product_service', text)])

    def test_statement_requires_the_registered_host(self):
        with self.assertRaises(ValueError):
            self.decisions('<p>Example Pumps leverer pumper til vannverk og industri.</p>', host='other.example.org')

    def test_trade_name_must_be_followed_by_the_predicate(self):
        for text in ('Example Pumps Norge leverer pumper til vannverk og industri.',
                     'Hos Example Pumps leverer vi pumper til vannverk og industri.',
                     'Vi leverer pumper til vannverk og industri.',
                     'Pumpene fra Example Pumps leverer vann til industri og vannverk.'):
            self.assertEqual(self.values(text), [], text)

    def test_generic_statements_without_concrete_offering_abstain(self):
        # The older exact-legal-name route is measured separately; this route must not add generic claims.
        for text in ('Example Pumps AS leverer flere tjenester til sine kunder, leverandører og samarbeidspartnere.',
                     'Example Pumps leverer høy kvalitet til våre kunder.',
                     'Example Pumps AS er et selskap.',
                     'Example Pumps AS tilbyr ulike løsninger.'):
            methods = [d['evidence']['extraction_method'] for d in self.decisions('<div><p>' + text + '</p></div>')]
            self.assertNotIn('registry_linked_business_statement_v1', methods, text)

    def test_group_parent_customer_and_other_entity_contexts_abstain(self):
        for text in ('Example Pumps er et konsern av spesialiserte virksomheter innen vannforsyning og industri.',
                     'Example Pumps leverer pumper til Other Pumps AS og vannverk i Bergen.',
                     'Example Pumps leverer pumper til datterselskapet og vannverk i Bergen.',
                     'Example Pumps AS er et datterselskap innen pumpeproduksjon og vannforsyning.',
                     'Kunden sier at Example Pumps leverer pumper til vannverk og industri.'):
            self.assertEqual(self.values(text), [], text)

    def test_negated_conditional_quoted_and_questioning_statements_abstain(self):
        for text in ('Example Pumps leverer ikke pumper til vannverk og industri.',
                     'Hvis Example Pumps leverer pumper til vannverk, ringer vi deg.',
                     'Leverer Example Pumps pumper til vannverk og industri?',
                     'Example Pumps leverer pumper: vannverk, industri og kommuner.',
                     'Example Pumps leverer pumper til vannverk, men Rival leverer pumper til industri.'):
            self.assertEqual(self.values(text), [], text)

    def test_membership_events_and_history_are_not_business_statements(self):
        for text in ('Example Pumps er stolt medlem av Norges største pumpekjede, PUMPEPROFFEN.',
                     'Example Pumps har levert en stor pumpepakke til Vitusapotek i Bergen.',
                     'Example Pumps AS søker nå flere dyktige medarbeidere til pumpeverkstedet.',
                     'Example Pumps AS har i rapporteringsperioden gjennomført aktsomhetsvurderinger av pumpeleverandører.'):
            self.assertEqual(self.values(text), [], text)

    def test_quoted_hypothetical_and_customer_containers_abstain(self):
        text = 'Example Pumps leverer pumper til vannverk og industri.'
        for wrapper in ('<blockquote><p>{}</p></blockquote>',
                        '<div>«demo»<p>{}</p></div>',
                        '<div><h3>Our customer story</h3><p>{}</p></div>',
                        '<div><h3>Hypothetical scenario</h3><p>{}</p></div>',
                        '<div style="display:none"><p>{}</p></div>'):
            self.assertEqual(self.values(text, wrapper), [], wrapper)

    def test_quote_characters_in_enclosing_text_abstain(self):
        text = 'Example Pumps leverer pumper til vannverk og industri.'
        filler = '<p>' + 'x' * 3100 + '</p>'
        for wrapper in ('<div>“demo” <p>{}</p></div>',
                        '<div>say "demo" <p>{}</p></div>',
                        "<div>' demo <p>{}</p></div>",
                        '<div>«demo»<div><p>{}</p></div></div>',
                        '<div>«demo»' + filler + '<div><p>{}</p></div></div>'):
            self.assertEqual(self.values(text, wrapper), [], wrapper)

    def test_hypothetical_wording_before_the_paragraph_abstains(self):
        text = 'Example Pumps leverer pumper til vannverk og industri.'
        # Loose text in the container is only seen by the preceding-text check.
        for word in ('hypothetical', 'scenario', 'imagine', 'suppose', 'forestill', 'false', 'fake', 'denied',
                     'benektet', 'usant', 'falsk'):
            self.assertEqual(self.values(text, '<div>' + word + ' <p>{}</p></div>'), [], word)
        # A heading is also seen as a label; the duplicated text before it blinds the preceding-text check.
        for word in ('hypothetical', 'scenario', 'false', 'fake', 'denied', 'benektet', 'usant', 'falsk'):
            self.assertEqual(self.values(text, '<div><span>' + text + '</span><h3>' + word + '</h3><p>{}</p></div>'),
                             [], word)
        for wrapper in ('<div>Imagine this <p>{}</p></div>',
                        '<div>Suppose that <p>{}</p></div>',
                        '<div>Denied: <span>x</span><p>{}</p></div>',
                        '<div><h3>Hypothetical scenario</h3><p>{}</p></div>',
                        '<div><span>' + text + '</span><h3>Hypothetical scenario</h3><p>{}</p></div>'):
            self.assertEqual(self.values(text, wrapper), [], wrapper)

    def test_customer_parent_group_and_speaker_labels_abstain(self):
        text = 'Example Pumps leverer pumper til vannverk og industri.'
        for label in ('Our customer story', 'Customer', 'Våre kunder', 'This is a quote', 'Quote', 'Speaker',
                      'Parent', 'Subsidiary structure', 'Group', 'The group:', 'Gruppen', 'Konsernstruktur'):
            self.assertEqual(self.values(text, '<div><h3>' + label + '</h3><p>{}</p></div>'), [], label)
        for wrapper in ('<div><span>Customer</span><p>{}</p></div>',
                        '<section><h2>Customer story</h2><div><p>{}</p></div></section>',
                        '<article><h3>Group</h3><p>{}</p></article>'):
            self.assertEqual(self.values(text, wrapper), [], wrapper)
        for label in ('A customer', 'Clients', 'Kundehistorie', 'Subsidiaries', 'Quoted'):
            self.assertEqual(self.values(text, '<div><h3>' + label + '</h3><p>{}</p></div>'), [], label)
        for suffix in ('story', 'record', 'case', 'example', 'profile', 'testimonial', 'context', 'description',
                       'scenario', 'statement', 'interview', 'services', 'activities', 'companies', 'structure',
                       'information', 'news'):
            self.assertEqual(self.values(text, '<div><h3>Customer ' + suffix + '</h3><p>{}</p></div>'), [], suffix)

    def test_labels_of_unrelated_earlier_containers_do_not_block(self):
        text = 'Example Pumps leverer pumper til vannverk og industri.'
        wrapper = '<div>«demo»</div><div><h3>Group</h3><p>Other text here.</p></div><div><p>{}</p></div>'
        self.assertEqual(self.values(text, wrapper), [('product_service', text)])

    def test_paragraph_needs_a_bounded_container_when_nested(self):
        text = 'Example Pumps leverer pumper til vannverk og industri.'
        filler = '<p>' + 'x' * 3100 + '</p>'
        for wrapper in ('<div>' + filler + '<p>{}</p></div>',
                        '<div>' + filler + '<div>' + filler + '<p>{}</p></div></div>',
                        '<span><p>{}</p></span>',
                        '<ul><li><p>{}</p></li></ul>',
                        '<main><p>{}</p></main>'):
            self.assertEqual(self.values(text, wrapper), [], wrapper[:40])
        for wrapper in ('<p>{}</p>', '<html><body><p>{}</p></body></html>'):
            self.assertEqual(self.values(text, wrapper), [('product_service', text)], wrapper)

    def test_container_is_bounded_at_3000_characters(self):
        text = 'Example Pumps leverer pumper til vannverk og industri.'
        for size, expected in ((3000, [('product_service', text)]), (3001, [])):
            filler = 'x' * (size - len(text) - 1)
            self.assertEqual(self.values(text, '<div><p>' + filler + '</p> <p>{}</p></div>'), expected, size)

    def test_deeply_nested_paragraph_uses_the_smallest_bounded_container(self):
        text = 'Example Pumps leverer pumper til vannverk og industri.'
        html = '<div><div><section><div><ul><li><p>' + text + '</p></li></ul></div></section></div></div>'
        decision = self.decisions(html)[0]
        inner = '<div><ul><li><p>' + text + '</p></li></ul></div>'
        self.assertEqual(decision['claim']['value'], text)
        self.assertEqual(decision['evidence']['support_spans']['section_context'], inner)
        self.assertEqual(self.values(text, '<div><div><div><div><p>{}</p></div></div></div></div>'),
                         [('product_service', text)])
        for tag in ('section', 'article'):
            html = '<div><' + tag + '><p>' + text + '</p></' + tag + '></div>'
            self.assertEqual(self.decisions(html)[0]['evidence']['support_spans']['section_context'],
                             '<' + tag + '><p>' + text + '</p></' + tag + '>', tag)

    def test_definition_allows_at_most_three_modifiers(self):
        for text, expected in (
                ('Example Pumps AS er en norsk lokal erfaren leverandør av industripumper og kompressorer.', True),
                ('Example Pumps AS er en ny stor lokal norsk leverandør av industripumper og kompressorer.', False),
                ('Example Pumps AS is a leading local trusted provider of industrial pumps and compressors.', True),
                ('Example Pumps AS is a very large well known provider of industrial pumps and compressors.', False)):
            self.assertEqual(self.values(text), [('business_description', text)] if expected else [], text)

    def test_definition_modifiers_are_adjectives_not_relations(self):
        self.assertEqual(self.values('Example Pumps AS is an experienced provider of industrial pumps and compressors.'),
                         [('business_description',
                           'Example Pumps AS is an experienced provider of industrial pumps and compressors.')])
        for word in ('of', 'the', 'a', 'an', 'for', 'to', 'in', 'at', 'on', 'with', 'by', 'from', 'and', 'or', 'av',
                     'til', 'i', 'på', 'med', 'fra', 'den', 'det', 'de', 'en', 'et', 'ett', 'og', 'eller'):
            for text in ('Example Pumps AS er en eier ' + word + ' produsent av industripumper og kompressorer.',
                         'Example Pumps AS is a tenant ' + word + ' supplier of industrial pumps and compressors.'):
                self.assertEqual(self.values(text), [], text)

    def test_sentence_split_does_not_truncate_at_dotted_abbreviations(self):
        text = 'Example Pumps lager pumper og systemer for kunder som N.K. Hansen og Eplehuset.'
        self.assertEqual(self.values(text), [('product_service', text)])

    def test_existing_routes_keep_priority_and_values(self):
        pair = ('<div><p>Meet Jane Doe, leader for Example Pumps AS.</p>'
                '<p>We supply industrial pumps and maintenance.</p></div>')
        decisions = self.decisions(pair + '<p>Example Pumps leverer pumper til vannverk og industri.</p>')
        self.assertEqual([(d['field'], d['evidence']['extraction_method']) for d in decisions],
                         [('product_service', 'bounded_company_section_v1')])

    def test_evidence_identifies_the_paragraph_sentence_and_method(self):
        text = 'Example Pumps AS arbeider med service av pumper og kompressorer til industri.'
        decision = self.decisions('<div><p>' + text + ' Vi har verksted.</p></div>')[0]
        self.assertEqual(decision['evidence']['extraction_method'], 'registry_linked_business_statement_v1')
        self.assertEqual(decision['claim']['scope'], 'registry_linked_html')
        self.assertIn(text + ' Vi har verksted.', decision['evidence']['claim_span'])
        self.assertIn('section_context', decision['evidence']['support_spans'])


if __name__ == '__main__':
    unittest.main()
