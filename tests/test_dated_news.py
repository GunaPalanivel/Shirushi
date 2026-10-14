"""Title plus the datetime attribute, offset kept, only after the website is accepted."""
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
OFFSET = '2026-02-04T08:30:00+01:00'
ZULU = '2025-09-24T12:55:19.714Z'
HEADLINE = 'Nytt verksted i Bergen'


class DatedNewsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(Path(self.temp.name))

    def decisions(self, html, host, path, website, email=None, name=NAME):
        row = {'organisasjonsnummer': SUBJECT, 'navn': name, 'hjemmeside': website}
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

    def article(self, headline=HEADLINE, when=OFFSET, extra=''):
        stamp = ('<time datetime="%s">4 Feb 2026</time>' % when) if when else '<time>4 Feb 2026</time>'
        return '<article>' + stamp + '<h2>' + headline + '</h2>' + extra + '</article>'

    def news(self, html, host='www.acme-site.test', path='/nyheter', website='registered-elsewhere.test', **kw):
        decisions = self.decisions(html, host, path, website, **kw)
        return decisions, [d for d in decisions if d['field'] == 'dated_news']

    def test_accepted_page_publishes_the_headline_and_the_literal_offset(self):
        body = self.article()
        decisions, found = self.news(body + PROOF)
        self.assertIn('verified_website', [d['field'] for d in decisions])
        self.assertEqual(len(found), 1)
        value = found[0]['claim']['value']
        self.assertEqual(value['headline'], HEADLINE)
        self.assertEqual(value['published_at'], OFFSET)
        self.assertEqual(value['source_url'], 'https://www.acme-site.test/nyheter')
        self.assertEqual(found[0]['evidence']['claim_span'], body)
        self.assertNotIn('public_activity', [d['field'] for d in decisions])
        claim, evidence = found[0]['claim'], found[0]['evidence']
        SourceAudit(self.store.root, [SUBJECT]).claim(SUBJECT, claim, {evidence['id']: evidence})
        forged = dict(claim, value=dict(claim['value'], published_at='2020-01-01'))
        with self.assertRaises(ValueError):
            SourceAudit(self.store.root, [SUBJECT]).claim(SUBJECT, forged, {evidence['id']: evidence})

    def test_zulu_datetime_is_not_collapsed_to_a_calendar_date(self):
        _, found = self.news(self.article(when=ZULU) + PROOF)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['claim']['value']['published_at'], ZULU)

    def test_a_denial_word_outside_the_article_does_not_abstain(self):
        _, found = self.news(self.article() + '<p>Vi har ikke mer.</p>' + PROOF)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['claim']['value']['published_at'], OFFSET)

    def test_quote_and_denial_inside_the_article_abstain(self):
        pages = (self.article(headline='Nytt verksted: Bergen'),
                 self.article(extra='<p>The story is false.</p>'),
                 self.article(extra='<p>Vi har ikke apnet.</p>'),
                 self.article(extra='<p>A neighbour said the workshop moved.</p>'))
        for body in pages:
            decisions, found = self.news(body + PROOF)
            self.assertIn('verified_website', [d['field'] for d in decisions])
            self.assertEqual(found, [], body)

    def test_missing_datetime_or_heading_or_two_datetimes_abstain(self):
        undated = '<article><h2>' + HEADLINE + '</h2></article>'
        no_heading = '<article><time datetime="' + OFFSET + '">4 Feb 2026</time><p>Bare tekst om verkstedet.</p></article>'
        two = ('<article><time datetime="' + OFFSET + '">4 Feb 2026</time>'
               '<time datetime="2026-03-01T09:00:00+01:00">1 Mar 2026</time><h2>' + HEADLINE + '</h2></article>')
        for body in (self.article(when=None), undated, no_heading, two):
            decisions, found = self.news(body + PROOF)
            self.assertIn('verified_website', [d['field'] for d in decisions])
            self.assertEqual(found, [], body)

    def test_each_article_on_an_accepted_page_is_its_own_claim(self):
        first = self.article(headline='Forste verksted i Bergen', when=OFFSET)
        second = self.article(headline='Andre verksted i Oslo', when='2026-03-01T09:00:00+01:00')
        _, found = self.news(first + second + PROOF)
        self.assertEqual(len(found), 2)
        self.assertEqual({d['claim']['value']['published_at'] for d in found},
                         {OFFSET, '2026-03-01T09:00:00+01:00'})
        self.assertEqual(len({d['claim']['claim_id'] for d in found}), 2)

    def test_registry_host_without_an_accepted_website_publishes_no_dated_news(self):
        decisions, found = self.news(self.article(), host='example.no', path='/nyheter', website='example.no')
        self.assertNotIn('verified_website', [d['field'] for d in decisions])
        self.assertEqual(found, [])

    def test_public_activity_keeps_its_name_and_calendar_date_when_the_website_was_refused(self):
        # article_values collapses an offset to a calendar date. That claim stays public_activity.
        footer = '<footer><p>Copyright 2020-2026 Example Pumps AS</p></footer>'
        body = ('<article><time datetime="' + OFFSET + '">4 Feb 2026</time>'
                '<h2>Example Pumps opened a workshop in Bergen.</h2></article>')
        decisions = self.decisions(footer + body, 'example.com', '/news', 'www.example.com')
        fields = [d['field'] for d in decisions]
        self.assertNotIn('verified_website', fields)
        self.assertNotIn('dated_news', fields)
        activity = next(d for d in decisions if d['field'] == 'public_activity')
        self.assertEqual(activity['claim']['value']['published_at'], '2026-02-04')

    def test_an_accepted_page_keeps_public_activity_and_adds_the_literal_datetime(self):
        filler = '<p>' + ('Vi leverer pumper og vedlikehold til bedrifter i hele landet. ' * 3) + '</p>'
        footer = ('<footer><p>Copyright 2020-2026 Example Pumps AS</p>'
                  '<p>Org.nr 923 609 016</p></footer>')
        body = ('<article><time datetime="' + OFFSET + '">4 Feb 2026</time>'
                '<h2>Example Pumps opened a workshop in Bergen.</h2></article>')
        html = '<html><head><title>Verksted</title></head><body>' + filler + body + footer + '</body></html>'
        decisions, found = self.news(html, host='example.no', path='/nyheter', website='example.no',
                                     email='post@example.no')
        self.assertIn('verified_website', [d['field'] for d in decisions])
        activity = next(d for d in decisions if d['field'] == 'public_activity')
        self.assertEqual(activity['claim']['value']['published_at'], '2026-02-04')
        self.assertEqual(activity['claim']['field'], 'public_activity')
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['claim']['value']['published_at'], OFFSET)
        self.assertEqual(found[0]['claim']['value']['headline'], 'Example Pumps opened a workshop in Bergen.')


if __name__ == '__main__':
    unittest.main()
