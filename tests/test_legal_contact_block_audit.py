"""Independent audit of ownership proved by a legal contact block (name, labelled number and a site tie in one block)."""
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from shirushi.snapshots import SnapshotStore, digest
from shirushi.web_sources import check_web
from shirushi_eval.html_support import legal_contact_block, legal_operator, ownership_proof
from shirushi_eval.support import SourceAudit

SUBJECT = '923609016'
NAME = 'Example Pumps AS'
HOST = 'www.acme-site.test'
ROW = 'Example Pumps AS | Orgnr. 923 609 016 | Storgata 1, 0123 Oslo | kontakt@acme-site.test'
BLOCK = '<p>' + ROW + '</p>'
IDENT = 'Example Pumps AS, org.nr. 923609016'


def block_of(html, host=HOST, path='/kontakt', name=NAME):
    return legal_contact_block(html.encode(), SUBJECT, name, 'https://' + host + path)


def attacks():
    """Label -> (html, host). Every entry carries an own-site-looking block that must not prove ownership."""
    footer = ROW
    result = {
        'supplier listing on a foreign host': ('<p>Our suppliers: ' + IDENT + ', post@example-pumps.test</p>', 'other-site.test'),
        'listing without an own-site tie': ('<p>' + IDENT + ', post@example-pumps.test</p>', 'other-site.test'),
        'directory host': (BLOCK, 'www.proff.no'),
        'directory host with a matching mailbox': ('<p>' + footer.replace('acme-site.test', 'proff.no') + '</p>', 'www.proff.no'),
        'directory subdomain': ('<p>' + footer.replace('acme-site.test', 'proff.no') + '</p>', 'bedrift.proff.no'),
        'directory with a name-like host': ('<footer>Example Pumps AS · org.nr. 923 609 016</footer>', 'examplepumps.brreg.no'),
        'group parent block with another number': ('<footer>Parent AS | Orgnr. 990 888 213 | post@acme-site.test</footer>'
                                                   '<p>Example Pumps AS is a subsidiary.</p>', HOST),
        'blockquote': ('<blockquote>' + BLOCK + '</blockquote>', HOST),
        'quote element': ('<q>' + BLOCK + '</q>', HOST),
        'hidden attribute': ('<p hidden>' + footer + '</p>', HOST),
        'aria hidden': ('<p aria-hidden="true">' + footer + '</p>', HOST),
        'display none': ('<p style="display : none">' + footer + '</p>', HOST),
        'visibility hidden': ('<p style="visibility:hidden">' + footer + '</p>', HOST),
        'template': ('<template>' + BLOCK + '</template>', HOST),
        'noscript': ('<noscript>' + BLOCK + '</noscript>', HOST),
        'hidden ancestor': ('<div hidden>' + BLOCK + '</div>', HOST),
        'unclosed element': ('<div><p>' + footer + '</div>', HOST),
        'mailbox at another domain': ('<p>Example Pumps AS | Orgnr. 923 609 016 | post@other-mail.test</p>', HOST),
        'name without number': ('<p>Example Pumps AS | Storgata 1 | kontakt@acme-site.test</p>', HOST),
        'number without name': ('<p>Orgnr. 923 609 016 | Storgata 1 | kontakt@acme-site.test</p>', HOST),
        'label-less number': ('<p>Example Pumps AS | 923 609 016 | kontakt@acme-site.test</p>', HOST),
        'vat label': ('<p>Example Pumps AS | VAT no. 923 609 016 | kontakt@acme-site.test</p>', HOST),
        'org-nr label': ('<p>Example Pumps AS | Org-nr 923 609 016 | kontakt@acme-site.test</p>', HOST),
        'name without legal form': ('<p>Example Pumps | Orgnr. 923 609 016 | kontakt@acme-site.test</p>', HOST),
        'old registered name': ('<p>Old Pumps AS | Orgnr. 923 609 016 | kontakt@acme-site.test</p>', HOST),
        'two labelled numbers': ('<p>' + footer + ' | Org.nr. 990 888 213</p>', HOST),
        'wrong number': ('<p>' + footer.replace('923 609 016', '990 888 213') + '</p>', HOST),
        'other legal entity AS': ('<p>' + footer + ' | Betalingsleverandor Payments AS</p>', HOST),
        'other legal entity ApS': ('<p>' + IDENT + ' | Danske Partnerselskap ApS | post@acme-site.test</p>', HOST),
        'other legal entity AG': ('<p>' + IDENT + ' | Schweiz Holding AG | post@acme-site.test</p>', HOST),
        'other legal entity ENK': ('<p>' + IDENT + ' | Kari Nordmann ENK | post@acme-site.test</p>', HOST),
        'other legal entity KS': ('<p>' + IDENT + ' | Fjord Drift KS | post@acme-site.test</p>', HOST),
        'other legal entity A/S': ('<p>' + IDENT + ' | Nordic Cargo A/S | post@acme-site.test</p>', HOST),
        'question mark': ('<p>' + footer + '?</p>', HOST),
        'straight quote': ('<p>"' + footer + '"</p>', HOST),
        'curly quote': ('<p>“' + footer + '”</p>', HOST),
        'guillemets': ('<p>«' + footer + '»</p>', HOST),
        'own-host absolute link only': ('<div>' + IDENT + ' <a href="https://www.acme-site.test/">our site</a></div>', HOST),
        'own-host url text only': ('<div>' + IDENT + ' www.acme-site.test</div>', HOST),
        'relative link only': ('<div>' + IDENT + ' <a href="/kontakt">Kontakt</a></div>', HOST),
        'phone only': ('<p>' + IDENT + ' <a href="tel:+4722222222">22 22 22 22</a></p>', HOST),
        'oversized div': ('<div>' + footer + ' ' + 'x ' * 300 + '</div>', HOST),
        'oversized footer': ('<footer>' + footer + ' ' + 'x ' * 800 + '</footer>', HOST),
        'mail domain followed by another at sign': ('<p>' + IDENT + ' post@acme-site.test@other-mail.test</p>', 'acme-site.test'),
        'webmail parent of a shared host': ('<p>' + IDENT + ' someone@wixsite.com</p>', 'example.wixsite.com'),
        'pages.dev mailbox': ('<p>' + IDENT + ' support@pages.dev</p>', 'victim.pages.dev'),
        'public suffix mailbox': ('<p>' + IDENT + ' post@bergen.no</p>', 'victim.bergen.no'),
        'name domain on a deeper subdomain': ('<footer>Example Pumps AS · org.nr. 923 609 016</footer>', 'foo.examplepumps.no'),
        'cyrillic look-alike host': ('<footer>Example Pumps AS · org.nr. 923 609 016</footer>', 'examplеpumps.no'),
        'zero width host': ('<footer>Example Pumps AS · org.nr. 923 609 016</footer>', 'examplepumps​.no'),
        'polish l host': ('<footer>Example Pumps AS · org.nr. 923 609 016</footer>', 'examplepumpsł.no'),
        'name domain on a longer name': ('<footer>Example Pumps AS · org.nr. 923 609 016</footer>', 'examplepumpsnorge.no'),
        'name domain on an abbreviation': ('<footer>Example Pumps AS · org.nr. 923 609 016</footer>', 'ex-pumps.no'),
    }
    for lead in ('Customer story: ', 'Our clients: ', 'Kunde: ', 'Leverandor: ', 'Partner: ', 'Referanse: ', 'Testimonial: ',
                 'Sponsor: ', 'Medlem: ', 'Subsidiary of ', 'Datterselskap: ', 'Not ', 'Ikke ', 'Formerly ', 'Tidligere ',
                 'c/o ', 'On behalf of ', 'Design av ', 'Utviklet av ', 'Powered by ', 'Hosted by ', 'Eies av ',
                 'Arbeidsgiver: ', 'Employer: ', 'Pressekontakt: ', 'Leietaker: ', 'Tenant: ', 'Forhandler: ',
                 'Faktura sendes til ', 'Vi har kjøpt ', 'Konkursbo etter ', 'Prosjekt: ', 'Regnskapsfører: ',
                 'Revisor: ', 'Samarbeid med ', 'Acquired ', 'Hvis ', 'If '):
        result['context word before the name: ' + lead] = ('<p>' + lead + ROW + '</p>', HOST)
    result['context word between name and number'] = ('<p>Example Pumps AS (customer) Orgnr. 923 609 016 post@acme-site.test</p>', HOST)
    result['context word after the number'] = ('<p>Example Pumps AS Orgnr. 923 609 016 invoice post@acme-site.test</p>', HOST)
    return result


class LegalContactBlockUnitTests(unittest.TestCase):
    def test_pipe_separated_footer_with_own_domain_mailbox_proves(self):
        result = block_of(BLOCK)
        self.assertEqual(result['kind'], 'legal_contact_block')
        self.assertIn('Orgnr. 923 609 016', result['text'])
        self.assertTrue(BLOCK.startswith('<p>') and BLOCK[result['start']:result['end']] == BLOCK)

    def test_mailto_link_and_parent_or_child_domains_tie(self):
        link = '<p>' + IDENT + ', <a href="mailto:post@acme-site.test?subject=hei">Send e-post</a></p>'
        self.assertIsNotNone(block_of(link, 'shop.acme-site.test'))
        self.assertIsNotNone(block_of('<p>' + IDENT + ', post@shop.acme-site.test</p>', 'acme-site.test'))
        self.assertIsNotNone(block_of('<p>' + IDENT + ', POST@ACME-SITE.TEST.</p>', 'WWW.Acme-Site.test'))

    def test_name_domain_tie_without_a_mailbox(self):
        footer = '<footer>Example Pumps AS · org.nr. 923 609 016 · del av Pump Group</footer>'
        for host in ('www.examplepumps.no', 'example-pumps.no', 'examplepumps.com', 'examplepumps.org', 'examplepumps.net',
                     'examplepumps.eu', 'examplepumps.com.no'):
            self.assertIsNotNone(block_of(footer, host), host)

    def test_norwegian_letters_fold_in_the_name_domain_tie(self):
        html = '<p>Kragerø Installasjon AS Org.nr: 923609016 Bråteveien 7, 3772 Kragerø</p>'
        self.assertIsNotNone(block_of(html, 'krageroinstallasjon.no', name='Kragerø Installasjon AS'))
        self.assertIsNone(block_of(html, 'krageroinstallasjon.no', name='Kragerø Installasjon AS'.replace('Krager', 'Brager')))

    def test_platform_tenants_and_public_sector_hosts_never_prove(self):
        platforms = ('medium.com substack.com notion.site notion.so linktr.ee google.com mystrikingly.com strikingly.com '
                     'weebly.com jimdosite.com jimdofree.com carrd.co squarespace.com wixsite.com wix.com webflow.io '
                     'godaddysites.com business.site github.io gitlab.io netlify.app vercel.app pages.dev herokuapp.com '
                     'blogspot.com wordpress.com tumblr.com ucoz.com 000webhostapp.com myshopify.com azurewebsites.net '
                     'web.app framer.app wixstudio.io gmail.com hotmail.com hotmail.no outlook.com outlook.no yahoo.com '
                     'yahoo.no online.no live.com live.no icloud.com proton.me protonmail.com sites.google.com github.com '
                     'gitlab.com').split()
        for platform in platforms:
            for host in ('victim.' + platform, platform, 'www.' + platform):
                for mailbox in ('x@' + platform, 'x@victim.' + platform, 'x@' + host):
                    self.assertIsNone(block_of('<p>' + IDENT + ' ' + mailbox + '</p>', host), (host, mailbox))
            platform_name = platform.split('.')[0].capitalize() + ' AS'
            html = '<p>%s, org.nr. 923609016, post@%s</p>' % (platform_name, platform)
            self.assertIsNone(block_of(html, platform, name=platform_name), platform)
            self.assertIsNone(block_of(html, 'www.' + platform, name=platform_name), platform)
        for host, mailbox in (('victim.vestland.no', 'post@vestland.no'), ('victim.kommune.no', 'post@kommune.no'),
                              ('steinkjer.kommune.no', 'x@steinkjer.kommune.no'), ('victim.fylke.no', 'post@fylke.no'),
                              ('bergen.no', 'post@bergen.no'), ('victim.bergen.no', 'post@bergen.no'),
                              ('acme-site.com.no', 'post@com.no'), ('examplepumps.vestland.no', 'post@examplepumps.vestland.no')):
            self.assertIsNone(block_of('<p>' + IDENT + ' ' + mailbox + '</p>', host), (host, mailbox))
        self.assertIsNone(block_of('<footer>Example Pumps AS · org.nr. 923 609 016</footer>', 'examplepumps.vestland.no'))

    def test_mailbox_ties_through_the_registrable_domain_only(self):
        self.assertIsNotNone(block_of('<p>' + IDENT + ' a@mail.acme-site.test</p>', 'acme-site.test'))
        self.assertIsNotNone(block_of('<p>' + IDENT + ' a@acme-site.test</p>', 'shop.acme-site.test'))
        self.assertIsNotNone(block_of('<p>' + IDENT + ' a@shop.acme-site.com.no</p>', 'www.acme-site.com.no'))
        self.assertIsNone(block_of('<p>' + IDENT + ' a@other.test</p>', 'acme-site.test'))

    def test_name_domain_tie_needs_a_permitted_tld_else_an_own_domain_mailbox(self):
        footer = '<footer>Example Pumps AS · org.nr. 923 609 016</footer>'
        mailed = '<footer>Example Pumps AS · org.nr. 923 609 016 · post@%s</footer>'
        for tld in ('no', 'com', 'org', 'net', 'eu'):
            self.assertIsNotNone(block_of(footer, 'examplepumps.' + tld), tld)
        for tld in ('shop', 'store', 'xyz', 'top', 'online', 'site', 'cc', 'ru', 'test', 'co.uk'):
            host = 'examplepumps.' + tld
            self.assertIsNone(block_of(footer, host), tld)
            self.assertIsNotNone(block_of(mailed % host, host), tld)
        self.assertIsNone(block_of(footer, 'examplepumps.github.io'))

    def test_relationship_word_far_from_the_identity_does_not_block(self):
        padding = ' '.join(['Navigasjon'] * 14)
        footer = ('<footer>Åpningstider man-fre 08-16 (kveldsåpent for kunder på torsdager) ' + padding +
                  ' Her finner du oss: Example Pumps AS Storgata 1, 0123 Oslo post@acme-site.test Org.nr. 923609016</footer>')
        self.assertIsNotNone(block_of(footer))
        self.assertIsNone(block_of(footer.replace('Her finner du oss:', 'Kunde:')))
        self.assertIsNone(block_of(footer.replace('Org.nr. 923609016', 'Kunde Org.nr. 923609016')))

    def test_first_satisfying_block_in_end_tag_order_is_the_proof(self):
        html = '<footer>' + BLOCK + ' <p>Mer</p></footer>'
        result = block_of(html)
        self.assertEqual(html[result['start']:result['end']], BLOCK)

    def test_candidate_tags_and_size_limits(self):
        for tag in ('footer', 'address', 'p', 'li', 'div', 'td', 'span'):
            self.assertIsNotNone(block_of('<%s>%s</%s>' % (tag, ROW, tag)), tag)
        self.assertIsNone(block_of('<section>' + ROW + '</section>'))
        self.assertIsNotNone(block_of('<address>' + ROW + ' ' + 'x ' * 600 + '</address>'))
        self.assertIsNotNone(block_of('<div>' + ROW + ' ' + 'x ' * 220 + '</div>'))
        self.assertIsNone(block_of('<div>' + ROW + ' ' + 'x ' * 260 + '</div>'))

    def test_page_url_is_required(self):
        self.assertIsNone(legal_contact_block(BLOCK.encode(), SUBJECT, NAME, ''))
        self.assertIsNone(legal_contact_block(BLOCK.encode(), SUBJECT, NAME, 'file:///nothing'))

    def test_every_attack_is_rejected_and_the_unmodified_footer_proves(self):
        self.assertIsNotNone(block_of(BLOCK))
        for label, (html, host) in attacks().items():
            self.assertIsNone(block_of(html, host), label)

    def test_existing_operator_kinds_are_tried_first_and_unchanged(self):
        html = '<footer>Copyright Example Pumps AS. Org.nr. 923 609 016 post@acme-site.test</footer>'
        direct = legal_operator(html.encode(), SUBJECT, NAME)
        self.assertIsNotNone(direct)
        self.assertEqual(ownership_proof(html.encode(), SUBJECT, NAME, '', 'https://' + HOST + '/'), direct)
        self.assertNotIn('kind', direct)
        self.assertIsNone(legal_operator(BLOCK.encode(), SUBJECT, NAME, '', 'https://' + HOST + '/'))
        self.assertEqual(ownership_proof(BLOCK.encode(), SUBJECT, NAME, '', 'https://' + HOST + '/')['kind'], 'legal_contact_block')
        self.assertIsNone(ownership_proof(('<p>' + ROW.replace('Example Pumps AS', 'Other AS') + '</p>').encode(),
                                          SUBJECT, NAME, '', 'https://' + HOST + '/'))


class LegalContactBlockAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(Path(self.temp.name))
        self.anchor = self.anchor_for(NAME, 'registered-elsewhere.test')

    def anchor_for(self, name, website):
        raw = json.dumps({'organisasjonsnummer': SUBJECT, 'navn': name, 'hjemmeside': website}).encode()
        url = 'https://data.brreg.no/enhetsregisteret/api/enheter/' + SUBJECT
        return self.store.save(raw, {'organisation_number': SUBJECT, 'source_class': 'brreg_entity',
            'source_url': url, 'effective_url': url, 'http_status': 200, 'sha256': digest(raw),
            'retrieved_at': '2026-10-10T08:00:00Z'})

    def save(self, html, path='/', host=HOST, **extra):
        raw = html.encode()
        url = 'https://' + host + path
        metadata = {'organisation_number': SUBJECT, 'source_class': 'company_owned', 'source_url': url,
            'effective_url': url, 'http_status': 200, 'sha256': digest(raw), 'source_origin': host,
            'declared_host': host, 'robots_checked': True, 'retrieved_at': '2026-10-10T08:00:00Z',
            'ownership_anchor_snapshot_id': self.anchor}
        metadata.update(extra)
        return self.store.save(raw, metadata)

    def audit(self, decisions):
        audit = SourceAudit(self.store.root, [SUBJECT])
        for decision in decisions:
            audit.claim(SUBJECT, decision['claim'], {decision['evidence']['id']: decision['evidence']})

    def forged_site(self, sid, html, span, host=HOST, path='/', **change):
        """A verified_website claim assembled by hand, independent of the maker, for any page and span."""
        start = html.index(span)
        values = {'field': 'verified_website', 'value': 'https://' + host + '/', 'scope': 'company_owned_html',
                  'method': 'explicit_subject_html_v1', 'legal_name': NAME, 'operator': True,
                  'html_start': start, 'html_end': start + len(span), 'family': 'website_owned_profiles'}
        values.update(change)
        key = None
        identity = hashlib.sha256(json.dumps([SUBJECT, values['field'], values['scope'], key, None], ensure_ascii=False,
                                             sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        evidence_id = sid + ':' + identity
        claim = {'claim_id': identity, 'field': values['field'], 'value': values['value'], 'scope': values['scope'],
                 'family': values['family'], 'item_key': key, 'period': None, 'availability': 'available',
                 'evidence_ids': [evidence_id], 'freshness': 'live_source'}
        evidence = {'id': evidence_id, 'snapshot_id': sid, 'source_url': 'https://' + host + path,
                    'source_class': 'company_owned', 'source_origin': host, 'retrieved_at': '2026-10-10T08:00:00Z',
                    'content_sha256': digest(html.encode()), 'claim_span': span,
                    'locator': {'html_start': values['html_start'], 'html_end': values['html_end'],
                                'legal_name': values['legal_name'], 'operator': values['operator']},
                    'extraction_method': values['method']}
        return [{'claim': claim, 'evidence': evidence}]

    # positive controls: maker produces, auditor accepts

    def test_proof_page_publishes_the_verified_website_and_the_audit_accepts_it(self):
        html = '<h1>Kontakt</h1><footer>' + BLOCK + '</footer>'
        decisions = check_web(self.store, SUBJECT, self.save(html, '/kontakt'))
        self.assertEqual([d['field'] for d in decisions], ['verified_website'])
        self.assertEqual(decisions[0]['evidence']['claim_span'], BLOCK)
        self.audit(decisions)

    def test_content_page_with_the_operator_link_audits_with_company_owned_scope(self):
        contact = self.save('<footer>' + BLOCK + '</footer>', '/kontakt')
        content = self.save('<p>Example Pumps AS produces industrial pumps.</p>', '/produkter', operator_snapshot_id=contact)
        decisions = check_web(self.store, SUBJECT, content)
        self.assertEqual([d['claim']['scope'] for d in decisions], ['company_owned_html'])
        self.assertEqual({d['evidence']['extraction_method'] for d in decisions}, {'explicit_subject_html_v1'})
        self.audit(decisions)

    def test_name_domain_tie_without_a_mailbox_audits(self):
        html = '<footer>Example Pumps AS · org.nr. 923 609 016 · del av Pump Group</footer>'
        decisions = check_web(self.store, SUBJECT, self.save(html, '/', 'www.examplepumps.no'))
        self.assertEqual([d['field'] for d in decisions], ['verified_website'])
        self.audit(decisions)

    def test_registry_host_page_with_a_block_keeps_its_claims_and_gains_the_website(self):
        self.anchor = self.anchor_for(NAME, HOST)
        html = BLOCK + '<p>Example Pumps AS produces industrial pumps.</p>'
        decisions = check_web(self.store, SUBJECT, self.save(html))
        self.assertEqual({d['field'] for d in decisions}, {'verified_website', 'product_service'})
        self.assertEqual({d['claim']['scope'] for d in decisions}, {'company_owned_html'})
        self.audit(decisions)

    def test_registry_host_page_without_a_block_audits_as_before(self):
        self.anchor = self.anchor_for(NAME, HOST)
        decisions = check_web(self.store, SUBJECT, self.save('<p>Example Pumps AS produces industrial pumps.</p>'))
        self.assertEqual({d['claim']['scope'] for d in decisions}, {'registry_linked_html'})
        self.audit(decisions)

    def test_existing_operator_proof_still_audits_unchanged(self):
        html = '<footer>Copyright Example Pumps AS. Org.nr. 923 609 016 post@acme-site.test</footer>'
        decisions = check_web(self.store, SUBJECT, self.save(html))
        self.assertEqual([d['field'] for d in decisions], ['verified_website'])
        self.audit(decisions)

    def test_hand_built_claim_matches_the_maker_claim(self):
        # Guards the forgery helper: the same claim built without the maker must audit.
        html = BLOCK
        sid = self.save(html, '/')
        self.audit(self.forged_site(sid, html, BLOCK))
        maker = check_web(self.store, SUBJECT, sid)
        self.assertEqual(maker[0]['claim']['claim_id'], self.forged_site(sid, html, BLOCK)[0]['claim']['claim_id'])

    # negative controls: an auditor that sees only the retained bytes must refuse

    def test_every_attack_is_refused_by_the_audit_while_the_twin_passes(self):
        sid = self.save(BLOCK, '/kontakt')
        self.audit(self.forged_site(sid, BLOCK, BLOCK, path='/kontakt'))
        for label, (html, host) in attacks().items():
            match = re.search(r'<(footer|div|p|q)\b.*</\1>', html, re.S) or re.search(r'<p\b.*</p>', html, re.S)
            span = match.group(0) if match else html
            sid = self.save(html, '/kontakt', host)
            with self.assertRaisesRegex(ValueError, 'anchor mismatch', msg=label):
                self.audit(self.forged_site(sid, html, span, host, '/kontakt'))

    def test_attacks_on_a_registry_host_page_lose_the_website_but_not_the_audit_of_linked_claims(self):
        self.anchor = self.anchor_for(NAME, HOST)
        html = '<p>Customer story: ' + ROW + '</p>'
        sid = self.save(html, '/kontakt')
        with self.assertRaisesRegex(ValueError, 'lacks legal operator evidence'):
            self.audit(self.forged_site(sid, html, html, path='/kontakt'))

    # forged claims on a page that does prove ownership

    def test_wrong_block_span_is_refused(self):
        html = '<footer>' + BLOCK + '<p>Mer</p></footer><h1>Tittel</h1>'
        sid = self.save(html)
        self.audit(self.forged_site(sid, html, BLOCK))
        for span in ('<footer>' + BLOCK + '<p>Mer</p></footer>', '<p>Mer</p>', '<h1>Tittel</h1>'):
            with self.assertRaises(ValueError, msg=span):
                self.audit(self.forged_site(sid, html, span))
        good = self.forged_site(sid, html, BLOCK)
        good[0]['evidence']['locator']['html_end'] += 1
        with self.assertRaisesRegex(ValueError, 'span'):
            self.audit(good)

    def test_forged_claim_on_another_host_is_refused(self):
        contact = self.save(BLOCK, '/kontakt')
        foreign_html = '<p>Example Pumps AS produces industrial pumps.</p>'
        foreign = self.save(foreign_html, '/produkter', host='other-site.test', operator_snapshot_id=contact)
        with self.assertRaisesRegex(ValueError, 'source chain mismatch'):
            self.audit(self.forged_site(foreign, foreign_html, foreign_html, 'other-site.test', '/produkter',
                                        field='product_service', value=foreign_html.replace('<p>', '').replace('</p>', '')))
        foreign_block = self.save(BLOCK, '/kontakt', host='other-site.test')
        with self.assertRaisesRegex(ValueError, 'anchor mismatch'):
            self.audit(self.forged_site(foreign_block, BLOCK, BLOCK, 'other-site.test', '/kontakt'))

    def test_missing_or_mismatched_ownership_snapshot_is_refused(self):
        html = '<p>Example Pumps AS produces industrial pumps.</p>'
        other_anchor = self.anchor_for('Example Pumps AS', 'registered-elsewhere.test')
        for owner in ('0' * 64, None):
            if owner is None:
                owner = self.save(BLOCK, '/kontakt', ownership_anchor_snapshot_id=other_anchor)
            sid = self.save(html, '/produkter', operator_snapshot_id=owner)
            forged = self.forged_site(sid, html, html, path='/produkter', field='product_service',
                                      value='Example Pumps AS produces industrial pumps.')
            with self.assertRaises((ValueError, OSError)):
                self.audit(forged)

    def test_ownership_receipt_fields_are_enforced(self):
        html = '<p>Example Pumps AS produces industrial pumps.</p>'
        for change in ({'http_status': 404}, {'robots_checked': False}, {'organisation_number': '999999999'},
                       {'source_class': 'nav_jobs'}):
            owner = self.save(BLOCK, '/kontakt', **change)
            sid = self.save(html, '/produkter', operator_snapshot_id=owner)
            forged = self.forged_site(sid, html, html, path='/produkter', field='product_service',
                                      value='Example Pumps AS produces industrial pumps.')
            with self.assertRaises(ValueError, msg=str(change)):
                self.audit(forged)

    def test_tampered_legal_name_wrong_scope_and_wrong_value_are_refused(self):
        sid = self.save(BLOCK, '/')
        for change, pattern in (({'legal_name': 'Example Pumps'}, 'locator mismatch'),
                                ({'scope': 'registry_linked_html'}, 'canonical identity'),
                                ({'method': 'registry_linked_subject_html_v1'}, 'registry host linkage'),
                                ({'scope': 'company_owned_catalogue', 'method': 'scoped_catalogue_html_v2'}, ''),
                                ({'value': 'https://www.acme-site.test/kontakt/'}, 'canonical identity'),
                                ({'value': 'https://acme-site.test/'}, 'canonical identity'),
                                ({'operator': False}, 'operator evidence'),
                                ({'family': 'business_products'}, 'canonical identity')):
            with self.assertRaisesRegex(ValueError, pattern, msg=str(change)):
                self.audit(self.forged_site(sid, BLOCK, BLOCK, **change))

    def test_verified_website_needs_the_block_on_the_page_itself(self):
        # The maker emits verified_website only when the ownership page is the page itself.
        contact = self.save(BLOCK, '/kontakt')
        html = '<footer>' + BLOCK + '</footer>'
        sid = self.save(html, '/om-oss', operator_snapshot_id=contact)
        self.assertEqual(check_web(self.store, SUBJECT, sid), [])
        with self.assertRaisesRegex(ValueError, 'not on the ownership page'):
            self.audit(self.forged_site(sid, html, BLOCK, path='/om-oss'))

    def test_block_proof_never_authorises_registry_linked_or_catalogue_routes(self):
        html = BLOCK + '<p>Example Pumps AS produces industrial pumps.</p>'
        sid = self.save(html)
        forged = self.forged_site(sid, html, '<p>Example Pumps AS produces industrial pumps.</p>', field='product_service',
                                  value='Example Pumps AS produces industrial pumps.', family='business_products',
                                  scope='registry_linked_html', method='registry_linked_subject_html_v1')
        with self.assertRaisesRegex(ValueError, 'registry host linkage'):
            self.audit(forged)
        catalogue = self.forged_site(sid, html, '<p>Example Pumps AS produces industrial pumps.</p>',
                                     field='product_service', family='business_products',
                                     scope='company_owned_catalogue', method='scoped_catalogue_html_v2',
                                     value={'name': 'Pumper', 'source_url': 'https://www.acme-site.test/produkter/pumper'})
        with self.assertRaisesRegex(ValueError, 'seller contract'):
            self.audit(catalogue)


if __name__ == '__main__':
    unittest.main()
