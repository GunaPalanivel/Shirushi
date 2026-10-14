"""Legal contact blocks on discovered sites: positive controls and the attacks that must stay rejected."""
import json
import tempfile
import unittest
from pathlib import Path

from shirushi.html_sources import operator_proof
from shirushi.live import covered_families
from shirushi.snapshots import SnapshotStore, digest
from shirushi.web_sources import check_web

SUBJECT = '923609016'
NAME = 'Example Pumps AS'
HOST = 'www.acme-site.test'


def proof(html, host=HOST, path='/kontakt'):
    return operator_proof(html.encode(), SUBJECT, NAME, '', 'https://' + host + path)


class LegalContactBlockProofTests(unittest.TestCase):
    def test_pipe_separated_legal_footer_with_own_domain_email_proves_ownership(self):
        html = ('<footer><p>Example Pumps AS | Orgnr. 923 609 016 | Storgata 1, 0123 Oslo | '
                'kontakt@acme-site.test</p></footer>')
        result = proof(html)
        self.assertEqual(result['kind'], 'legal_contact_block')
        self.assertIn('Orgnr. 923 609 016', result['text'])
        self.assertEqual(html[result['start']:result['end']].startswith('<p>'), True)

    def test_subdomain_and_mailto_link_inside_the_block_corroborate(self):
        block = '<p>Example Pumps AS, org.nr 923609016, <a href="mailto:post@acme-site.test">Send e-post</a></p>'
        self.assertEqual(proof(block, 'shop.acme-site.test')['kind'], 'legal_contact_block')
        parent = '<p>Example Pumps AS, org.nr 923609016, post@shop.acme-site.test</p>'
        self.assertEqual(proof(parent, 'acme-site.test')['kind'], 'legal_contact_block')

    def test_links_and_url_text_to_the_own_host_are_not_a_tie(self):
        # Any listing on a site can carry an absolute link to that same site (a tenant or member card),
        # so only a mailbox at the site's domain or the name~domain equality ties a block to its site.
        for link in ('<a href="https://www.acme-site.test/">our site</a>', '<a href="/kontakt">Kontakt</a>',
                     'www.acme-site.test', '<a href="https://www.acme-site.test/firma/example-pumps">Detaljer</a>'):
            self.assertIsNone(proof('<div>Example Pumps AS org.nr. 923609016 ' + link + '</div>'), link)

    def test_domain_equal_to_legal_name_corroborates_without_email(self):
        html = '<footer>Example Pumps AS · org.nr. 923 609 016 · del av Pump Group</footer>'
        self.assertEqual(proof(html, 'www.examplepumps.no')['kind'], 'legal_contact_block')
        self.assertEqual(proof(html, 'example-pumps.no')['kind'], 'legal_contact_block')
        for host in ('examplepumpsnorge.no', 'ex-pumps.no', 'pumps.no', HOST):
            self.assertIsNone(proof(html, host), host)

    def test_norwegian_letters_fold_in_the_name_domain_tie(self):
        name = 'Kragerø Installasjon AS'
        html = '<p>Kragerø Installasjon AS Org.nr: 923609016 Bråteveien 7, 3772 Kragerø</p>'
        self.assertEqual(operator_proof(html.encode(), SUBJECT, name, '', 'https://krageroinstallasjon.no/om-oss')['kind'],
                         'legal_contact_block')

    def test_relationship_words_far_from_the_identity_do_not_block_a_long_site_footer(self):
        padding = ' '.join(['Navigasjon'] * 14)
        footer = ('<footer>Åpningstider man-fre 08-16 (kveldsåpent for kunder på torsdager) ' + padding +
                  ' Her finner du oss: Example Pumps AS Storgata 1, 0123 Oslo post@acme-site.test Org.nr. 923609016</footer>')
        self.assertEqual(proof(footer)['kind'], 'legal_contact_block')
        near = footer.replace('Her finner du oss:', 'Kunde:')
        self.assertIsNone(proof(near))
        number_side = footer.replace('Org.nr. 923609016', 'Kunde Org.nr. 923609016')
        self.assertIsNone(proof(number_side))

    def test_existing_operator_proof_kinds_keep_priority(self):
        html = '<footer>Copyright Example Pumps AS. Org.nr. 923 609 016 post@acme-site.test</footer>'
        self.assertEqual(proof(html)['kind'], 'operator')

    def attacks(self):
        footer = 'Example Pumps AS | Orgnr. 923 609 016 | Storgata 1, 0123 Oslo | kontakt@acme-site.test'
        return {
            'supplier listing on a foreign host': ('<p>Our suppliers: Example Pumps AS, org.nr. 923609016, '
                                                  'post@example-pumps.test</p>', 'other-site.test'),
            'listing without own-site tie': ('<p>Example Pumps AS, org.nr. 923609016, post@example-pumps.test</p>',
                                             'other-site.test'),
            'directory host': ('<p>' + footer + '</p>', 'www.proff.no'),
            'directory subdomain': ('<p>' + footer.replace('acme-site.test', 'proff.no') + '</p>', 'bedrift.proff.no'),
            'group parent footer, other number': ('<footer>Parent AS | Orgnr. 990 888 213 | post@acme-site.test'
                                                  '</footer><p>Example Pumps AS is a subsidiary.</p>', HOST),
            'blockquote': ('<blockquote><p>' + footer + '</p></blockquote>', HOST),
            'quote element': ('<q>' + footer + '</q>', HOST),
            'hidden attribute': ('<p hidden>' + footer + '</p>', HOST),
            'aria hidden': ('<p aria-hidden="true">' + footer + '</p>', HOST),
            'display none': ('<p style="display: none">' + footer + '</p>', HOST),
            'mail at another domain': ('<p>Example Pumps AS | Orgnr. 923 609 016 | post@other-mail.test</p>', HOST),
            'name without number': ('<p>Example Pumps AS | Storgata 1 | kontakt@acme-site.test</p>', HOST),
            'number without name': ('<p>Orgnr. 923 609 016 | Storgata 1 | kontakt@acme-site.test</p>', HOST),
            'label-less number': ('<p>Example Pumps AS | 923 609 016 | kontakt@acme-site.test</p>', HOST),
            'vat label only': ('<p>Example Pumps AS | VAT no. 923 609 016 | kontakt@acme-site.test</p>', HOST),
            'second number': ('<p>' + footer + ' | Org.nr. 990 888 213</p>', HOST),
            'wrong number': ('<p>' + footer.replace('923 609 016', '990 888 213') + '</p>', HOST),
            'other legal entity named': ('<p>' + footer + ' | Betalingsleverandor Payments AS</p>', HOST),
            'agency credit': ('<p>Design av Webbyra AS | Example Pumps AS Orgnr. 923 609 016 | '
                              'post@acme-site.test</p>', HOST),
            'customer context': ('<p>Customer story: ' + footer + '</p>', HOST),
            'negated': ('<p>Not ' + footer + '</p>', HOST),
            'question': ('<p>' + footer + '?</p>', HOST),
            'phone only': ('<p>Example Pumps AS | Orgnr. 923 609 016 | <a href="tel:+4722222222">22 22 22 22</a></p>',
                           HOST),
            'old registered name': ('<p>Old Pumps AS | Orgnr. 923 609 016 | kontakt@acme-site.test</p>', HOST),
            'name without legal form': ('<p>Example Pumps | Orgnr. 923 609 016 | kontakt@acme-site.test</p>', HOST),
            'webmail parent of a shared host': ('<p>Example Pumps AS | Orgnr. 923 609 016 | someone@wixsite.com</p>',
                                                'example.wixsite.com'),
            'oversized div': ('<div>' + footer + ' ' + 'x ' * 300 + '</div>', HOST),
            'oversized footer': ('<footer>' + footer + ' ' + 'x ' * 800 + '</footer>', HOST),
        }

    def test_unlisted_relationship_phrases_and_forms_are_rejected(self):
        # Found by an independent adversarial review: each block has an own-domain mailbox.
        ident = 'Example Pumps AS, org.nr. 923609016'
        for lead in ('Arbeidsgiver: ', 'Pressekontakt: ', 'Leietaker: ', 'Forhandler: ', 'Prosjekt: nytt nettsted for ',
                     'Faktura sendes til ', 'Eies av ', 'Vi har kjøpt ', 'Konkursbo etter ', 'Employer: ', 'Tenant: '):
            self.assertIsNone(proof('<p>' + lead + ident + ', post@acme-site.test</p>'), lead)
        for other in ('Danske Partnerselskap ApS', 'Schweiz Holding AG', 'Kari Nordmann ENK', 'Fjord Drift KS'):
            self.assertIsNone(proof('<p>' + ident + ' | ' + other + ' | post@acme-site.test</p>'), other)

    def test_mail_domain_must_end_the_address_and_platforms_do_not_tie(self):
        ident = 'Example Pumps AS | Orgnr. 923 609 016 | '
        self.assertIsNone(proof('<p>' + ident + 'post@acme-site.test@other-mail.test</p>', 'acme-site.test'))
        self.assertIsNone(proof('<p>' + ident + 'support@pages.dev</p>', 'victim.pages.dev'))
        self.assertIsNone(proof('<p>' + ident + 'post@bergen.no</p>', 'victim.bergen.no'))

    def test_name_domain_tie_needs_the_bare_registrable_host_in_ascii(self):
        footer = '<footer>Example Pumps AS · org.nr. 923 609 016</footer>'
        self.assertEqual(proof(footer, 'examplepumps.no')['kind'], 'legal_contact_block')
        self.assertEqual(proof(footer, 'www.examplepumps.no')['kind'], 'legal_contact_block')
        for host in ('foo.examplepumps.no', 'shop.www.examplepumps.no', 'examplеpumps.no',
                     'examplepumps​.no', 'examplepumpsł.no'):
            self.assertIsNone(proof(footer, host), host)

    PLATFORMS = ('medium.com', 'substack.com', 'notion.site', 'notion.so', 'linktr.ee', 'sites.google.com',
                 'mystrikingly.com', 'strikingly.com', 'weebly.com', 'jimdosite.com', 'jimdofree.com', 'carrd.co',
                 'squarespace.com', 'wixsite.com', 'wix.com', 'webflow.io', 'godaddysites.com', 'business.site',
                 'github.io', 'gitlab.io', 'netlify.app', 'vercel.app', 'pages.dev', 'herokuapp.com', 'blogspot.com',
                 'wordpress.com', 'tumblr.com', 'ucoz.com', '000webhostapp.com')

    def test_tenant_on_a_hosting_platform_is_never_tied_by_a_platform_mailbox(self):
        ident = 'Example Pumps AS | Orgnr. 923 609 016 | '
        for platform in self.PLATFORMS:
            for mailbox in ('x@' + platform, 'x@victim.' + platform):
                self.assertIsNone(proof('<p>' + ident + mailbox + '</p>', 'victim.' + platform), (platform, mailbox))

    def test_platform_root_host_never_proves_even_when_the_company_is_named_like_it(self):
        for platform in self.PLATFORMS:
            name = platform.split('.')[0].title() + ' AS'
            html = '<p>' + name + ' | Orgnr. 923 609 016 | post@' + platform + '</p>'
            for host in (platform, 'www.' + platform):
                self.assertIsNone(operator_proof(html.encode(), SUBJECT, name, '', 'https://' + host + '/@tenant'),
                                  (platform, host))

    def test_public_sector_suffix_is_checked_before_domain_equality(self):
        ident = 'Example Pumps AS | Orgnr. 923 609 016 | '
        for host, mailbox in (('victim.vestland.no', 'post@vestland.no'), ('victim.vestland.no', 'post@victim.vestland.no'),
                              ('victim.kommune.no', 'post@kommune.no'), ('steinkjer.kommune.no', 'x@steinkjer.kommune.no'),
                              ('victim.fylke.no', 'post@victim.fylke.no'), ('bergen.no', 'post@bergen.no'),
                              ('victim.bergen.no', 'post@bergen.no')):
            self.assertIsNone(proof('<p>' + ident + mailbox + '</p>', host), (host, mailbox))
        self.assertIsNone(proof('<footer>Example Pumps AS org.nr. 923 609 016</footer>', 'examplepumps.vestland.no'))

    def test_mailbox_tie_is_registrable_domain_equality_on_ordinary_domains(self):
        ident = 'Example Pumps AS | Orgnr. 923 609 016 | '
        for host, mailbox in (('www.acme-site.test', 'a@acme-site.test'), ('acme-site.test', 'a@mail.acme-site.test'),
                              ('shop.acme-site.test', 'a@acme-site.test'), ('acme-site.com.no', 'a@acme-site.com.no')):
            self.assertEqual(proof('<p>' + ident + mailbox + '</p>', host)['kind'], 'legal_contact_block', host)
        for host, mailbox in (('acme-site.test', 'a@other-site.test'), ('acme-site.com.no', 'a@com.no'),
                              ('a.acme-site.test', 'a@b.other-site.test')):
            self.assertIsNone(proof('<p>' + ident + mailbox + '</p>', host), host)

    def test_name_domain_tie_is_limited_to_registrable_tlds_without_an_own_mailbox(self):
        footer = '<footer>Example Pumps AS · org.nr. 923 609 016</footer>'
        for tld in ('no', 'com', 'org', 'net', 'eu'):
            self.assertEqual(proof(footer, 'examplepumps.' + tld)['kind'], 'legal_contact_block', tld)
        for tld in ('shop', 'store', 'xyz', 'top', 'online', 'site', 'cc', 'ru'):
            self.assertIsNone(proof(footer, 'examplepumps.' + tld), tld)
        mailbox = '<footer>Example Pumps AS · org.nr. 923 609 016 · post@examplepumps.shop</footer>'
        self.assertEqual(proof(mailbox, 'examplepumps.shop')['kind'], 'legal_contact_block')

    def test_every_attack_is_rejected(self):
        for label, (html, host) in self.attacks().items():
            self.assertIsNone(proof(html, host), label)

    def test_proof_needs_the_page_url(self):
        html = '<p>Example Pumps AS | Orgnr. 923 609 016 | kontakt@acme-site.test</p>'
        self.assertIsNone(operator_proof(html.encode(), SUBJECT, NAME))
        self.assertIsNone(operator_proof(html.encode(), SUBJECT, NAME, '', ''))

    def test_every_attack_has_a_working_positive_twin(self):
        # Guards against rejection for an unrelated reason: the unmodified footer must prove.
        footer = ('<p>Example Pumps AS | Orgnr. 923 609 016 | Storgata 1, 0123 Oslo | '
                  'kontakt@acme-site.test</p>')
        self.assertEqual(proof(footer)['kind'], 'legal_contact_block')
        self.assertIsNone(proof(footer, 'www.proff.no'))
        self.assertIsNone(proof('<blockquote>' + footer + '</blockquote>'))


class LegalContactBlockPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(Path(self.temp.name))
        raw = json.dumps({'organisasjonsnummer': SUBJECT, 'navn': NAME, 'hjemmeside': 'registered-elsewhere.test'}).encode()
        url = 'https://data.brreg.no/enhetsregisteret/api/enheter/' + SUBJECT
        self.anchor = self.store.save(raw, {'organisation_number': SUBJECT, 'source_class': 'brreg_entity',
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

    FOOTER = ('<footer><p>Example Pumps AS | Orgnr. 923 609 016 | Storgata 1, 0123 Oslo | '
              'kontakt@acme-site.test</p></footer>')

    def test_contact_page_block_anchors_discovered_site_for_explicit_named_claims(self):
        contact = self.save('<h1>Kontakt</h1>' + self.FOOTER, '/kontakt')
        content = self.save('<p>Example Pumps AS produces industrial pumps.</p>', '/produkter',
                            operator_snapshot_id=contact)
        decisions = check_web(self.store, SUBJECT, content)
        self.assertEqual([d['field'] for d in decisions], ['product_service'])
        self.assertEqual({d['claim']['scope'] for d in decisions}, {'company_owned_html'})
        self.assertEqual({d['evidence']['extraction_method'] for d in decisions}, {'explicit_subject_html_v1'})
        self.assertEqual(covered_families([d['claim'] for d in decisions]), {'business_products'})

    def test_proof_page_itself_yields_the_verified_website_with_the_block_as_span(self):
        decisions = check_web(self.store, SUBJECT, self.save(self.FOOTER, '/'))
        site = next(d for d in decisions if d['field'] == 'verified_website')
        self.assertEqual(site['claim']['value'], 'https://www.acme-site.test/')
        self.assertIn('Orgnr. 923 609 016', site['evidence']['claim_span'])
        self.assertIn('Example Pumps AS', site['evidence']['claim_span'])

    def test_proof_does_not_leave_the_host_of_the_ownership_page(self):
        contact = self.save(self.FOOTER, '/kontakt')
        foreign = self.save('<p>Example Pumps AS produces industrial pumps.</p>', '/produkter',
                            host='other-site.test', operator_snapshot_id=contact)
        with self.assertRaisesRegex(ValueError, 'proof mismatch'):
            check_web(self.store, SUBJECT, foreign)

    def test_rejected_blocks_keep_the_discovery_not_anchored_error(self):
        for html, host in (('<p>Our suppliers: Example Pumps AS, org.nr. 923609016, post@example-pumps.test</p>'
                            '<p>Example Pumps AS produces industrial pumps.</p>', 'other-site.test'),
                           ('<p>Example Pumps AS | Orgnr. 923 609 016 | kontakt@acme-site.test</p>'
                            '<p>Example Pumps AS produces industrial pumps.</p>', 'www.proff.no'),
                           ('<blockquote>' + self.FOOTER + '</blockquote><p>Example Pumps AS produces pumps.</p>', HOST)):
            with self.assertRaisesRegex(ValueError, 'not anchored'):
                check_web(self.store, SUBJECT, self.save(html, host=host))

    def test_path_tenant_platform_never_yields_a_platform_root_website_claim(self):
        block = '<p>Example Pumps AS | Orgnr. 923 609 016 | post@medium.com</p>'
        for host in ('medium.com', 'victim.mystrikingly.com', 'victim.vestland.no'):
            with self.assertRaisesRegex(ValueError, 'not anchored'):
                check_web(self.store, SUBJECT, self.save(block, '/@example-pumps', host=host))

    def test_registry_linked_routes_stay_unavailable_to_a_contact_block_proof(self):
        # Declared host differs, so registry_host is False: article and section routes must not run.
        html = (self.FOOTER + '<p>Example Pumps AS ble etablert i 1997. Vi utfører vedlikehold.</p>')
        decisions = check_web(self.store, SUBJECT, self.save(html))
        self.assertEqual({d['claim']['scope'] for d in decisions}, {'company_owned_html'})


if __name__ == '__main__':
    unittest.main()
