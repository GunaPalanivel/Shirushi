"""Precision gates found by independent adjudication of the first replay: wording, page kind, relative clauses."""
import unittest

from tests.test_business_statements import BusinessStatementTests


def statement_methods(fixture, text, path='/about', wrapper='<div><p>{}</p></div>'):
    decisions = fixture.decisions(wrapper.format(text), path=path)
    return [d['evidence']['extraction_method'] for d in decisions]


class StatementPrecisionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = BusinessStatementTests('values')
        self.fixture.setUp()
        self.addCleanup(self.fixture.temp.cleanup)

    def abstains(self, text, path='/about'):
        self.assertNotIn('registry_linked_business_statement_v1', statement_methods(self.fixture, text, path), text)

    def test_marketing_adjectives_and_weak_nouns_are_not_a_concrete_offering(self):
        for text in ('Example Pumps tilbyr nøye utvalgte produkter fra ledende globale leverandører.',
                     'Example Pumps tilbyr individuelt tilpasset, løsningsrettet bistand til deltaker.',
                     'Example Pumps leverer innovative og skreddersydde løsninger av høy kvalitet.',
                     'Example Pumps offers carefully selected products from leading global suppliers.'):
            self.abstains(text)

    def test_vague_definition_with_a_relative_clause_abstains(self):
        self.abstains('Example Pumps er et dedikert ekspertteam som følger deg hele veien fra første skisse til drift.')

    def test_definition_relative_clause_with_a_provider_verb_still_qualifies(self):
        text = 'Example Pumps AS er en familiedrevet bedrift som tilbyr en rekke tjenester innenfor pumpeservice og vannforsyning.'
        self.assertEqual([f for f, _ in self.fixture.values(text)], ['business_description'])

    def test_privacy_legal_job_and_news_pages_are_not_business_description_pages(self):
        text = 'Example Pumps tilbyr rollestyring slik at kun utvalgte personer kan endre pumpedata og vannmålere.'
        for path in ('/personvern', '/personvernerklaering', '/privacy-policy', '/cookies', '/vilkar', '/salgsbetingelser',
                     '/terms-and-conditions', '/jobb', '/ledige-stillinger', '/karriere/montor', '/careers', '/aktuelt',
                     '/nyheter/2023/ny-pumpe', '/news', '/blogg/pumper', '/presse'):
            self.abstains(text, path)

    def test_ordinary_company_pages_still_qualify(self):
        text = 'Example Pumps leverer dokumenterte pumper, teknisk støtte og vedlikehold innen vannforsyning.'
        for path in ('/', '/about', '/om-oss', '/tjenester', '/produkter/pumper', '/en/about-us'):
            self.assertEqual(self.fixture.values(text, path=path), [('product_service', text)], path)

    def test_hyphenated_word_in_a_path_is_not_a_page_kind(self):
        text = 'Example Pumps leverer dokumenterte pumper, teknisk støtte og vedlikehold innen vannforsyning.'
        for path in ('/newsletter-pumper', '/jobbe-med-pumper-og-vann'):
            self.assertEqual(self.fixture.values(text, path=path), [('product_service', text)], path)


class TradeNameTests(unittest.TestCase):
    def fixture_for(self, company_name):
        fixture = BusinessStatementTests('values')
        fixture.company_name = company_name
        fixture.setUp()
        self.addCleanup(fixture.temp.cleanup)
        return fixture

    def test_only_one_legal_form_token_is_removed_and_only_a_trailing_one(self):
        fixture = self.fixture_for('BA FASHION AS')
        text = 'Fashion leverer damekolleksjoner og tilbehør til butikker.'
        methods = [d['evidence']['extraction_method'] for d in fixture.decisions('<div><p>' + text + '</p></div>')]
        self.assertNotIn('registry_linked_business_statement_v1', methods)
        own = 'BA Fashion leverer damekolleksjoner og tilbehør til butikker.'
        self.assertEqual(fixture.values(own), [('product_service', own)])

    def test_leading_as_prefix_names_are_still_bound_by_their_trade_name(self):
        fixture = self.fixture_for('AS SOLREGN')
        text = 'Solregn leverer solcelleanlegg og vedlikehold til bolig og næring.'
        self.assertEqual(fixture.values(text), [('product_service', text)])

    def test_mixed_case_words_that_look_like_legal_forms_are_names(self):
        fixture = self.fixture_for('Da Vinci Pumps AS')
        text = 'Vinci Pumps leverer pumper og systemer til vannverk og industri.'
        methods = [d['evidence']['extraction_method'] for d in fixture.decisions('<div><p>' + text + '</p></div>')]
        self.assertNotIn('registry_linked_business_statement_v1', methods)


if __name__ == '__main__':
    unittest.main()
