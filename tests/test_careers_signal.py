"""A careers-page URL is hiring_signal only after this page's website is accepted."""
import json
import tempfile
import unittest
from pathlib import Path

from shirushi.snapshots import SnapshotStore, digest
from shirushi.web_sources import check_web
from shirushi_eval.support import SourceAudit

SUBJECT = '923609016'
NAME = 'Example Pumps AS'
PROOF = ('<footer><p>Example Pumps AS | Orgnr. 923 609 016 | Storgata 1, 0123 Oslo | '
         'kontakt@acme-site.test</p></footer>')
H1 = '<h1>Ledige stillinger</h1>'
TITLE = '<title>Karriere</title>'


class HiringSignalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(Path(self.temp.name))

    def decisions(self, html, host, path, website, email=None):
        row = {'organisasjonsnummer': SUBJECT, 'navn': NAME, 'hjemmeside': website}
        if email:
            row['epostadresse'] = email
        anchor_raw = json.dumps(row).encode()
        anchor = self.store.save(anchor_raw, dict(organisation_number=SUBJECT, source_class='brreg_entity',
            source_url='https://data.brreg.no/enhetsregisteret/api/enheter/' + SUBJECT,
            http_status=200, sha256=digest(anchor_raw), retrieved_at='2026-10-10T08:00:00Z'))
        raw = html.encode()
        url = 'https://' + host + path
        sid = self.store.save(raw, dict(organisation_number=SUBJECT, source_class='company_owned',
            source_url=url, effective_url=url, http_status=200, sha256=digest(raw), declared_host=host,
            source_origin=host, robots_checked=True, retrieved_at='2026-10-10T08:00:00Z',
            ownership_anchor_snapshot_id=anchor))
        return check_web(self.store, SUBJECT, sid)

    def page(self, body, head=''):
        return '<html><head>' + head + '</head><body>' + body + '</body></html>'

    def hiring(self, html, host, path, website, email=None):
        decisions = self.decisions(html, host, path, website, email)
        return decisions, [d for d in decisions if d['field'] == 'hiring_signal']

    def test_accepted_careers_page_publishes_its_url_and_the_h1(self):
        html = self.page(H1 + PROOF, TITLE)
        decisions, found = self.hiring(html, 'www.acme-site.test', '/karriere', 'registered-elsewhere.test')
        self.assertIn('verified_website', [d['field'] for d in decisions])
        self.assertEqual(len(found), 1)
        claim, evidence = found[0]['claim'], found[0]['evidence']
        self.assertEqual(claim['value'], 'https://www.acme-site.test/karriere')
        self.assertEqual(claim['item_key'], claim['value'])
        self.assertEqual(evidence['claim_span'], H1)
        self.assertIn(H1.encode(), html.encode())
        SourceAudit(self.store.root, [SUBJECT]).claim(SUBJECT, claim, {evidence['id']: evidence})
        forged = dict(claim, value='https://www.acme-site.test/other')
        with self.assertRaises(ValueError):
            SourceAudit(self.store.root, [SUBJECT]).claim(SUBJECT, forged, {evidence['id']: evidence})

    def test_career_words_other_than_a_hardcoded_path_still_publish(self):
        html = self.page(H1 + PROOF, TITLE)
        _, found = self.hiring(html, 'www.acme-site.test', '/ledige-stillinger', 'registered-elsewhere.test')
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['claim']['value'], 'https://www.acme-site.test/ledige-stillinger')

    def test_title_is_the_span_when_the_page_has_no_h1(self):
        html = self.page(PROOF, TITLE)
        _, found = self.hiring(html, 'www.acme-site.test', '/karriere', 'registered-elsewhere.test')
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['evidence']['claim_span'], TITLE)

    def test_an_accepted_page_that_is_not_a_careers_link_publishes_nothing(self):
        html = self.page(H1 + PROOF, TITLE)
        decisions, found = self.hiring(html, 'www.acme-site.test', '/om-oss', 'registered-elsewhere.test')
        self.assertIn('verified_website', [d['field'] for d in decisions])
        self.assertEqual(found, [])

    def test_a_product_url_that_also_contains_a_career_word_is_not_a_careers_link(self):
        html = self.page(H1 + PROOF, TITLE)
        decisions, found = self.hiring(html, 'www.acme-site.test', '/tjenester/karriere', 'registered-elsewhere.test')
        self.assertIn('verified_website', [d['field'] for d in decisions])
        self.assertEqual(found, [])

    def test_registry_host_without_an_accepted_website_publishes_no_hiring_signal(self):
        html = self.page(H1, TITLE)
        decisions, found = self.hiring(html, 'example.no', '/karriere', 'example.no')
        self.assertNotIn('verified_website', [d['field'] for d in decisions])
        self.assertEqual(found, [])

    def test_tier_b_accepted_careers_page_publishes_the_same_url(self):
        filler = '<p>' + ('Vi leverer pumper og vedlikehold til bedrifter i hele landet. ' * 3) + '</p>'
        html = self.page(H1 + filler + '<footer>Org.nr 923 609 016</footer>', TITLE)
        decisions, found = self.hiring(html, 'example.no', '/karriere', 'example.no', email='post@example.no')
        self.assertIn('verified_website', [d['field'] for d in decisions])
        self.assertEqual([d['claim']['value'] for d in found], ['https://example.no/karriere'])
        self.assertEqual(found[0]['evidence']['claim_span'], H1)
        claim, evidence = found[0]['claim'], found[0]['evidence']
        SourceAudit(self.store.root, [SUBJECT]).claim(SUBJECT, claim, {evidence['id']: evidence})


if __name__ == '__main__':
    unittest.main()
