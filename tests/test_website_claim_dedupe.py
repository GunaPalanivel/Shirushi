"""One verified website per company: the same site proven twice keeps the strongest proof; two sites abstain."""
import unittest

from shirushi.live import unique_decisions


def website(scope, value, claim_id):
    claim = {'claim_id': claim_id, 'field': 'verified_website', 'value': value, 'scope': scope,
             'family': 'website_owned_profiles', 'availability': 'available'}
    return {'field': 'verified_website', 'family': 'website_owned_profiles', 'accepted': True, 'claim': claim,
            'evidence': {'id': claim_id + ':e'}}


class WebsiteDedupeTests(unittest.TestCase):
    def test_same_site_under_two_scopes_keeps_the_strongest_proof(self):
        result = unique_decisions([website('registry_declared_host_name_gate', 'https://acme.no/', 'a'),
                                   website('company_owned_html', 'https://acme.no/', 'b')])
        kept = [d for d in result if d['field'] == 'verified_website']
        self.assertEqual([d['claim']['scope'] for d in kept], ['company_owned_html'])

    def test_same_host_different_seller_path_still_one_claim(self):
        result = unique_decisions([website('registry_declared_host_name_gate', 'https://www.acme.no/', 'a'),
                                   website('company_owned_html', 'https://acme.no/en/', 'b')])
        self.assertEqual(len([d for d in result if d['field'] == 'verified_website']), 1)

    def test_two_different_sites_abstain_as_ambiguous(self):
        result = unique_decisions([website('registry_declared_host_name_gate', 'https://acme.no/', 'a'),
                                   website('company_owned_html', 'https://acme-shop.com/', 'b')])
        sites = [d for d in result if d['field'] == 'verified_website']
        self.assertEqual(len(sites), 1)
        self.assertFalse(sites[0]['accepted'])
        self.assertEqual(sites[0]['availability'], 'ambiguous')

    def test_a_single_website_claim_is_untouched(self):
        decision = website('registry_declared_host_name_gate', 'https://acme.no/', 'a')
        self.assertEqual(unique_decisions([decision]), [decision])


if __name__ == '__main__':
    unittest.main()
