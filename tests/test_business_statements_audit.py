"""Independent audit of registry-linked business statements and forged claims."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from shirushi.snapshots import SnapshotStore, digest
from shirushi.web_sources import check_web
from shirushi_eval.html_support import document
from shirushi_eval.support import SourceAudit

METHOD = 'registry_linked_business_statement_v1'


class BusinessStatementAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(Path(self.temp.name))
        self.subject = '923609016'
        self.use_name('Example Pumps AS')

    def use_name(self, name):
        raw = json.dumps({'organisasjonsnummer': self.subject, 'navn': name,
                          'hjemmeside': 'example.com'}).encode()
        self.anchor = self.store.save(raw, dict(organisation_number=self.subject, source_class='brreg_entity',
            source_url='https://data.brreg.no/enhetsregisteret/api/enheter/' + self.subject,
            http_status=200, sha256=digest(raw), retrieved_at='2026-10-10T08:00:00Z'))

    def decisions(self, html, path='/about'):
        raw = html.encode()
        sid = self.store.save(raw, dict(organisation_number=self.subject, source_class='company_owned',
            source_url='https://example.com' + path, effective_url='https://example.com' + path,
            http_status=200, sha256=digest(raw), declared_host='example.com', source_origin='example.com',
            robots_checked=True, retrieved_at='2026-10-10T08:00:00Z', ownership_anchor_snapshot_id=self.anchor))
        self.page_sid = sid
        return check_web(self.store, self.subject, sid)

    def audit(self, decisions):
        audit = SourceAudit(self.store.root, [self.subject])
        for decision in decisions:
            audit.claim(self.subject, decision['claim'], {decision['evidence']['id']: decision['evidence']})

    def published(self, html):
        decisions = self.decisions(html)
        self.assertEqual(len(decisions), 1, html)
        self.assertEqual(decisions[0]['evidence']['extraction_method'], METHOD)
        return decisions[0]

    def identity(self, decision, field, value):
        key = None if field == 'business_description' else hashlib.sha256(value.encode()).hexdigest()
        encoded = json.dumps([self.subject, field, 'registry_linked_html', key, None], ensure_ascii=False,
                             sort_keys=True, separators=(',', ':')).encode()
        decision['claim'].update(value=value, field=field, item_key=key, claim_id=hashlib.sha256(encoded).hexdigest())

    def forged(self, base, html, value, field='product_service', path='/about'):
        """Point a genuine decision at another page and recompute its identity."""
        forged = copy.deepcopy(self.published(base))
        self.decisions(html, path)
        raw, _ = self.store.open(self.page_sid)
        page = document(raw)
        paragraph = next(n for n in page.nodes if n['tag'] == 'p')
        parents = [n for n in page.nodes if n['tag'] in ('div', 'section', 'article')
                   and n['start'] < paragraph['start'] and paragraph['end'] < n['end'] and len(n['text']) <= 3000]
        item = forged['evidence']
        item.update(snapshot_id=self.page_sid, content_sha256=digest(raw), source_url='https://example.com' + path,
                    claim_span=page.source[paragraph['start']:paragraph['end']])
        item['locator'] = dict(html_start=paragraph['start'], html_end=paragraph['end'])
        item['support_spans'] = {}
        if parents:
            context = min(parents, key=lambda n: n['end'] - n['start'])
            item['locator'].update(container_start=context['start'], container_end=context['end'])
            item['support_spans'] = {'section_context': page.source[context['start']:context['end']]}
        self.identity(forged, field, value)
        return forged

    def rejects(self, forged, message=None):
        with self.assertRaisesRegex(ValueError, message or 'Audit'):
            self.audit([forged])

    ACTIVITY = 'Example Pumps leverer dokumenterte pumper, teknisk støtte og vedlikehold innen vannforsyning.'
    DEFINITION = 'Example Pumps AS er en velkjent kvalitetsleverandør av industripumper i Norge.'

    def test_auditor_agrees_with_published_statements(self):
        for html in ('<div><p>Example Pumps AS arbeider hovedsaklig med levering, installasjon og service av pumper og kompressorer til industri. Vi har verksted i Bergen.</p></div>',
                     '<div><p>' + self.ACTIVITY + '</p></div>',
                     '<p>' + self.ACTIVITY + '</p>',
                     '<section><div><p>' + self.ACTIVITY + '</p></div></section>',
                     '<div><p>' + self.DEFINITION + '</p></div>',
                     '<div><p>EXAMPLE PUMPS AS har siden 1989 produsert over 240 kundetilpassede pumper i rustfritt stål.</p></div>',
                     '<div><p>Example Pumps AS er et sammensveiset pumpeteam med 5 faglaerte montorer og en driftsleder.</p></div>',
                     '<div><p>Example Pumps lager pumper og systemer for kunder som Bertel O. Steen og Eplehuset.</p></div>'):
            self.audit([self.published(html)])

    def test_field_and_key_follow_the_sentence_type(self):
        activity, definition = self.published('<p>' + self.ACTIVITY + '</p>'), self.published('<p>' + self.DEFINITION + '</p>')
        self.assertEqual((activity['claim']['field'], definition['claim']['field']), ('product_service', 'business_description'))
        for decision, field, value in ((activity, 'business_description', self.ACTIVITY),
                                       (definition, 'product_service', self.DEFINITION)):
            forged = copy.deepcopy(decision)
            self.identity(forged, field, value)
            self.rejects(forged, 'value or identity')
        forged = copy.deepcopy(activity)
        forged['claim']['item_key'] = None
        self.rejects(forged, 'value or identity')
        forged = copy.deepcopy(definition)
        forged['claim']['item_key'] = hashlib.sha256(self.DEFINITION.encode()).hexdigest()
        self.rejects(forged, 'value or identity')

    def test_scope_family_and_period_cannot_be_changed(self):
        for change in ({'scope': 'company_owned_html'}, {'family': 'jobs_dated_activity'}, {'period': '2025'}):
            forged = copy.deepcopy(self.published('<p>' + self.ACTIVITY + '</p>'))
            forged['claim'].update(change)
            self.rejects(forged, 'value or identity')

    def test_value_must_be_the_first_qualifying_sentence(self):
        first = 'Example Pumps leverer dokumenterte pumper og teknisk støtte.'
        second = 'Example Pumps AS bygger rustfrie ventiler og armaturer.'
        base = '<div><p>' + first + ' ' + second + '</p></div>'
        self.assertEqual(self.published(base)['claim']['value'], first)
        forged = copy.deepcopy(self.published(base))
        self.identity(forged, 'product_service', second)
        self.rejects(forged, 'first qualifying')
        forged = copy.deepcopy(self.published(base))
        self.identity(forged, 'product_service', first + ' ' + second)
        self.rejects(forged, 'paragraph sentence')

    def test_value_must_be_a_sentence_of_the_paragraph(self):
        for value in ('Example Pumps leverer gull og diamanter til alle vannverk.',
                      'Example Pumps leverer dokumenterte pumper, teknisk',
                      'leverer dokumenterte pumper, teknisk støtte og vedlikehold innen vannforsyning.'):
            forged = copy.deepcopy(self.published('<p>' + self.ACTIVITY + '</p>'))
            self.identity(forged, 'product_service', value)
            self.rejects(forged, 'paragraph sentence')

    def test_sentence_after_a_non_qualifying_sentence_is_not_first(self):
        base = ('<div><p>' + self.ACTIVITY + ' Example Pumps leverer også mange ulike kunder.</p></div>')
        self.audit([self.published(base)])
        later = 'Example Pumps AS leverer pumper og ventiler til industribedrifter.'
        forged = self.forged(base, '<div><p>' + self.ACTIVITY + ' ' + later + '</p></div>', later)
        self.rejects(forged, 'first qualifying')

    def test_locator_must_name_the_paragraph_and_its_container(self):
        original = self.published('<div><p>' + self.ACTIVITY + '</p></div>')
        for key, delta in (('html_start', 1), ('html_end', -1), ('container_start', 1), ('container_end', -1)):
            forged = copy.deepcopy(original)
            forged['evidence']['locator'][key] += delta
            self.rejects(forged)
        forged = copy.deepcopy(original)
        del forged['evidence']['locator']['container_start'], forged['evidence']['locator']['container_end']
        self.rejects(forged, 'section locator')
        forged = copy.deepcopy(original)
        forged['evidence']['locator']['html_start'] = 'x'
        self.rejects(forged, 'locator type')

    def test_locator_has_no_other_keys_and_container_keys_only_with_a_container(self):
        for html in ('<div><p>' + self.ACTIVITY + '</p></div>', '<p>' + self.ACTIVITY + '</p>'):
            forged = copy.deepcopy(self.published(html))
            forged['evidence']['locator']['legal_name'] = 'Example Pumps AS'
            self.rejects(forged, 'locator keys')
        forged = copy.deepcopy(self.published('<p>' + self.ACTIVITY + '</p>'))
        forged['evidence']['locator'].update(container_start=0, container_end=1)
        self.rejects(forged, 'locator keys')

    def test_claim_span_must_be_the_whole_paragraph(self):
        original = self.published('<div><p>' + self.ACTIVITY + ' Vi har verksted.</p></div>')
        forged = copy.deepcopy(original)
        forged['evidence']['claim_span'] = self.ACTIVITY
        self.rejects(forged)

    def test_support_spans_must_be_exactly_the_container(self):
        original = self.published('<div><p>' + self.ACTIVITY + '</p></div>')
        self.assertEqual(list(original['evidence']['support_spans']), ['section_context'])
        for spans in ({}, {'section_context': '<div></div>'}, {'subject_context': '<p>Example Pumps AS</p>'},
                      dict(original['evidence']['support_spans'], subject_context='<p>Example Pumps AS</p>')):
            forged = copy.deepcopy(original)
            forged['evidence']['support_spans'] = spans
            self.rejects(forged, 'support mismatch')
        bare = self.published('<p>' + self.ACTIVITY + '</p>')
        self.assertEqual(bare['evidence']['support_spans'], {})
        forged = copy.deepcopy(bare)
        forged['evidence']['support_spans'] = {'section_context': '<div></div>'}
        self.rejects(forged, 'support mismatch')

    def test_method_downgrade_is_not_accepted_by_another_route(self):
        for html in ('<div><p>' + self.ACTIVITY + '</p></div>', '<div><p>' + self.DEFINITION + '</p></div>'):
            for method in ('named_company_definition_v1', 'bounded_company_section_v1', 'registry_linked_subject_html_v1',
                           'explicit_subject_html_v1'):
                forged = copy.deepcopy(self.published(html))
                forged['evidence']['extraction_method'] = method
                self.rejects(forged)

    def test_published_sentences_must_name_the_registered_subject(self):
        base = '<div><p>' + self.ACTIVITY + '</p></div>'
        for text in ('Example Pumps Norge leverer pumper til vannverk og industri.',
                     'Hos Example Pumps leverer vi pumper til vannverk og industri.',
                     'Vi leverer pumper til vannverk og industri.',
                     'Pumpene fra Example Pumps leverer vann til industri og vannverk.',
                     'Rival Pumps AS leverer pumper til vannverk og industri.',
                     'Example Pumpsen leverer pumper til vannverk og industri.',
                     'Example Pumps, leverer pumper til vannverk og industri.',
                     'Example Pumps AS Holding er et pumpeselskap for vannverk.',
                     'Example leverer pumper til vannverk og industri.'):
            self.rejects(self.forged(base, '<div><p>' + text + '</p></div>', text), 'business')

    def test_trade_name_needs_four_characters_and_a_removable_legal_form(self):
        self.use_name('Abc Pumper AS')
        base = self.published('<div><p>Abc Pumper leverer rustfrie pumper og ventiler.</p></div>')
        self.audit([base])
        text = 'Abc leverer rustfrie pumper og ventiler.'
        self.rejects(self.forged('<div><p>Abc Pumper leverer rustfrie pumper og ventiler.</p></div>',
                                 '<div><p>' + text + '</p></div>', text), 'business')
        self.use_name('Abc AS')
        text = 'Abc leverer rustfrie pumper og ventiler.'
        text = 'Abc bygger rustfrie pumper og ventiler.'
        self.rejects(self.forged('<div><p>Abc AS bygger rustfrie pumper og ventiler.</p></div>',
                                 '<div><p>' + text + '</p></div>', text), 'business')
        self.use_name('AS Pumpeservice')
        self.audit([self.published('<div><p>Pumpeservice leverer rustfrie pumper og ventiler.</p></div>')])

    def test_rejections_after_the_subject_hold_in_the_auditor(self):
        base = '<div><p>' + self.ACTIVITY + '</p></div>'
        for text in ('Example Pumps leverer ikke pumper til vannverk og industri.',
                     'Example Pumps leverer pumper til vannverk og aldri til industri.',
                     'Example Pumps leverer pumper: vannverk, industri og kommuner.',
                     'Example Pumps leverer pumper; vannverk, industri og kommuner.',
                     'Example Pumps leverer pumper til vannverk, men Rival leverer pumper til industri.',
                     'Example Pumps leverer pumper til vannverk, fordi industri kjøper dem.',
                     'Example Pumps leverer pumper til datterselskapet og vannverk i Bergen.',
                     'Example Pumps leverer pumper til morselskapets vannverk i Bergen.',
                     'Example Pumps leverer pumper til konsernets vannverk i Bergen.',
                     'Example Pumps leverer pumper til medlemmer og vannverk i Bergen.',
                     'Example Pumps leverer pumper som del av vannverk og industri.',
                     'Example Pumps leverer pumper til partner og vannverk i Bergen.',
                     'Example Pumps leverer pumper til example vannverk i Bergen.',
                     'Example Pumps leverer pumper til joke vannverk i Bergen.',
                     'Example Pumps leverer pumper til customer vannverk i Bergen.',
                     'Example Pumps leverer pumper til Other Pumps AS og vannverk i Bergen.',
                     'Example Pumps leverer pumper til Rival Ltd og vannverk i Bergen.',
                     'Example Pumps leverer pumper «til vannverk» og industri.',
                     'Example Pumps leverer pumper "til vannverk" og industri.',
                     'Example Pumps leverer pumper “til vannverk” og industri.',
                     "Example Pumps leverer pumper 'til vannverk' og industri.",
                     'Example Pumps leverer pumper til vannverk og industri, sier kunden.'):
            self.rejects(self.forged(base, '<div><p>' + text + '</p></div>', text), 'business|identifier')

    def test_competing_organisation_numbers_are_rejected(self):
        base = '<div><p>' + self.ACTIVITY + '</p></div>'
        text = 'Example Pumps leverer pumper og ventiler org nr 999 999 999 til vannverk.'
        self.rejects(self.forged(base, '<div><p>' + text + '</p></div>', text), 'identifier')

    def test_paragraph_denials_and_hypotheticals_reject_every_sentence(self):
        base = '<div><p>' + self.ACTIVITY + '</p></div>'
        for tail in ('Dette er false.', 'Et fake scenario.', 'Notatet ble benektet.', 'Det var usant.', 'En hypothetical case.'):
            html = '<div><p>' + self.ACTIVITY + ' ' + tail + '</p></div>'
            self.assertEqual(self.decisions(html), [], tail)
            self.rejects(self.forged(base, html, self.ACTIVITY), 'business')

    def test_concrete_offering_needs_two_specific_words(self):
        base = '<div><p>' + self.ACTIVITY + '</p></div>'
        for text in ('Example Pumps AS leverer flere tjenester til sine kunder, leverandører og samarbeidspartnere.',
                     'Example Pumps leverer høy kvalitet til våre kunder.',
                     'Example Pumps leverer også pumper.',
                     'Example Pumps AS tilbyr ulike løsninger.',
                     'Example Pumps AS er et selskap.',
                     'Example Pumps AS er en bedrift.'):
            field = 'business_description' if ' er ' in text else 'product_service'
            self.rejects(self.forged(base, '<div><p>' + text + '</p></div>', text, field), 'business')

    def test_non_business_definitions_and_history_are_rejected(self):
        base = '<div><p>' + self.DEFINITION + '</p></div>'
        for text in ('Example Pumps er stolt medlem av Norges største pumpekjede.',
                     'Example Pumps AS er et datterselskap innen pumpeproduksjon og vannforsyning.',
                     'Example Pumps er et konsern av spesialiserte virksomheter innen vannforsyning.',
                     'Example Pumps AS er en velkjent kvalitetsleverandør av industripumper i Norge, men Rival også.',
                     'Example Pumps AS har levert en stor pumpepakke til Vitusapotek i Bergen.',
                     'Example Pumps AS søker nå flere dyktige medarbeidere til pumpeverkstedet.'):
            self.rejects(self.forged(base, '<div><p>' + text + '</p></div>', text,
                                     'business_description'), 'business')

    def test_definition_modifiers_are_not_function_words(self):
        base = '<div><p>' + self.DEFINITION + '</p></div>'
        for text in ('Example Pumps AS is a tenant of the manufacturer.',
                     'Example Pumps AS is a subscriber to the supplier network.',
                     'Example Pumps AS er en eier av pumpeselskap og vannverk i Bergen.',
                     'Example Pumps AS er en kjede for pumpeprodusenter og vannverk i Bergen.',
                     'Example Pumps AS er en eier og pumpeselskap for vannverk i Bergen.',
                     'Example Pumps AS is a seller or global pump manufacturer in Norway.',
                     'Example Pumps AS er et medlem i pumpeforhandlerne og vannverkene.'):
            self.rejects(self.forged(base, '<div><p>' + text + '</p></div>', text, 'business_description'), 'business')
        for text in ('Example Pumps AS is a global industrial pump manufacturer in Norway.',
                     'Example Pumps AS er en ledende norsk pumpeprodusent for vannverk og industri.'):
            self.audit([self.forged(base, '<div><p>' + text + '</p></div>', text, 'business_description')])

    def test_off_topic_page_paths_are_rejected_but_hyphenated_words_are_not(self):
        base = '<div><p>' + self.ACTIVITY + '</p></div>'
        for path in ('/personvern', '/personvernerklaering', '/privacy-policy', '/cookies', '/vilkar', '/salgsbetingelser',
                     '/terms-and-conditions', '/jobb', '/ledige-stillinger', '/karriere/montor', '/careers', '/aktuelt',
                     '/nyheter/2023/ny-pumpe', '/news', '/blogg/pumper', '/presse', '/om-oss/legal.html', '/%4Eews'):
            self.rejects(self.forged(base, base, self.ACTIVITY, path=path), 'page kind')
        for path in ('/', '/om-oss', '/produkter/pumper', '/en/about-us', '/newsletter-pumper', '/jobbe-med-pumper-og-vann'):
            self.audit([self.forged(base, base, self.ACTIVITY, path=path)])

    def test_definition_relative_clause_must_keep_the_subject(self):
        base = '<div><p>' + self.DEFINITION + '</p></div>'
        for text in ('Example Pumps er et dedikert ekspertteam som følger deg hele veien fra første skisse til drift.',
                     'Example Pumps AS er en pumpebedrift som kundene stoler på i hele Bergen.',
                     'Example Pumps AS is a pump manufacturer that Bergen relies on for water supply.',
                     'Example Pumps AS er en pumpebedrift som.'):
            self.rejects(self.forged(base, '<div><p>' + text + '</p></div>', text, 'business_description'), 'relative clause')
        text = 'Example Pumps AS er en familiedrevet bedrift som tilbyr en rekke tjenester innenfor pumpeservice og vannforsyning.'
        self.audit([self.forged(base, '<div><p>' + text + '</p></div>', text, 'business_description')])
        text = 'Example Pumps AS rehabiliterer pumper som kunder i Bergen eier og bruker daglig.'
        self.audit([self.forged('<div><p>' + self.ACTIVITY + '</p></div>', '<div><p>' + text + '</p></div>', text)])

    def test_marketing_adjectives_and_weak_nouns_are_not_a_concrete_offering(self):
        base = '<div><p>' + self.ACTIVITY + '</p></div>'
        for text in ('Example Pumps tilbyr nøye utvalgte produkter fra ledende globale leverandører.',
                     'Example Pumps tilbyr individuelt tilpasset, løsningsrettet bistand til deltaker.',
                     'Example Pumps leverer innovative og skreddersydde løsninger av høy kvalitet.',
                     'Example Pumps offers carefully selected products from leading global suppliers.'):
            self.rejects(self.forged(base, '<div><p>' + text + '</p></div>', text), 'concrete offering')

    def test_enclosing_context_labels_and_quotes_reject(self):
        base = '<div><p>' + self.ACTIVITY + '</p></div>'
        for html in ('<div>«demo»<p>{}</p></div>',
                     '<div><h3>Our customer story</h3><p>{}</p></div>',
                     '<div><h3>Hypothetical scenario</h3><p>{}</p></div>',
                     '<section><h2>Our group</h2><p>{}</p></section>',
                     '<div><h3>Parent company</h3><p>{}</p></div>',
                     '<div><h3>Subsidiary company</h3><p>{}</p></div>',
                     '<div><h3>Group company</h3><p>{}</p></div>',
                     '<div><h3>Customer company</h3><p>{}</p></div>',
                     '<section>Quoted record: "<div><p>{}</p></div>"</section>'):
            self.rejects(self.forged(base, html.format(self.ACTIVITY), self.ACTIVITY), 'context|speaker')

    def test_unbounded_container_is_rejected(self):
        base = '<div><p>' + self.ACTIVITY + '</p></div>'
        html = '<div><p>' + self.ACTIVITY + '</p>' + '<p>fyll</p>' * 800 + '</div>'
        forged = self.forged(base, html, self.ACTIVITY)
        self.rejects(forged, 'bounded context')

    def test_paragraph_length_bounds(self):
        base = '<div><p>' + self.ACTIVITY + '</p></div>'
        text = 'Example Pumps leverer pumper og ventiler til industri ' + 'og vannverk ' * 200 + '.'
        self.rejects(self.forged(base, '<div><p>' + text + '</p></div>', text), 'eligible paragraph')

    def test_sentence_split_keeps_initials_and_abbreviations(self):
        text = 'Example Pumps lager pumper og systemer for kunder som Bertel O. Steen og Eplehuset.'
        self.audit([self.published('<div><p>' + text + '</p></div>')])
        text = 'Example Pumps lager pumper og ventiler for U.S. kunder i Bergen.'
        self.audit([self.published('<div><p>' + text + ' Vi har verksted.</p></div>')])
        base = '<div><p>' + self.ACTIVITY + '</p></div>'
        forged = self.forged(base, '<div><p>' + text + ' Vi har verksted.</p></div>', 'Example Pumps lager pumper og ventiler for U.S.')
        self.rejects(forged, 'paragraph sentence')


if __name__ == '__main__':
    unittest.main()
