"""A definition names what the company is, not what it owns, rents, uses or belongs to."""
import unittest

from tests.test_business_statements import BusinessStatementTests


class StatementRelationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = BusinessStatementTests('values')
        self.fixture.setUp()
        self.addCleanup(self.fixture.temp.cleanup)

    def test_head_noun_must_directly_follow_adjectives_not_prepositions(self):
        for text in ('Example Pumps AS is a tenant of the manufacturer.',
                     'Example Pumps AS is a subscriber to the supplier network.',
                     'Example Pumps AS er en eier av pumpeselskap og vannverk i Bergen.',
                     'Example Pumps AS er en kjede for pumpeprodusenter og vannverk i Bergen.',
                     'Example Pumps AS er et medlem i pumpeforhandlerne og vannverkene.'):
            self.assertEqual(self.fixture.values(text), [], text)

    def test_adjectives_before_the_head_noun_still_qualify(self):
        for text in ('Example Pumps AS is a global industrial pump manufacturer in Norway.',
                     'Example Pumps AS er en ledende norsk pumpeprodusent for vannverk og industri.'):
            self.assertEqual([f for f, _ in self.fixture.values(text)], ['business_description'], text)


    def test_parent_company_and_subsidiary_company_headings_abstain(self):
        text = 'Example Pumps leverer pumper til vannverk og industri.'
        for label in ('Parent company', 'Subsidiary company', 'Group company', 'Customer company'):
            self.assertEqual(self.fixture.values(text, '<div><h3>' + label + '</h3><p>{}</p></div>'), [], label)


if __name__ == '__main__':
    unittest.main()
