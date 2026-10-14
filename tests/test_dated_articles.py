"""Named activity, publisher identity and publication-date controls."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from shirushi.snapshots import SnapshotStore, digest
from shirushi.web_sources import check_web
from shirushi_eval.support import SourceAudit


class DatedArticleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(Path(self.temp.name))
        self.subject, self.name = '923609016', 'Example Pumps AS'
        raw = json.dumps({'organisasjonsnummer': self.subject, 'navn': self.name,
                          'hjemmeside': 'www.example.com'}).encode()
        self.anchor = self.store.save(raw, dict(organisation_number=self.subject, source_class='brreg_entity',
            source_url='https://data.brreg.no/enhetsregisteret/api/enheter/' + self.subject,
            http_status=200, sha256=digest(raw), retrieved_at='2026-10-10T08:00:00Z'))

    def save(self, html, host='example.com'):
        raw = html.encode()
        return self.store.save(raw, dict(organisation_number=self.subject, source_class='company_owned',
            source_url='https://' + host + '/news', effective_url='https://' + host + '/news',
            http_status=200, sha256=digest(raw), declared_host=host, source_origin=host, robots_checked=True,
            retrieved_at='2026-10-10T08:00:00Z', evaluation_cutoff='2026-10-10T00:00:00Z',
            ownership_anchor_snapshot_id=self.anchor))

    def footer(self):
        return '<footer><p>Copyright 2020-2026 Example Pumps AS</p></footer>'

    def article(self, statement='Example Pumps joins the New Software family.', date='2026-02-04'):
        return '<article><time datetime="' + date + '">4 Feb 2026</time><h2>' + statement + '</h2></article>'

    def audit(self, decisions):
        audit = SourceAudit(self.store.root, [self.subject])
        for d in decisions:
            audit.claim(self.subject, d['claim'], {d['evidence']['id']: d['evidence']})

    def test_registered_publisher_and_named_article_time_support_dated_activity(self):
        article = self.article()
        decisions = check_web(self.store, self.subject, self.save(self.footer() + article))
        self.assertEqual([d['field'] for d in decisions], ['public_activity'])
        self.assertEqual(decisions[0]['claim']['value'], dict(statement='Example Pumps joins the New Software family.',
            published_at='2026-02-04', source_url='https://example.com/news'))
        self.assertEqual(decisions[0]['evidence']['claim_span'], article)
        self.audit(decisions)

    def test_explicit_publication_label_does_not_use_modification_date(self):
        article = ('<article><h2>Example Pumps has been acquired by New Software.</h2>'
            '<p><span class="published">Published Feb 4, 2026 | Last updated Mar 3, 2026</span></p></article>')
        decisions = check_web(self.store, self.subject, self.save(self.footer() + article))
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]['claim']['value']['published_at'], '2026-02-04')
        self.audit(decisions)

    def test_passive_delivery_is_target_action_not_partner_manufacture(self):
        article = ('<article><time datetime="2025-09-24T12:55:19.714Z">24.9.2025</time>'
            '<h3>New counter opened</h3><p>L\u00f8sningen, levert av Example Pumps i samarbeid med kommunen, '
            'gir planleggere data.</p></article>')
        decisions = check_web(self.store, self.subject, self.save(self.footer() + article))
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]['claim']['value']['published_at'], '2025-09-24')
        self.assertTrue(decisions[0]['claim']['value']['statement'].startswith('L\u00f8sningen, levert av Example Pumps'))
        self.audit(decisions)

    def test_identity_date_quote_and_role_ambiguities_abstain(self):
        article = self.article()
        for html in (article, self.footer().replace('Example Pumps AS', 'Parent AS') + article,
                     self.footer().replace('Example Pumps AS', 'Example Pumps AS Holding') + article,
                     self.footer() + self.article('OtherExample Pumps joins the New Software family.'),
                     self.footer() + self.article('Example Pumps Group joins the New Software family.'),
                     self.footer() + self.article('Example Pumps does not join the New Software family.'),
                     self.footer() + self.article('If Example Pumps joins the New Software family.'),
                     self.footer() + self.article('We opened a new factory.'),
                     self.footer() + '<blockquote>' + article + '</blockquote>',
                     self.footer() + '<div hidden>' + article + '</div>',
                     self.footer() + self.article('"Example Pumps joins the New Software family."'),
                     self.footer() + self.article(date='2099-01-01'),
                     self.footer() + self.article(date='2026-02-30'),
                     self.footer() + article.replace('</article>', '<time datetime="2026-02-05">Other</time></article>'),
                     self.footer() + article + '<p>Org.nr. 990888213</p>'):
            self.assertEqual(check_web(self.store, self.subject, self.save(html)), [], html)
        with self.assertRaises(ValueError):
            check_web(self.store, self.subject, self.save(self.footer() + article, host='other.com'))

    def test_modified_event_empty_and_article_footer_dates_are_not_publication(self):
        for time in ('<time itemprop="dateModified" datetime="2026-02-04">Last updated 4 Feb 2026</time>',
                     '<time itemprop="startDate" datetime="2026-02-04">Event starts 4 Feb 2026</time>',
                     '<time datetime="2026-02-04"></time>',
                     '<footer><time datetime="2026-02-04">4 Feb 2026</time></footer>'):
            html = self.footer() + '<article>' + time + '<h2>Example Pumps joins New Software.</h2></article>'
            self.assertEqual(check_web(self.store, self.subject, self.save(html)), [])

    def test_nullable_class_attribute_does_not_crash_valid_article(self):
        html = self.footer() + self.article().replace('</article>', '<span class>Decoration</span></article>')
        decisions = check_web(self.store, self.subject, self.save(html))
        self.assertEqual(len(decisions), 1)
        self.audit(decisions)

    def test_unrelated_copyright_and_explicit_denial_do_not_authorize_activity(self):
        for copyright in ('Photo copyright 2026 Example Pumps AS. Website publisher Parent.',
                          'This website is not copyright 2026 Example Pumps AS.'):
            html = '<footer><p>' + copyright + '</p></footer>' + self.article()
            self.assertEqual(check_web(self.store, self.subject, self.save(html)), [])
        html = self.footer() + self.article('Example Pumps joins New Software. This allegation is false.')
        self.assertEqual(check_web(self.store, self.subject, self.save(html)), [])
        for footer in ('<footer><p>This website is not <span>copyright 2026 Example Pumps AS</span>.</p></footer>',
                       '<footer><p>Photo credit: <span>copyright 2026 Example Pumps AS</span>. Website publisher Parent.</p></footer>',
                       '<footer><p>This website is not <span>copyright 2026 Example Pumps AS</span>. <q>Photo credit</q></p></footer>',
                       '<footer><p><q>This website is not</q> <span>copyright 2026 Example Pumps AS</span>.</p></footer>'):
            self.assertEqual(check_web(self.store, self.subject, self.save(footer + self.article())), [])
        for statement in ('Parent said: "Business grows. Example Pumps joins New Software. Welcome aboard."',
                          'Imagine the following scenario. Example Pumps joins New Software. This is a possibility.'):
            self.assertEqual(check_web(self.store, self.subject, self.save(self.footer() + self.article(statement))), [])

    def test_independent_audit_rejects_forged_article_date_statement_and_alias(self):
        original = check_web(self.store, self.subject, self.save(self.footer() + self.article()))[0]
        for target, key, value in (('value', 'published_at', '2026-03-03'),
                                   ('value', 'statement', 'Example Pumps opened a factory.'),
                                   ('locator', 'actor_alias', 'Parent')):
            bad = copy.deepcopy(original)
            (bad['claim']['value'] if target == 'value' else bad['evidence']['locator'])[key] = value
            with self.assertRaises(ValueError):
                self.audit([bad])
