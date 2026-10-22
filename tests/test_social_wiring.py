"""Social profile claims published through check_web on anchored company pages."""
import unittest

from tests.test_business_statements import BusinessStatementTests


class SocialWiringTests(unittest.TestCase):
    def setUp(self):
        self.fixture = BusinessStatementTests('values')
        self.fixture.setUp()
        self.addCleanup(self.fixture.temp.cleanup)

    def page(self, links):
        return '<html><body><footer>' + ''.join('<a href="%s">x</a>' % link for link in links) + '</footer></body></html>'

    def social(self, links, host='example.com'):
        decisions = self.fixture.decisions(self.page(links), host=host)
        return [(d['claim']['value'], d['claim']['scope'], d['family'], d['evidence']['extraction_method'])
                for d in decisions if d['field'] == 'social_profile']

    def test_anchored_page_publishes_scalar_profile_claims_with_evidence(self):
        claims = self.social(['https://www.facebook.com/ExamplePumps/', 'https://www.linkedin.com/company/example-pumps-as?trk=x'])
        self.assertEqual(sorted(value for value, *_ in claims), ['facebook.com/examplepumps', 'linkedin.com/company/example-pumps-as'])
        for _, scope, family, method in claims:
            self.assertEqual((scope, family), ('registry_linked_html', 'website_owned_profiles'))
            self.assertTrue(method)

    def test_links_to_other_entities_and_share_buttons_are_not_published(self):
        self.assertEqual(self.social(['https://www.facebook.com/sharer/sharer.php?u=x', 'https://twitter.com/intent/tweet?text=x',
                                      'https://www.facebook.com/rivalcorp']), [])

    def test_unanchored_page_publishes_nothing(self):
        with self.assertRaises(ValueError):
            self.fixture.decisions(self.page(['https://www.facebook.com/examplepumps']), host='other.example.org')

    def test_decisions_carry_the_claim_evidence_shape(self):
        decision = [d for d in self.fixture.decisions(self.page(['https://www.facebook.com/examplepumps']))
                    if d['field'] == 'social_profile'][0]
        self.assertEqual(decision['claim']['item_key'], decision['claim']['value'])
        self.assertIn(decision['claim']['claim_id'] and decision['evidence']['id'], decision['claim']['evidence_ids'])
        self.assertTrue(decision['evidence']['claim_span'])


    def test_a_social_link_alone_does_not_cover_the_website_family(self):
        from shirushi.live import covered_families
        claims = [{'availability': 'available', 'field': 'social_profile', 'family': 'website_owned_profiles'}]
        self.assertEqual(covered_families(claims), set())
        claims.append({'availability': 'available', 'field': 'verified_website', 'family': 'website_owned_profiles'})
        self.assertEqual(covered_families(claims), {'website_owned_profiles'})


if __name__ == '__main__':
    unittest.main()
