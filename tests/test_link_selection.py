"""Link selection spends the bounded page budget on distinct informative pages."""
import unittest
from urllib.parse import urlsplit

from shirushi.live import acquire_website
from shirushi.web_sources import content_links, page_links

SUBJECT = '923609016'
NAME = 'Example Pumps AS'


def anchors(*paths):
    return ''.join('<a href="' + path + '">x</a>' for path in paths).encode()


class Site:
    """Serves one fixed home page and empty pages elsewhere; records every request."""
    def __init__(self, home):
        self.home, self.urls = home, []

    def get(self, url, *_args, **_kw):
        self.urls.append(url)
        raw = self.home if urlsplit(url).path == '/' else b'<p>Page</p>'
        return raw, {'effective_url': url, 'content_type': 'text/html'}

    def paths(self):
        return [urlsplit(url).path for url in self.urls]


class PageLinkTests(unittest.TestCase):
    def test_keyword_in_host_does_not_admit_unrelated_links(self):
        html = anchors('/login', '/cart', '/tjenester')
        self.assertEqual(page_links(html, 'https://example-service.no/'),
                         ['https://example-service.no/tjenester'])

    def test_keyword_in_path_or_query_still_admits_links(self):
        html = anchors('/index.php?page=products', '/om-oss/')
        self.assertEqual(set(page_links(html, 'https://example.no/')),
                         {'https://example.no/index.php?page=products', 'https://example.no/om-oss/'})

    def test_informative_pages_without_the_older_keywords_are_leads(self):
        html = anchors('/omoss', '/siste-nytt', '/karriere', '/faste-priser', '/prosjekter', '/referanser')
        self.assertEqual(len(page_links(html, 'https://example.no/')), 6)

    def test_trailing_slash_and_www_variants_are_one_lead(self):
        html = anchors('/kontakt-oss/', '/kontakt-oss', '/om-oss#team', '/om-oss/')
        self.assertEqual(page_links(html, 'https://www.example.no/'),
                         ['https://www.example.no/kontakt-oss/', 'https://www.example.no/om-oss'])

    def test_plain_word_containing_a_legal_stem_is_not_legal(self):
        html = anchors('/artikkel/hvilken-hytte-passer', '/personvern')
        self.assertEqual(page_links(html, 'https://example.no/')[0], 'https://example.no/personvern')

    def test_new_in_a_slug_is_not_news(self):
        links = ['https://example.no/' + path for path in ('hva-koster-det-aa-bygge-nytt-hus', 'aktuelt')]
        self.assertEqual(content_links(links), [links[1], links[0]])

    def test_compound_terms_pages_stay_legal_leads(self):
        html = anchors('/salgsbetingelser', '/kjopsvilkar', '/artikkel/hvilke-hus', '/tjenester')
        self.assertEqual(page_links(html, 'https://example.no/')[:2],
                         ['https://example.no/salgsbetingelser', 'https://example.no/kjopsvilkar'])

    def test_careers_and_news_share_the_budget_with_products(self):
        links = ['https://example.no/' + path for path in ('tjenester/a', 'tjenester/b', 'karriere', 'siste-nytt')]
        self.assertEqual(content_links(links), [links[0], links[2], links[3], links[1]])

    def test_named_services_rank_before_projects_and_references(self):
        links = ['https://example.no/' + path for path in ('referanser', 'prosjekter', 'tjenester/bygg')]
        self.assertEqual(content_links(links), [links[2], links[0], links[1]])

    def test_price_pages_are_leads_but_words_containing_pris_are_not(self):
        html = anchors('/faste-priser/', '/artikkel/prisgunstig-bolig')
        self.assertEqual(page_links(html, 'https://example.no/'), ['https://example.no/faste-priser/'])

    def test_content_links_collapse_variants(self):
        links = ['https://example.no/tjenester/', 'https://example.no/tjenester']
        self.assertEqual(content_links(links), ['https://example.no/tjenester/'])


class PageBudgetTests(unittest.TestCase):
    ENTITY = {'navn': NAME, 'hjemmeside': 'https://example-service.no/'}

    def test_budget_goes_to_informative_pages_not_host_keyword_matches(self):
        site = Site(anchors('/login', '/cart', '/handlekurv', '/tjenester', '/karriere', '/siste-nytt', '/produkter'))
        acquire_website(site, SUBJECT, self.ENTITY, None, 6)
        self.assertEqual(site.paths(), ['/', '/tjenester', '/karriere', '/siste-nytt', '/produkter'])

    def test_second_privacy_page_does_not_replace_an_about_page(self):
        site = Site(anchors('/personvern', '/kopi-av-personvern', '/om-oss'))
        acquire_website(site, SUBJECT, {'navn': NAME, 'hjemmeside': 'example.no'}, None, 6)
        self.assertEqual(site.paths()[:3], ['/', '/personvern', '/om-oss'])

    def test_plain_word_containing_a_legal_stem_is_not_an_identity_lead(self):
        site = Site(anchors('/artikkel/hvilken-hytte-passer', '/personvern', '/om-oss'))
        acquire_website(site, SUBJECT, {'navn': NAME, 'hjemmeside': 'example.no'}, None, 6)
        self.assertEqual(site.paths()[:3], ['/', '/personvern', '/om-oss'])

    def test_registry_lead_on_the_www_alias_is_not_fetched_twice(self):
        site = Site(anchors('/om-oss'))
        acquire_website(site, SUBJECT, {'navn': NAME, 'hjemmeside': 'www.example.no',
                                        'epostadresse': 'post@example.no'}, None, 6)
        self.assertEqual(site.urls.count('https://example.no/'), 0)
        self.assertEqual(site.urls[0], 'https://www.example.no/')

    def test_trailing_slash_variant_is_not_requested_again(self):
        site = Site(anchors('/kontakt-oss/', '/kontakt-oss', '/tjenester'))
        acquire_website(site, SUBJECT, {'navn': NAME, 'hjemmeside': 'example.no'}, None, 6)
        self.assertEqual(sorted(site.paths()), ['/', '/kontakt-oss/', '/tjenester'])

    def test_budget_is_not_raised(self):
        site = Site(anchors(*['/tjenester/' + str(i) for i in range(20)]))
        acquire_website(site, SUBJECT, {'navn': NAME, 'hjemmeside': 'example.no'}, None, 6)
        self.assertEqual(len(site.urls), 6)


if __name__ == '__main__':
    unittest.main()
