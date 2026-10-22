"""Bounded company paragraphs and dated post-card acceptance controls."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from shirushi.snapshots import SnapshotStore, digest
from shirushi.web_sources import check_web
from shirushi_eval.support import SourceAudit


class ContentSectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(Path(self.temp.name))
        self.subject, self.name = '923609016', 'Example Pumps AS'
        raw = json.dumps({'organisasjonsnummer': self.subject, 'navn': self.name,
                          'hjemmeside': 'example.com'}).encode()
        self.anchor = self.store.save(raw, dict(organisation_number=self.subject, source_class='brreg_entity',
            source_url='https://data.brreg.no/enhetsregisteret/api/enheter/' + self.subject,
            http_status=200, sha256=digest(raw), retrieved_at='2026-10-10T08:00:00Z'))

    def decisions(self, html):
        raw = html.encode()
        sid = self.store.save(raw, dict(organisation_number=self.subject, source_class='company_owned',
            source_url='https://example.com/about', effective_url='https://example.com/about',
            http_status=200, sha256=digest(raw), declared_host='example.com', source_origin='example.com',
            robots_checked=True, retrieved_at='2026-10-10T08:00:00Z', ownership_anchor_snapshot_id=self.anchor))
        self.page_sid = sid
        return check_web(self.store, self.subject, sid)

    def audit(self, decisions):
        audit = SourceAudit(self.store.root, [self.subject])
        for decision in decisions:
            audit.claim(self.subject, decision['claim'], {decision['evidence']['id']: decision['evidence']})

    def pair(self):
        return ('<div><p>Meet Jane Doe, leader for Example Pumps AS.</p>'
                '<p>We supply industrial pumps and maintenance.</p></div>')

    def card(self):
        return ('<li class="wp-block-post"><h4 class="wp-block-post-title">'
                '<a href="/news/leader">Jane Doe er ansatt som daglig leder i Example Pumps AS</a></h4>'
                '<div class="wp-block-post-date"><time datetime="2024-10-04T10:57:16+02:00">'
                '<a href="/news/leader">04.10.2024</a></time></div>'
                '<div class="wp-block-post-excerpt"><p>The board met 03.10.2024. '
                'The director called the business a \u00abgreat team\u00bb.</p></div></li>')

    def test_adjacent_company_and_service_paragraphs_keep_subject_evidence(self):
        decisions = self.decisions(self.pair())
        self.assertEqual([d['field'] for d in decisions], ['product_service'])
        self.assertEqual(decisions[0]['claim']['value'], 'We supply industrial pumps and maintenance.')
        self.assertIn('Example Pumps AS', decisions[0]['evidence']['support_spans']['subject_context'])
        self.audit(decisions)

    def test_named_history_and_welcome_descriptions_retain_literal_scope(self):
        for paragraph in ('Example Pumps AS ble etablert i 1997. Vi utf\u00f8rer vedlikehold.',
                          'Velkommen til Example Pumps AS, din partner. V\u00e5re maskiner er tilgjengelig for leie.'):
            decisions = self.decisions('<p>' + paragraph + '</p>')
            self.assertEqual([d['field'] for d in decisions], ['product_service'])
            self.assertEqual(decisions[0]['claim']['value'], paragraph.split('. ', 1)[1])
            self.audit(decisions)

    def test_intervening_subject_heading_quote_negation_and_hidden_text_abstain(self):
        pair = self.pair()
        for html in (pair.replace('Example Pumps AS', 'Parent AS'),
                     pair.replace('Example Pumps AS', 'Example Pumps AS Holding'),
                     pair.replace('</p><p>', '</p><h2>Customer story</h2><p>'),
                     pair.replace('We supply', 'Our customer Parent AS supplies'),
                     pair.replace('leader for', 'customer of'),
                     pair.replace('We supply', 'We do not supply'),
                     '<blockquote>' + pair + '</blockquote>', '<div hidden>' + pair + '</div>',
                     pair.replace('<div>', '<div><h2>Quoted customer record</h2>'),
                     '<section><h2>Our group</h2>' + pair + '</section>',
                     '<section><h2>Customer story</h2>' + pair + '</section>',
                     '<section><p>Customer story</p>' + pair + '</section>',
                     '<section><p>Customer story.</p>' + pair + '</section>',
                     '<div>Quoted record: "' + pair + '"</div>',
                     pair.replace('Meet Jane Doe', '"Meet Jane Doe'), pair[:-6]):
            self.assertEqual(self.decisions(html), [], html)

    def test_post_card_publication_is_separate_from_board_date_and_current_role(self):
        decisions = self.decisions(self.card())
        self.assertEqual([d['field'] for d in decisions], ['public_activity'])
        self.assertEqual(decisions[0]['claim']['value']['published_at'], '2024-10-04')
        self.assertNotIn('registered_role', decisions[0]['claim']['field'])
        self.audit(decisions)

    def test_card_requires_own_headline_and_one_explicit_publication_time(self):
        card = self.card()
        for html in (card.replace('Example Pumps AS', 'Parent AS'),
                     card.replace('Example Pumps AS', 'Example Pumps AS Holding'),
                     card.replace('er ansatt', 'er ikke ansatt'),
                     card.replace('Jane Doe er', '"Jane Doe er'),
                     card.replace('wp-block-post-date', 'event-date'),
                     card.replace('class="wp-block-post-date"', 'class="wp-block-post-date updated" itemprop="dateModified"'),
                     card.replace('<time ', 'Updated: <time '),
                     card.replace('<div class="wp-block-post-date">', '<span>Updated: </span><div class="wp-block-post-date">'),
                     card.replace('<div class="wp-block-post-date">', 'Updated: <div class="wp-block-post-date">'),
                     card.replace('<time datetime=', '<time itemprop="dateModified" datetime='),
                     card.replace('<time datetime=', '<time itemprop="startDate" datetime='),
                     card.replace('<time ', '<time class="updated" '),
                     card.replace('<a href="/news/leader">04.', '<a href="/news/other">04.'),
                     card.replace('04.10.2024', '05.10.2024'),
                     card.replace('2024-10-04T10:57:16+02:00', '2099-10-04T10:57:16+02:00'),
                     card.replace('</li>', '<time datetime="2024-10-05">05.10.2024</time></li>'),
                     card.replace('The board met', 'This announcement is false. The board met'),
                     '<blockquote>' + card + '</blockquote>', '<div hidden>' + card + '</div>'):
            self.assertEqual(self.decisions(html), [], html)

    def test_auditor_rejects_forged_subject_context_and_card_date(self):
        for original, target in ((self.decisions(self.pair()), 'subject'), (self.decisions(self.card()), 'date')):
            self.assertEqual(len(original), 1)
            forged = copy.deepcopy(original)
            if target == 'subject':
                forged[0]['evidence']['support_spans']['subject_context'] = '<p>Parent AS</p>'
            else:
                forged[0]['claim']['value']['published_at'] = '2024-10-03'
            with self.assertRaises(ValueError):
                self.audit(forged)

    def test_company_prefix_group_scope_and_speaker_switch_do_not_bind(self):
        for html in ('<p>Example Pumps AS Holding. We supply industrial pumps.</p>',
                     '<div><h2>Our group</h2><p>Example Pumps AS is a member of the group. '
                     'We supply industrial pumps across the group.</p></div>',
                     '<p>Example Pumps AS attended the show. At the show, I introduced my startup: '
                     'We supply industrial pumps.</p>'):
            self.assertEqual(self.decisions(html), [], html)

    def test_auditor_rechecks_legal_identifier_in_subject_introduction(self):
        from shirushi_eval.html_support import document
        original = self.decisions(self.pair())[0]
        html = self.pair().replace('Jane Doe', 'org nr 999 999 999')
        self.assertEqual(self.decisions(html), [])
        raw, _ = self.store.open(self.page_sid)
        page = document(raw)
        intro, body = sorted((n for n in page.nodes if n['tag'] == 'p'), key=lambda n: n['start'])
        container = next(n for n in page.nodes if n['tag'] == 'div')
        forged = copy.deepcopy(original)
        item = forged['evidence']
        item.update(snapshot_id=self.page_sid, content_sha256=digest(raw),
                    id=self.page_sid + ':' + forged['claim']['claim_id'])
        forged['claim']['evidence_ids'] = [item['id']]
        item['locator'] = dict(html_start=body['start'], html_end=body['end'], subject_start=intro['start'],
                               subject_end=intro['end'], container_start=container['start'], container_end=container['end'])
        item['support_spans'] = dict(subject_context=page.source[intro['start']:intro['end']],
                                     section_context=page.source[container['start']:container['end']])
        with self.assertRaisesRegex(ValueError, 'competing legal identifiers'):
            self.audit([forged])

    def test_named_definition_excludes_next_entity_and_employee_sentence(self):
        for text in ('Example Pumps AS is an independent financial consultant and intermediary. '
                     'The holding company, Parent AS, employs 200 staff.',
                     'Example Pumps AS er et regnskapskontor i byen. Vi er i dag 14 ansatte.'):
            result = self.decisions('<p>' + text + '</p>')
            self.assertEqual([d['field'] for d in result], ['business_description'])
            self.assertEqual(result[0]['claim']['value'], text.split('. ', 1)[0] + '.')
            self.audit(result)

    def test_named_definition_rejects_wrong_actor_and_nonbusiness_relationship(self):
        for text in ('If Example Pumps AS is an independent consultant.',
                     'Example Pumps AS Holding is an independent consultant.',
                     'Example Pumps AS is a customer of Parent AS.',
                     'Example Pumps AS is a subsidiary of Parent.',
                     'Example Pumps AS is a data controller.',
                     'Example Pumps AS er en del av konsernet.',
                     'Example Pumps AS is a partner of Acme AS.',
                     'Example Pumps AS is a plaintiff in the lawsuit.',
                     'Example Pumps AS is an owner of a company.',
                     'Example Pumps AS is a tenant of the manufacturer.',
                     'Example Pumps AS is a consultant and Acme employs 200 staff.',
                     'Example Pumps AS is a consultant while Acme employs 200 staff.',
                     'Example Pumps AS is a consultant but Acme manufactures pumps.',
                     'Example Pumps AS is a company director.',
                     'Example Pumps AS er et selskap. Vi leverer ingen pumper.',
                     'Example Pumps AS is a company.',
                     'Example Pumps AS is a consultant that Acme employs.',
                     'Example Pumps AS is a consultant; Acme AS employs 200 staff.',
                     '"Example Pumps AS is a financial consultant."'):
            self.assertEqual(self.decisions('<p>' + text + '</p>'), [])
        for html in ('<div><p>Example Pumps AS is a financial consultant.</p>',
                     '<div>Quoted record: "<p>Example Pumps AS is a financial consultant.</p>"</div>',
                     '<section><h2>Hypothetical scenario</h2><p>Example Pumps AS is a financial consultant.</p></section>',
                     '<section>Hypothetical scenario<div><p>Example Pumps AS is a consultant.</p></div></section>',
                     '<section>Quoted record: "<div><p>Example Pumps AS is a consultant.</p></div>"</section>',
                     '<section><p>Customer story.</p><p>Example Pumps AS is a financial consultant.</p></section>'):
            self.assertEqual(self.decisions(html), [])

    def test_definition_preserves_abbreviation_and_does_not_replace_existing_service(self):
        text = 'Example Pumps AS is a consultant for U.S. manufacturers.'
        decisions = self.decisions('<p>' + text + '</p>')
        self.assertEqual(decisions[0]['claim']['value'], text)
        self.audit(decisions)
        decisions = self.decisions(self.pair() + '<p>Example Pumps AS is a financial consultant.</p>')
        self.assertEqual([d['field'] for d in decisions], ['product_service'])
        self.assertEqual(decisions[0]['claim']['value'], 'We supply industrial pumps and maintenance.')
        self.audit(decisions)
