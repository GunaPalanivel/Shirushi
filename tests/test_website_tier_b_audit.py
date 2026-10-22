"""Independent audit of the registry-corroborated website claim: it accepts what the maker publishes and
rejects every hand-forged claim, whether the page, the registry row or the evidence was tampered with."""
import copy
import csv
import gzip
import hashlib
import io
import json
import re
import tempfile
import time
import unittest
from pathlib import Path

from shirushi.registry import acquire_batch
from shirushi.snapshots import SnapshotStore, digest
from shirushi.web_sources import check_web
from shirushi_eval import website_support
from shirushi_eval.support import SourceAudit

SUBJECT, NAME = '923609016', 'EXAMPLE PUMPS AS'
FILLER = ('<p>Vi leverer pumper, tjenester og vedlikehold til bedrifter i hele landet, og har gjort det i mange år. '
          'Ta kontakt for en uforpliktende prat om dine behov.</p>')
SCOPE, METHOD = 'registry_declared_host_name_gate', 'registry_host_corroboration_v1'
EMAIL = 'post@example.no'


def mail(email=EMAIL, domain='example.no'):
    return {'kind': 'email_domain', 'registry_field': 'epostadresse', 'registry_value': email, 'domain': domain}


def label(host, name=NAME):
    return {'kind': 'name_host_label', 'registry_field': 'navn', 'registry_value': name, 'domain': host}


OWN = '<footer>Org.nr 923 609 016</footer>'


def doc(title='Pumper og service', body=FILLER + OWN, head='', h1=''):
    return ('<!doctype html><html lang="no"><head><title>' + title + '</title>' + head + '</head><body>'
            + (('<h1>' + h1 + '</h1>') if h1 else '') + body + '</body></html>')


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SnapshotStore(Path(self.temp.name))

    def anchor(self, website='example.no', email=EMAIL, name=NAME, subject=SUBJECT, address=None):
        row = {'organisasjonsnummer': subject, 'navn': name}
        if address is not None:
            row['forretningsadresse'] = address
        if website is not None:
            row['hjemmeside'] = website
        if email is not None:
            row['epostadresse'] = email
        raw = json.dumps(row).encode()
        return self.store.save(raw, dict(organisation_number=subject, source_class='brreg_entity',
            source_url='https://data.brreg.no/enhetsregisteret/api/enheter/' + subject, effective_url=
            'https://data.brreg.no/enhetsregisteret/api/enheter/' + subject, http_status=200, sha256=digest(raw),
            retrieved_at='2026-10-10T08:00:00Z'))

    def page(self, html, host='example.no', path='/', anchor=None, receipt=None, **registry):
        anchor = anchor or self.anchor(**registry)
        raw = html.encode()
        extra = receipt or {}
        meta = dict(organisation_number=SUBJECT, source_class='company_owned', source_url='https://' + host + path,
                    effective_url='https://' + host + path, content_type='text/html', http_status=200,
                    sha256=digest(raw), declared_host=host, source_origin=host, robots_checked=True,
                    retrieved_at='2026-10-10T08:00:00Z', ownership_anchor_snapshot_id=anchor)
        meta.update(extra)
        return self.store.save(raw, meta), anchor

    def produce(self, html, **kwargs):
        sid, anchor = self.page(html, **kwargs)
        found = [d for d in check_web(self.store, SUBJECT, sid) if d['field'] == 'verified_website']
        return found, sid, anchor

    def audit(self, claim, evidence):
        refs = {ref: evidence for ref in claim['evidence_ids']} or {evidence['id']: evidence}
        SourceAudit(self.store.root, [SUBJECT]).claim(SUBJECT, claim, refs)

    def accepts(self, claim, evidence, why=''):
        self.audit(claim, evidence)

    def rejects(self, claim, evidence, why=''):
        with self.assertRaises(ValueError, msg=why):
            self.audit(claim, evidence)

    def forge(self, sid, anchor, html, host='example.no', website='example.no', email=EMAIL, name=NAME,
              corroboration=None, kind='org_number', part=None, span=None, score=0.95, path='/'):
        """A tier-B claim assembled by hand from the page bytes, independent of the maker."""
        part = part or kind
        if span is None:
            span = OWN
        start = max(html.find(span), 0)
        claim_id = hashlib.sha256(json.dumps([SUBJECT, 'verified_website', SCOPE, None, None], ensure_ascii=False,
                                             sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        evidence_id = sid + ':' + claim_id
        claim = {'claim_id': claim_id, 'field': 'verified_website', 'value': 'https://' + host + '/', 'scope': SCOPE,
                 'family': 'website_owned_profiles', 'item_key': None, 'period': None, 'availability': 'available',
                 'evidence_ids': [evidence_id], 'freshness': 'live_source'}
        evidence = {'id': evidence_id, 'snapshot_id': sid, 'source_url': 'https://' + host + path,
                    'source_class': 'company_owned', 'source_origin': host, 'retrieved_at': '2026-10-10T08:00:00Z',
                    'content_sha256': digest(html.encode()), 'claim_span': span, 'extraction_method': METHOD,
                    'locator': {'html_start': start, 'html_end': start + len(span), 'identity_part': part},
                    'identity_assessment': {
                        'method': METHOD, 'path': 'registry_corroborated', 'status': 'exact', 'score': score,
                        'reasons': ['registry row corroborates the registered host'],
                        'corroboration': [mail(email, 'example.no')] if corroboration is None else corroboration,
                        'anchor_snapshot_id': anchor, 'legal_name': name, 'registry_website': website,
                        'page_url': 'https://' + host + path, 'identifier': {'kind': kind, 'part': part},
                        'visible_text_sha256': hashlib.sha256(
                            website_support.Page(html.encode()).visible.encode('utf-8')).hexdigest()}}
        return claim, evidence

    def forged(self, html, host='example.no', registry_email=EMAIL, website='example.no', name=NAME, address=None, **kwargs):
        sid, anchor = self.page(html, host=host, website=website, email=registry_email, name=name, address=address)
        return self.forge(sid, anchor, html, host=host, website=website, email=registry_email, name=name, **kwargs)


class PositiveTests(Base):
    def test_valid_forge_is_accepted_so_every_negative_below_isolates_one_defect(self):
        self.accepts(*self.forged(doc()))

    def test_maker_claims_are_accepted(self):
        cases = (
            (doc(), {}, 'email only'),
            (doc(), dict(website='examplepumps.no', email=None, host='examplepumps.no'), 'name label only'),
            (doc(), dict(website='examplepumps.no', email='post@examplepumps.no', host='examplepumps.no'), 'both'),
            (doc(title='Example Pumps AS - Pumper'), {}, 'named title'),
            (doc(title='Pumper', body=FILLER + '<footer>Example Pumps AS</footer>'), {}, 'legal name in a footer'),
            (doc(), dict(host='www.example.no'), 'www alias page'),
            (doc(), dict(email='Post@Kontor.Example.NO '), 'mail on a subdomain, mixed case, padded'),
            ('<html><body><h1>Example pumper</h1>' + FILLER + OWN + '</body></html>', {}, 'heading only, no title'),
            (doc(), dict(path='/om-oss'), 'sub page of the registered host'),
            (doc(), dict(website='poweroffice.no', email='post@poweroffice.no', host='poweroffice.no',
                         name='POWEROFFICE AS'), 'software vendor named after its own host'),
            (doc(), dict(website='http://www.example.no/', host='example.no'), 'registry website with scheme and www'),
            (doc(), dict(website='https://EXAMPLE.no'), 'registry website uppercase'),
        )
        for html, kwargs, why in cases:
            found, sid, anchor = self.produce(html, **kwargs)
            self.assertEqual(len(found), 1, why)
            self.assertEqual(found[0]['evidence']['extraction_method'], METHOD, why)
            self.accepts(found[0]['claim'], found[0]['evidence'], why)

    def test_org_number_in_title_and_body_publishes_the_body_element(self):
        html = ('<!doctype html><html><head><title>Org.nr 923 609 016</title></head><body>'
                + FILLER + '<footer>Org.nr 923 609 016</footer></body></html>')
        found, _, _ = self.produce(html)
        self.assertEqual(len(found), 1)
        loc = found[0]['evidence']['locator']
        self.assertNotIn('<title>', html[loc['html_start']:loc['html_end']])
        self.accepts(found[0]['claim'], found[0]['evidence'])

    def test_implicitly_closed_org_number_element_is_independently_supported(self):
        html = ('<!doctype html><html><head><title>T</title></head><body>'
                + FILLER + '<div><p>Org.nr 923 609 016</div></p></body></html>')
        found, _, _ = self.produce(html)
        self.assertEqual(len(found), 1)
        self.accepts(found[0]['claim'], found[0]['evidence'])

    def test_org_number_only_inside_title_is_not_published(self):
        html = ('<!doctype html><html><head><title>Org.nr 923 609 016</title></head><body>'
                + FILLER + '</body></html>')
        found, _, _ = self.produce(html)
        self.assertEqual(found, [])

    def test_both_scores_and_the_corroboration_order_are_re_derived(self):
        both = dict(website='examplepumps.no', email='post@examplepumps.no', host='examplepumps.no')
        found, _, _ = self.produce(doc(title='Pumper', body=FILLER + '<footer>Example Pumps AS</footer>'), **both)
        evidence = found[0]['evidence']
        self.assertEqual(evidence['identity_assessment']['score'], 0.95)
        self.assertEqual([c['kind'] for c in evidence['identity_assessment']['corroboration']],
                         ['email_domain', 'name_host_label'])
        swapped = copy.deepcopy(evidence)
        swapped['identity_assessment']['corroboration'].reverse()
        self.rejects(found[0]['claim'], swapped, 'order')
        lowered = copy.deepcopy(evidence)
        lowered['identity_assessment']['score'] = 0.9
        self.rejects(found[0]['claim'], lowered, 'two corroborations score 0.95')

    def test_score_is_ninety_five_for_numbers_title_heading_or_two_corroborations_else_ninety(self):
        footer = doc(title='Pumper', body=FILLER + '<footer>Example Pumps AS</footer>')
        for html, expected in ((footer, 0.9), (doc(title='Example Pumps AS'), 0.95),
                               (doc(title='Pumper', h1='Example Pumps AS'), 0.95),
                               (doc(title='Pumper', body=FILLER + '<footer>Org.nr 923 609 016</footer>'), 0.95),
                               (doc(title='Pumper', body=FILLER + '<footer>© 2026 Example Pumps AS</footer>'), 0.9)):
            found, sid, anchor = self.produce(html)
            self.assertEqual(found[0]['evidence']['identity_assessment']['score'], expected, html)
            self.accepts(found[0]['claim'], found[0]['evidence'])
            forged = copy.deepcopy(found[0]['evidence'])
            forged['identity_assessment']['score'] = 0.9 if expected == 0.95 else 0.95
            self.rejects(found[0]['claim'], forged, 'wrong score for ' + html[:80])

    def test_existing_operator_route_still_audits_and_outranks_the_corroboration_claim(self):
        html = doc(title='Example Pumps AS', body=FILLER + '<footer>© 2026 Example Pumps AS. Org.nr 923 609 016</footer>')
        found, sid, anchor = self.produce(html)
        self.assertEqual([d['claim']['scope'] for d in found], ['company_owned_html'])
        self.accepts(found[0]['claim'], found[0]['evidence'])
        # a hand-made corroboration claim on the same page is refused: the operator proof owns the page
        self.rejects(*self.forge(sid, anchor, html, span='<footer>© 2026 Example Pumps AS. Org.nr 923 609 016</footer>'),
                     'operator proof present')


class RegistryRowTests(Base):
    def test_no_valid_corroboration_in_the_registry_row(self):
        cases = (
            ('example.no', 'example@gmail.com', 'example.no', 'free mail'),
            ('example.no', 'post@online.no', 'example.no', 'internet provider mail'),
            ('example.no', 'post@other.no', 'example.no', 'other domain'),
            ('example.no', None, 'example.no', 'no mail'),
            ('example.no', 'not an email', 'example.no', 'not an address'),
            ('example.no', 'a@b@example.no', 'example.no', 'two at signs'),
            ('example.no', 'a@example.no, b@example.no', 'example.no', 'two addresses'),
            ('example.no', 'post@example.no.', 'example.no', 'trailing dot'),
            ('example.no', 'post@exampel.no', 'example.no', 'near miss'),
            ('example.no', 'post@example.com', 'example.no', 'other tld'),
            ('shop.wixsite.com', 'x@shop.wixsite.com', 'shop.wixsite.com', 'platform tenant mailbox'),
            ('wixsite.com', 'x@wixsite.com', 'wixsite.com', 'platform'),
            ('bergen.kommune.no', 'post@bergen.kommune.no', 'bergen.kommune.no', 'public sector'),
            ('tripletex.no', 'post@tripletex.no', 'tripletex.no', 'accounting software'),
            ('proff.no', 'post@proff.no', 'proff.no', 'directory'),
            ('facebook.com', 'a@facebook.com', 'facebook.com', 'social'),
            ('telenor.no', 'x@telenor.no', 'telenor.no', 'telco'),
            ('gmail.com', 'x@gmail.com', 'gmail.com', 'free mail host'),
            ('example.co.uk', 'x@other.co.uk', 'example.co.uk', 'second level suffix is not a domain'),
            ('example.no', 'post@kommune.no', 'example.no', 'public suffix mailbox'),
            ('example.no', 'post@pwc.no', 'example.no', 'accountant'),
            ('pwc.no', 'post@pwc.no', 'pwc.no', 'accountant host'),
            ('example.no', 'post@mail.tripletex.no', 'example.no', 'subdomain of a listed vendor'),
        )
        for website, email, host, why in cases:
            html = doc()
            sid, anchor = self.page(html, host=host, website=website, email=email)
            for lie in ([mail(email or '', host)], [mail(email or '', 'example.no')], [label(host)]):
                self.rejects(*self.forge(sid, anchor, html, host=host, website=website, email=email,
                                         corroboration=lie), why + ' ' + str(lie[0]['kind']))

    def test_hostname_only_page_never_publishes_even_when_the_title_names_the_company(self):
        html = doc(title='Example Pumps AS - Pumper')
        sid, anchor = self.page(html, email=None)
        for lie in ([mail('post@example.no')], [label('example.no')], [mail('post@example.no'), label('example.no')]):
            self.rejects(*self.forge(sid, anchor, html, email=None, corroboration=lie, score=0.95), str(lie))
        self.rejects(*self.forge(sid, anchor, html, email=None, corroboration=[], score=0.95), 'empty list')

    def test_name_host_label_requires_the_bare_ascii_label_and_the_whole_normalised_name(self):
        cases = (('pumps.example.no', 'EXAMPLE PUMPS AS'), ('examplepumps.com', 'EXAMPLE PUMPS TRONDHEIM AS'),
                 ('ex.no', 'EX AS'), ('xn--exmplepumps-yzb.no', 'EXAMPLEPUMPS AS'), ('example-pumps.no', 'EXAMPLE PUMPS TRONDHEIM AS'),
                 ('www.shop.examplepumps.no', 'EXAMPLE PUMPS AS'),
                 ('examplepumps.wixsite.com', 'EXAMPLE PUMPS AS'), ('proff.no', 'PROFF AS'), ('kommune.no', 'KOMMUNE AS'),
                 ('examplepumps.github.io', 'EXAMPLE PUMPS AS'), ('gmail.com', 'GMAIL AS'),
                 ('bergen.kommune.no', 'BERGEN AS'), ('examplepump.no', 'EXAMPLE PUMPS AS'))
        for host, name in cases:
            html = doc()
            sid, anchor = self.page(html, host=host, website=host, email=None, name=name)
            self.rejects(*self.forge(sid, anchor, html, host=host, website=host, email=None, name=name,
                                     corroboration=[label(host, name)]), host + ' ' + name)

    def test_name_host_label_accepts_hyphens_folding_and_a_vendor_domain(self):
        cases = (('example-pumps.no', 'EXAMPLE PUMPS AS'), ('www.example-pumps.no', 'Example Pumps ASA'),
                 ('kragero-installasjon.no', 'Kragerø Installasjon AS'), ('examplepumps.com', 'EXAMPLE PUMPS A/S'),
                 ('examplepumps.co.uk', 'Example Pumps Ltd'), ('tripletex.no', 'Tripletex AS'), ('kpmg.no', 'KPMG AS'),
                 ('examplepumps.bergen.no', 'EXAMPLE PUMPS AS'))
        for host, name in cases:
            html = doc()
            bare = host[4:] if host.startswith('www.') else host
            sid, anchor = self.page(html, host=host, website=host, email=None, name=name)
            self.accepts(*self.forge(sid, anchor, html, host=host, website=host, email=None, name=name,
                                     corroboration=[label(bare, name)]))

    def test_mailbox_ties_through_the_registrable_domain_only(self):
        for address, host in (('post@kontor.example.no', 'example.no'), ('post@example.no', 'www.example.no'),
                              ('post@example.no', 'example.no'), ('POST@EXAMPLE.NO', 'example.no'),
                              ('a@mail.example.com.no', 'example.com.no'), ('a@example.co.uk', 'www.example.co.uk')):
            html = doc()
            sid, anchor = self.page(html, host=host, website=host, email=address)
            registrable = '.'.join(host.removeprefix('www.').split('.')[-3 if host.endswith(('.com.no', '.co.uk')) else -2:])
            self.accepts(*self.forge(sid, anchor, html, host=host, website=host, email=address,
                                     corroboration=[mail(address, registrable)]), address + ' ' + host)

    def test_tampered_corroboration_entries_are_rejected(self):
        html = doc()
        sid, anchor = self.page(html)
        base, evidence = self.forge(sid, anchor, html)
        good = evidence['identity_assessment']['corroboration']
        for label_, entry in (('wrong kind', dict(good[0], kind='name_host_label')),
                              ('other registry value', dict(good[0], registry_value='post@evil.test')),
                              ('other domain', dict(good[0], domain='evil.test')),
                              ('other field', dict(good[0], registry_field='email')),
                              ('extra key', dict(good[0], extra=1)),
                              ('case changed value', dict(good[0], registry_value='POST@example.no')),
                              ('unstripped domain', dict(good[0], domain='www.example.no'))):
            forged = copy.deepcopy(evidence)
            forged['identity_assessment']['corroboration'] = [entry]
            self.rejects(base, forged, label_)
        forged = copy.deepcopy(evidence)
        forged['identity_assessment']['corroboration'] = good + [label('example.no')]
        self.rejects(base, forged, 'invented second kind')
        forged['identity_assessment']['corroboration'] = []
        self.rejects(base, forged, 'empty')


class PageTests(Base):
    def reject_page(self, html, why, **kwargs):
        self.rejects(*self.forged(html, **kwargs), why)

    def test_parked_and_placeholder_pages(self):
        parked = ('Domain is for sale', 'Domain for sale', 'This domain may be for sale', 'Buy this domain', 'HugeDomains',
                  'Parked at example', 'Domain Parking', 'Miss Hosting', 'Her flytter snart en ny gjest',
                  'has been informing visitors', 'Domenet er til salgs', 'Domene til salgs', 'Domenet selges',
                  'Dette domenet', 'Kjøp dette domenet', 'Find the best information and most relevant links on all topics related to')
        for phrase in parked:
            self.reject_page(doc(body='<p>' + phrase + '. ' + 'x ' * 400 + '</p>' + OWN), phrase)
        self.reject_page(doc(title='Domenet er til salgs'), 'in title')
        for phrase in ('Coming soon', 'Kommer snart', 'Under construction', 'Under bygging', 'Under utvikling',
                       'Default web site page', 'Welcome to nginx', 'It works!', 'Index of /', 'Account suspended',
                       'Siden er ikke tilgjengelig', 'Site not found'):
            self.reject_page(doc(body='<p>' + phrase + ' ' + FILLER + '</p>' + OWN), phrase)

    def test_placeholder_phrase_inside_a_long_page_is_not_a_placeholder(self):
        html = doc(body=FILLER * 6 + '<p>Kommer snart: nye produkter.</p>' + OWN)
        self.assertGreater(len(re.sub(r'<[^>]+>', '', html)), 600)
        self.accepts(*self.forged(html))

    def test_unreadable_pages(self):
        for html in (doc(body='<div id="root"></div><script>document.title="Example Pumps AS"; ' + 'x' * 400 + '</script>' + OWN),
                     doc(body='<noscript>' + FILLER + '</noscript>' + OWN), doc(body='<div hidden>' + FILLER + '</div>' + OWN),
                     doc(body='<div aria-hidden="true">' + FILLER + '</div>' + OWN),
                     doc(body='<div style="display : none">' + FILLER + '</div>' + OWN),
                     doc(body='<div style="visibility:hidden">' + FILLER + '</div>' + OWN),
                     doc(body='<template>' + FILLER + '</template>' + OWN), doc(body='<style>' + 'x' * 300 + '</style>' + OWN),
                     doc(body='<!-- ' + FILLER + ' -->' + OWN), doc(body='<p>short</p>' + OWN),
                     doc(title='T' * 300, body='<p>short</p>' + OWN)):
            self.reject_page(html, html[:70])

    def test_visible_text_threshold_is_one_hundred_characters(self):
        named = dict(kind='legal_name', part='title', span='<title>Example Pumps AS</title>')
        self.accepts(*self.forged(doc(title='Example Pumps AS', body='<p>' + 'a' * 100 + '</p>'), **named))
        self.reject_page(doc(title='Example Pumps AS', body='<p>' + 'a' * 99 + '</p>'), '99 characters', **named)
        self.reject_page(doc(title='Example Pumps AS', body='<p>' + 'a' * 99 + '</p><!-- ' + 'b' * 200 + ' -->'),
                         'comment does not count', **named)

    def test_a_page_without_title_or_heading_publishes_on_its_identifier_and_without_one_it_does_not(self):
        for html in ('<html><body>' + FILLER + OWN + '</body></html>', doc(title=''), doc(title='  ')):
            self.accepts(*self.forged(html))
        self.reject_page('<html><body>' + FILLER + '</body></html>', 'no identifier at all')

    def test_title_and_heading_identifiers_are_the_first_nonempty_title_and_one_of_the_first_three_headings(self):
        named = dict(kind='legal_name')
        html = '<html><head><title></title><title>Example Pumps AS</title></head><body>' + FILLER + '</body></html>'
        self.accepts(*self.forged(html, part='title', span='<title>Example Pumps AS</title>', **named))
        self.reject_page(html, 'the empty title carries no name', part='title', span='<title></title>', **named)
        html = ('<html><head><title>Pumper</title></head><body><h1> </h1><h1>Example Pumps AS</h1>' + FILLER
                + '</body></html>')
        self.accepts(*self.forged(html, part='h1', span='<h1>Example Pumps AS</h1>', **named))
        self.reject_page(html, 'blank heading', part='h1', span='<h1> </h1>', **named)
        self.reject_page(html, 'heading claimed as title', part='title', span='<h1>Example Pumps AS</h1>', **named)
        html = '<html><body><h1>a</h1><h1>b</h1><h1>c</h1><h1>Example Pumps AS</h1>' + FILLER + '</body></html>'
        self.reject_page(html, 'fourth heading', part='h1', span='<h1>Example Pumps AS</h1>', **named)
        for hidden, span in (('<h1 hidden>Example Pumps AS</h1>', '<h1 hidden>Example Pumps AS</h1>'),
                             ('<blockquote><h1>Example Pumps AS</h1></blockquote>', '<h1>Example Pumps AS</h1>'),
                             ('<q><h1>Example Pumps AS</h1></q>', '<h1>Example Pumps AS</h1>'),
                             ('<div style="display:none"><h1>Example Pumps AS</h1></div>', '<h1>Example Pumps AS</h1>')):
            html = '<html><body>' + hidden + FILLER + '</body></html>'
            self.reject_page(html, hidden, part='h1', span=span, **named)

    def test_organisation_numbers_other_than_the_subject_conflict(self):
        for fragment in ('<footer>Org.nr 987 654 321</footer>', '<footer>Organisasjonsnummer: 987654321</footer>',
                         '<footer>Org nr. NO 987 654 321</footer>', '<footer>Organisation number 987 654 321</footer>',
                         '<footer>NO 987654321 MVA</footer>', '<p>987 654 321 MVA</p>', '<p>NO987654321MVA</p>',
                         '<p>Org.nr 923 609 016 og org.nr 987 654 321</p>', '<p>Orgnr: 987.654.321</p>'):
            self.reject_page(doc(body=FILLER + OWN + fragment), fragment)
        for head in ('<script type="application/ld+json">{"@type":"Organization","vatID":"NO987654321MVA"}</script>',
                     '<script type="application/ld+json">{"@graph":[{"@type":"Person"},{"identifier":"987654321"}]}</script>',
                     '<script type="application/ld+json">{"@type":"Organization","taxID":{"value":"987 654 321"}}</script>',
                     '<script type="application/ld+json">[{"@type":"Organization","identifier":["923609016","987654321"]}]</script>',
                     '<script TYPE="Application/LD+JSON">{"@type":"Organization","vatID":"987654321"}</script>'):
            self.reject_page(doc(head=head), head)

    def test_own_number_bare_numbers_and_unrelated_jsonld_are_not_conflicts(self):
        for html in (doc(body=FILLER + OWN + '<p>Ring 987 654 321 for hjelp. Tilbud 12345.</p>'),
                     doc(body=FILLER + OWN + '<footer>NO 923 609 016 MVA</footer>'),
                     doc(head='<script type="application/ld+json">{"@type":"Organization","vatID":"NO923609016MVA","telephone":"987654321"}</script>'),
                     doc(head='<script type="application/ld+json">{"@type":"Product","sku":"987654321"}</script>'),
                     doc(head='<script type="application/json">{"vatID":"987654321"}</script>')):
            self.accepts(*self.forged(html))

    def test_another_legal_entity_in_title_site_name_or_headings(self):
        cases = (doc(title='Parent Group AS - Pumper'), doc(h1='Welcome to Parent Group AS'),
                 doc(head='<meta property="og:site_name" content="Parent Group AS">'),
                 doc(head='<meta name="og:site_name" content="Parent ASA">'),
                 doc(title='Pumper hos Nordic Cargo A/S'), doc(title='Pumper - Kari Nordmann ENK'),
                 doc(title='Example Pumps AS Parent Group Ltd'), doc(title='Fjord Drift KS'),
                 doc(title='Pumper AS'), doc(body='<h1>Pumper</h1><h1>Hei</h1><h1>Another Entity GmbH</h1>' + FILLER + OWN),
                 doc(title='Example Pumps ASA'))
        for html in cases:
            self.reject_page(html, html[:120])

    def test_own_name_other_forms_and_late_headings_are_not_conflicts(self):
        for html in (doc(title='Example Pumps AS'), doc(title='EXAMPLE PUMPS AS | Pumper'),
                     doc(title='Pumper as service'), doc(title='Home'),
                     doc(body='<h1>a</h1><h1>b</h1><h1>c</h1><h1>Another Entity AS</h1>' + FILLER + OWN),
                     doc(head='<meta property="og:site_name" content="Example Pumps">')):
            self.accepts(*self.forged(html))

    def test_group_parent_and_ownership_markers(self):
        markers = ('Pumper, et datterselskap', 'Del av Parent', 'Deler av Parent', 'Part of the Parent family',
                   'Member of Parent', 'Medlem av konsernet', 'Parent company', 'Owned by Parent', 'Eies av Parent',
                   'Eid av Parent', 'Datterselskapet vårt', 'Morselskapet', 'Søsterselskap', 'Sosterselskap',
                   'konsernledelsen', 'Subsidiary of X', 'subsidiaries')
        for marker in markers:
            self.reject_page(doc(title='Pumper - ' + marker), 'title ' + marker)
            self.reject_page(doc(h1=marker), 'h1 ' + marker)
            self.reject_page(doc(head='<meta property="og:site_name" content="' + marker + '">'), 'og ' + marker)
            self.reject_page(doc(body=FILLER + OWN + '<footer>' + marker + '</footer>'), 'footer ' + marker)
            self.reject_page(doc(body=FILLER + OWN + '<address>' + marker + '</address>'), 'address ' + marker)

    def test_marker_outside_the_checked_elements_is_not_a_conflict(self):
        self.accepts(*self.forged(doc(body=FILLER + OWN + '<p>Vi er del av fellesskapet og et konsern av venner.</p>')))
        self.accepts(*self.forged(doc(body=FILLER + OWN + '<h1>a</h1><h1>b</h1><h1>c</h1><h1>del av</h1>')))
        self.accepts(*self.forged(doc(body=FILLER + OWN + '<h2>Part of the team</h2>')))


class SourceChainTests(Base):
    def test_host_must_be_the_registry_host_or_its_www_alias(self):
        for host, website in (('other.no', 'example.no'), ('shop.example.no', 'example.no'),
                              ('example.no.evil.test', 'example.no'), ('evil-example.no', 'example.no'),
                              ('example.no', 'other.no'), ('www.shop.example.no', 'example.no')):
            html = doc()
            sid, anchor = self.page(html, host=host, website=website)
            self.rejects(*self.forge(sid, anchor, html, host=host, website=website), host + ' vs ' + website)

    def test_registry_website_must_be_a_root(self):
        for website in ('example.no/shop', 'https://example.no/shop/', 'example.no/?q=1', 'example.no?x', 'example.no:8080',
                        'https://user:pw@example.no/', 'ftp://example.no/', 'example.no/#top', '//example.no/', '',
                        'example .no', 'https://', 'localhost'):
            html = doc()
            sid, anchor = self.page(html, website=website)
            self.rejects(*self.forge(sid, anchor, html, website=website), repr(website))
        for website in ('example.no', 'example.no/', 'http://example.no', 'https://www.example.no/', 'HTTPS://Example.No'):
            html = doc()
            sid, anchor = self.page(html, website=website)
            self.accepts(*self.forge(sid, anchor, html, website=website), website)

    def test_redirect_only_host_is_not_covered(self):
        html = doc()
        sid, anchor = self.page(html, host='redirected.test', website='example.no')
        self.rejects(*self.forge(sid, anchor, html, host='redirected.test'), 'a redirect link never establishes ownership')

    def test_receipt_checks(self):
        html = doc()
        for change, why in (({'http_status': 404}, 'status'), ({'robots_checked': False}, 'robots'),
                            ({'content_type': 'application/json'}, 'content type'), ({'content_type': ''}, 'empty type'),
                            ({'source_class': 'other'}, 'class'), ({'organisation_number': '999999999'}, 'subject'),
                            ({'sha256': digest(b'other')}, 'receipt hash'),
                            ({'effective_url': 'http://example.no/', 'source_url': 'http://example.no/'}, 'plain http'),
                            ({'effective_url': 'https://example.no:8443/', 'source_url': 'https://example.no:8443/'}, 'port')):
            anchor = self.anchor()
            sid, _ = self.page(html, anchor=anchor, receipt=change)
            claim, evidence = self.forge(sid, anchor, html)
            if 'effective_url' in change:
                evidence['source_url'] = change['effective_url']
            self.rejects(claim, evidence, why)

    def test_anchor_must_be_this_companys_exact_registry_row(self):
        html = doc()
        other = self.anchor(subject='990888213')
        sid, _ = self.page(html, anchor=other)
        self.rejects(*self.forge(sid, other, html), 'anchor row of another company')
        sid, anchor = self.page(html)
        claim, evidence = self.forge(sid, anchor, html)
        evidence['identity_assessment']['anchor_snapshot_id'] = other
        self.rejects(claim, evidence, 'assessment cites another anchor')
        unanchored = self.store.save(html.encode(), dict(organisation_number=SUBJECT, source_class='company_owned',
            source_url='https://example.no/', effective_url='https://example.no/', content_type='text/html',
            http_status=200, sha256=digest(html.encode()), declared_host='example.no', source_origin='example.no',
            robots_checked=True, retrieved_at='2026-10-10T08:00:00Z', ownership_anchor_snapshot_id='0' * 64))
        with self.assertRaises(Exception):
            self.audit(*self.forge(unanchored, anchor, html))

    def test_registry_values_in_the_assessment_are_the_retained_rows(self):
        html = doc()
        sid, anchor = self.page(html)
        for key, value in (('legal_name', 'OTHER AS'), ('registry_website', 'other.no'), ('registry_website', 'www.example.no'),
                           ('page_url', 'https://example.no/other'), ('legal_name', NAME.title()), ('registry_website', None)):
            claim, evidence = self.forge(sid, anchor, html)
            evidence['identity_assessment'][key] = value
            self.rejects(claim, evidence, key + ' ' + str(value))


class ForgeryTests(Base):
    def setUp(self):
        super().setUp()
        self.html = doc()
        self.sid, self.anchor_sid = self.page(self.html)

    def base(self):
        return self.forge(self.sid, self.anchor_sid, self.html)

    def test_claim_field_tampering(self):
        for key, value in (('value', 'https://example.no/shop'), ('value', 'https://other.no/'), ('value', 'http://example.no/'),
                           ('value', 'https://www.example.no/'), ('value', 'https://example.no'), ('value', None),
                           ('value', 'https://example.no/ '), ('scope', 'company_owned_html'), ('scope', 'registry_linked_html'),
                           ('scope', 'registry_declared_host'), ('field', 'business_description'), ('field', 'official_website'),
                           ('family', 'business_products'), ('item_key', 'x'), ('period', '2025'),
                           ('availability', 'ambiguous'), ('freshness', 'cached'), ('claim_id', '0' * 64),
                           ('evidence_ids', []), ('evidence_ids', ['x'])):
            claim, evidence = self.base()
            claim[key] = value
            self.rejects(claim, evidence, key + ' ' + str(value))

    def test_evidence_field_tampering(self):
        for key, value in (('extraction_method', 'explicit_subject_html_v1'), ('extraction_method', 'registry_host_corroboration_v2'),
                           ('extraction_method', 'footer_bound_organization_jsonld_v1'), ('extraction_method', 'scoped_catalogue_html_v2'),
                           ('extraction_method', 'bounded_company_section_v1'), ('extraction_method', None),
                           ('claim_span', '<title>Pumper</title>'), ('claim_span', '<title>Pumper og service'),
                           ('claim_span', 'Pumper og service'), ('claim_span', ''),
                           ('content_sha256', digest(b'other bytes')), ('source_origin', 'other.no'),
                           ('source_url', 'https://example.no/other'), ('source_class', 'brreg_entity'),
                           ('retrieved_at', '2026-10-11T08:00:00Z'), ('id', 'x:y'),
                           ('support_spans', {}), ('support_spans', {'legal_identity': 'x'})):
            claim, evidence = self.base()
            evidence[key] = value
            self.rejects(claim, evidence, key + ' ' + str(value))

    def test_scope_and_method_each_changed_alone(self):
        claim, evidence = self.base()
        claim['scope'] = 'company_owned_html'
        self.rejects(claim, evidence, 'scope only')
        claim, evidence = self.base()
        evidence['extraction_method'] = 'explicit_subject_html_v1'
        self.rejects(claim, evidence, 'method only')
        claim, evidence = self.base()
        evidence['identity_assessment']['method'] = 'other'
        self.rejects(claim, evidence, 'assessment method')

    def test_locator_tampering(self):
        claim, evidence = self.base()
        loc = evidence['locator']
        for change in ({'html_start': loc['html_start'] + 1}, {'html_start': loc['html_start'] - 1},
                       {'html_end': loc['html_end'] + 1}, {'html_end': loc['html_end'] - 1},
                       {'html_start': str(loc['html_start'])}, {'html_start': True}, {'html_end': float(loc['html_end'])},
                       {'identity_part': 'h1'}, {'identity_part': None}, {'extra': 1}, {'identity_part': 'footer'}):
            claim, evidence = self.base()
            evidence['locator'].update(change)
            self.rejects(claim, evidence, str(change))
        for key in loc:
            claim, evidence = self.base()
            del evidence['locator'][key]
            self.rejects(claim, evidence, 'missing ' + key)

    def test_span_is_an_element_that_carries_the_identifier(self):
        html = doc(h1='Rubrikk')
        sid, anchor = self.page(html)
        self.accepts(*self.forge(sid, anchor, html))
        for span, why in (('<title>Pumper og service</title>', 'title without the identifier'),
                          ('<h1>Rubrikk</h1>', 'heading without the identifier'),
                          ('<p>Vi leverer pumper', 'paragraph fragment'), (FILLER[:40], 'text slice'),
                          ('Org.nr 923 609 016', 'text only, no element'),
                          (html[html.index('<body>'):html.index('</body>') + 7], 'the body never counts'),
                          (html, 'the document never counts'), (FILLER, 'paragraph without the identifier')):
            self.rejects(*self.forge(sid, anchor, html, span=span), why)
        wrapped = doc(body='<div>' + FILLER + OWN + '</div>')
        sid, anchor = self.page(wrapped)
        self.accepts(*self.forge(sid, anchor, wrapped, span='<div>' + FILLER + OWN + '</div>'))
        self.accepts(*self.forge(sid, anchor, wrapped, span=OWN))
        huge = doc(body='<div>' + FILLER * 12 + OWN + '</div>')
        sid, anchor = self.page(huge)
        self.rejects(*self.forge(sid, anchor, huge, span='<div>' + FILLER * 12 + OWN + '</div>'), 'over 1500 characters')
        self.accepts(*self.forge(sid, anchor, huge, span=OWN))

    def test_identifier_and_text_digest_tampering(self):
        for key, value in (('identifier', None), ('identifier', {}), ('identifier', {'kind': 'org_number'}),
                           ('identifier', {'kind': 'legal_name', 'part': 'org_number'}),
                           ('identifier', {'kind': 'registry_address', 'part': 'registry_address'}),
                           ('identifier', {'kind': 'org_number', 'part': 'footer'}),
                           ('identifier', {'kind': 'org_number', 'part': 'org_number', 'extra': 1}),
                           ('visible_text_sha256', '0' * 64), ('visible_text_sha256', hashlib.sha256(b'x').hexdigest()),
                           ('visible_text_sha256', None), ('visible_text_sha256', 'ABC')):
            claim, evidence = self.base()
            evidence['identity_assessment'][key] = value
            self.rejects(claim, evidence, key + ' ' + repr(value))

    def test_visible_text_digest_gaps_block_tags_and_joins_inline_tags(self):
        page = website_support.Page(b'<html><head><title>T</title></head><body><p>a</p><p>b<b>c</b></p>'
                                    b'<span hidden>x</span><script>y</script><!-- z --> d&nbsp;e</body></html>')
        self.assertEqual(page.visible, 'a bc d e')
        self.assertEqual(hashlib.sha256(page.visible.encode()).hexdigest(),
                         hashlib.sha256(b'a bc d e').hexdigest())

    def test_missing_or_malformed_identity_assessment(self):
        claim, evidence = self.base()
        del evidence['identity_assessment']
        self.rejects(claim, evidence, 'missing')
        for value in (None, [], 'exact', {}, []):
            claim, evidence = self.base()
            evidence['identity_assessment'] = value
            self.rejects(claim, evidence, 'type ' + repr(value))
        for key in self.base()[1]['identity_assessment']:
            claim, evidence = self.base()
            del evidence['identity_assessment'][key]
            self.rejects(claim, evidence, 'missing ' + key)
        claim, evidence = self.base()
        evidence['identity_assessment']['extra'] = 'x'
        self.rejects(claim, evidence, 'extra key')
        for key, value in (('status', 'strong'), ('status', 'exact '), ('status', None), ('path', 'page_identity_part'),
                           ('path', 'registry_corroborated '), ('score', 0.8), ('score', 1.0), ('score', 0.9), ('score', '0.9'),
                           ('score', None), ('score', True), ('reasons', []), ('reasons', 'text'), ('reasons', [1]),
                           ('reasons', None), ('method', 'registry_host_corroboration_v2')):
            claim, evidence = self.base()
            evidence['identity_assessment'][key] = value
            self.rejects(claim, evidence, key + ' ' + repr(value))

    def test_snapshot_and_hash_tampering(self):
        claim, evidence = self.base()
        other_html = doc(title='Annet')
        other_sid, _ = self.page(other_html)
        evidence['snapshot_id'] = other_sid
        evidence['id'] = other_sid + ':' + claim['claim_id']
        claim['evidence_ids'] = [evidence['id']]
        self.rejects(claim, evidence, 'snapshot of other bytes')
        claim, evidence = self.base()
        evidence['snapshot_id'] = '0' * 64
        with self.assertRaises(Exception):
            self.audit(claim, evidence)
        claim, evidence = self.base()
        two = [evidence['id'], evidence['id']]
        claim['evidence_ids'] = two
        self.rejects(claim, evidence, 'two evidence ids')

    def test_retained_bytes_are_what_is_audited_not_the_claimed_ones(self):
        claim, evidence = self.base()
        retained = self.store.path('objects', digest(self.html.encode()))
        retained.write_bytes(self.html.encode().replace(b'Pumper og service', b'Pumper og servicX'))
        self.rejects(claim, evidence, 'object bytes no longer hash to the receipt')


ADDRESS = {'adresse': ['Storgata 1'], 'postnummer': '0123', 'poststed': 'OSLO'}
NAMED = 'Example Pumps AS'
SPAN = re.compile(r'<(footer|address|p|div|h1|h2|title|a|li|span|section|article|td)\b[^>]*>.*?</\1>', re.S)
COMBOS = (('org_number', 'org_number'), ('registry_address', 'registry_address'), ('legal_name', 'title'),
          ('legal_name', 'h1'), ('legal_name', 'footer'), ('legal_name', 'copyright'), ('legal_name', 'contact_block'))


class AmendmentTests(Base):
    """A registry-corroborated host is not enough: the page must carry a hard identifier of this exact entity."""

    def refuse_everything(self, html, why, **registry):
        """No element of the page may be claimed as any identifier kind, at either score."""
        sid, anchor = self.page(html, **{k: v for k, v in registry.items() if k in ('website', 'email', 'name', 'address', 'host')})
        spans = {m[0] for m in SPAN.finditer(html)}
        self.assertTrue(spans, why)
        for span in spans:
            for kind, part in COMBOS:
                for score in (0.9, 0.95):
                    claim, evidence = self.forge(sid, anchor, html, span=span, kind=kind, part=part, score=score,
                                                 **{k: v for k, v in registry.items() if k != 'address'})
                    self.rejects(claim, evidence, '%s: %s %s %s' % (why, span[:50], kind, part))

    def accept_one(self, html, span, kind, part=None, score=None, address=ADDRESS, produce=True, **registry):
        if score is None:
            score = 0.95 if kind == 'org_number' or part in ('title', 'h1') else 0.9
        sid, anchor = self.page(html, address=address, **{k: v for k, v in registry.items() if k in ('website', 'email', 'name', 'host')})
        self.accepts(*self.forge(sid, anchor, html, span=span, kind=kind, part=part, score=score,
                                 **{k: v for k, v in registry.items() if k not in ('address',)}), span[:60])
        if produce:
            found, _, _ = self.produce(html, address=address, **{k: v for k, v in registry.items() if k in ('website', 'email', 'name', 'host')})
            self.assertEqual(len(found), 1, 'the maker publishes ' + span[:60])
            self.accepts(found[0]['claim'], found[0]['evidence'], 'maker claim ' + span[:60])

    # the six adjudicated regressions, as pages
    def test_global_parent_site_is_refused(self):
        html = doc(title='Falck', body=FILLER + '<footer>© 2020 Falck A/S</footer>')
        self.refuse_everything(html, 'falck', host='falck.com', website='falck.com', email='kundesenter@falck.com',
                               name='FALCK NORGE AS', corroboration=[mail('kundesenter@falck.com', 'falck.com')],
                               address={'adresse': ['Wergelandsveien 7'], 'postnummer': '0167', 'poststed': 'OSLO'})

    def test_brand_only_copyright_line_is_refused(self):
        html = doc(title='Ekstralys', body=FILLER + '<footer>Copyright © 2026 All rights Reserved Ekstralys</footer>')
        self.refuse_everything(html, 'ekstralys', host='ekstralys.no', website='ekstralys.no', email=None,
                               name='EKSTRALYS AS', corroboration=[label('ekstralys.no', 'EKSTRALYS AS')])

    def test_menu_only_script_shell_is_refused(self):
        menu = ''.join('<li><a href="/p%d">Meny og kategori nummer %d</a></li>' % (i, i) for i in range(14))
        html = doc(title='Apotek 1', body='<div id="app"><ul>' + menu + '</ul></div>')
        self.refuse_everything(html, 'apotek1', host='apotek1.no', website='apotek1.no', email='post@apotek1.no',
                               name='APOTEK 1 GRUPPEN AS', corroboration=[mail('post@apotek1.no', 'apotek1.no')])

    def test_landing_page_with_another_business_address_is_refused(self):
        html = doc(title='Bang &amp; Olufsen | Mobit', body='<p>Bang &amp; Olufsen | Oslo Vest | Drammensveien 130, 0277 Oslo</p>'
                   '<p>MOBIT Follo - ring oss på telefon for en prat om hjemmekino.</p>')
        self.refuse_everything(html, '3d', host='3d.no', website='3d.no', email='regnskap@3d.no', name='3D-BEDRIFT AS',
                               corroboration=[mail('regnskap@3d.no', '3d.no')],
                               address={'adresse': ['Nygårdsveien 2'], 'postnummer': '1400', 'poststed': 'SKI'})

    def test_under_construction_page_is_refused(self):
        html = doc(title='Romlaboratoriet', body='<p>Vi er Romlaboratoriet, et tverrfaglig kontor som jobber med arkitektur og '
                   'interiørarkitektur. ' + 'Vi samarbeider med byggherrer, entreprenører og leverandører. ' * 3 +
                   'Vi jobber med en ny nettside.</p>')
        self.refuse_everything(html, 'romlab', host='romlab.no', website='romlab.no', email='post@romlab.no',
                               name='ROMLABORATORIET AS', corroboration=[mail('post@romlab.no', 'romlab.no')])

    def test_chain_brand_without_the_legal_form_is_refused(self):
        html = doc(title='HJEM | Bislett Kebab House', body='<h1>Bislett Kebab House</h1>' + FILLER
                   + '<footer>© 2026 Bislett Kebab House</footer>')
        self.refuse_everything(html, 'bislett', host='bislettkebabhouse.no', website='bislettkebabhouse.no', email=None,
                               name='BISLETT KEBAB HOUSE AS', corroboration=[label('bislettkebabhouse.no', 'BISLETT KEBAB HOUSE AS')])

    def test_corroboration_alone_never_publishes_whatever_the_title_says(self):
        for title in ('Pumper og service', 'Example Pumps'):
            self.refuse_everything(doc(title=title, body=FILLER, h1=title), 'corroboration only ' + title)

    # near misses of each identifier
    def test_address_and_number_near_misses_and_unmarked_names_are_refused(self):
        cases = ('<p>Storgata 1</p>', '<p>0123</p>', '<p>Oslo</p>', '<p>Storgata 12, 0123 Oslo</p>', '<p>Storgata 1A, 0123 Oslo</p>',
                 '<p>Storgata 1 og Oslo</p>'.replace('og Oslo', ''), '<p>Storgata, 0123 Oslo</p>', '<p>Storgata 1</p><p>0123 Oslo</p>',
                 '<p>Orgnr 923 609 0161</p>', '<p>Org.nr 1923 609 016</p>', '<p>Org.nr 92360901</p>', '<p>Org.nr 923-609-016</p>',
                 '<blockquote><p>Example Pumps AS, tlf 22 22 22 22</p></blockquote>',
                 '<div hidden><footer>Example Pumps AS</footer></div>', '<p>Vi er Example Pumps AS og leverer pumper.</p>',
                 '<p>Copyright Example Pumps AS</p>', '<footer>Example Pumps AS Holding</footer>',
                 '<footer>Example Pumps AS Norge</footer>', '<footer>Example Pumps</footer>',
                 '<p>© 2026 Example Pumps</p>', '<p>Kontakt oss: Example Pumps</p>')
        for fragment in cases:
            self.refuse_everything(doc(title='Pumper', body=FILLER + fragment), fragment, address=ADDRESS)
        self.refuse_everything(doc(title='Nordic Example Pumps AS', body=FILLER), 'capitalised prefix in the title', address=ADDRESS)
        self.refuse_everything(doc(title='Pumper', h1='Nordic Example Pumps AS', body=FILLER), 'capitalised prefix in a heading',
                               address=ADDRESS)

    def test_street_lines_that_are_not_streets_never_count(self):
        for line in ('c/o Pumper AS', 'Postboks 5', 'PB 5', 'Boks 1', 'Gt 1', '1234', ''):
            address = {'adresse': [line], 'postnummer': '0123', 'poststed': 'OSLO'}
            html = doc(title='Pumper', body=FILLER + '<p>' + (line or 'x') + ', 0123 Oslo</p>')
            self.refuse_everything(html, 'street ' + line, address=address)

    # positives
    def test_every_org_number_format_publishes_without_a_label(self):
        for text in ('Org.nr 923 609 016', 'Faktura: 923 609 016', 'NO 923609016 MVA', '923.609.016', '923609016', '923 609.016',
                     'Orgnr: 923609016.'):
            self.accept_one(doc(title='Pumper', body=FILLER + '<footer>' + text + '</footer>'),
                            '<footer>' + text + '</footer>', 'org_number')

    def test_registry_address_with_street_and_postcode_or_street_and_town(self):
        for text in ('Storgata 1, 0123 Bergen', 'Kontor: storgata 1 0123', 'STORGATA 1; Oslo', 'Storgata 1 Oslo', 'Hit: Storgata 1,0123'):
            self.accept_one(doc(title='Pumper', body=FILLER + '<p>' + text + '</p>'), '<p>' + text + '</p>',
                            'registry_address')
        address = {'adresse': ['c/o Pumper AS', 'Storgata 1'], 'postnummer': '0123', 'poststed': 'OSLO'}
        self.accept_one(doc(title='Pumper', body=FILLER + '<p>Storgata 1, 0123 Oslo</p>'), '<p>Storgata 1, 0123 Oslo</p>',
                        'registry_address', address=address)
        address = {'adresse': 'Kjøpmannsgata 4', 'postnummer': '7013', 'poststed': 'TRONDHEIM'}
        self.accept_one(doc(title='Pumper', body=FILLER + '<p>Kjopmannsgata 4, Trondheim</p>'),
                        '<p>Kjopmannsgata 4, Trondheim</p>', 'registry_address', address=address)
        address = {'adresse': ['Storgata 1'], 'postnummer': '6511', 'poststed': 'KRISTIANSUND N'}
        self.accept_one(doc(title='Pumper', body=FILLER + '<p>Storgata 1, Kristiansund</p>'),
                        '<p>Storgata 1, Kristiansund</p>', 'registry_address', address=address)

    def test_the_legal_name_publishes_in_title_heading_footer_copyright_or_contact_block(self):
        plain = '<html><head><title>Pumper</title></head><body>%s</body></html>'
        cases = (
            (doc(title='Example Pumps AS - Pumper', body=FILLER), '<title>Example Pumps AS - Pumper</title>', 'title', 0.95),
            (doc(title='Hjem | Example Pumps AS', body=FILLER), '<title>Hjem | Example Pumps AS</title>', 'title', 0.95),
            (plain % ('<h1>Velkommen til Example Pumps AS</h1>' + FILLER), '<h1>Velkommen til Example Pumps AS</h1>', 'h1', 0.95),
            (plain % (FILLER + '<footer>Example Pumps AS</footer>'), '<footer>Example Pumps AS</footer>', 'footer', 0.9),
            (plain % (FILLER + '<footer>Nordic Example Pumps AS</footer>'), '<footer>Nordic Example Pumps AS</footer>',
             'footer', 0.9),
            (plain % (FILLER + '<address>Example Pumps AS, Storgata 99</address>'),
             '<address>Example Pumps AS, Storgata 99</address>', 'footer', 0.9),
            (plain % (FILLER + '<p>© 2026 Example Pumps AS</p>'), '<p>© 2026 Example Pumps AS</p>', 'copyright', 0.9),
            (plain % (FILLER + '<p>Copyright 2026 Example Pumps AS</p>'), '<p>Copyright 2026 Example Pumps AS</p>',
             'copyright', 0.9),
            (plain % (FILLER + '<p>(c) 2016-2025 by example pumps as</p>'), '<p>(c) 2016-2025 by example pumps as</p>', 'copyright', 0.9),
            (plain % (FILLER + '<div>Example Pumps AS, tlf 22 22 22 22</div>'), '<div>Example Pumps AS, tlf 22 22 22 22</div>',
             'contact_block', 0.9),
            (plain % (FILLER + '<div>Example Pumps AS post@example.no</div>'), '<div>Example Pumps AS post@example.no</div>',
             'contact_block', 0.9),
            (plain % (FILLER + '<div>Example Pumps AS 22222222</div>'), '<div>Example Pumps AS 22222222</div>', 'contact_block', 0.9),
            (plain % (FILLER + '<div>Adresse: Example Pumps AS</div>'), '<div>Adresse: Example Pumps AS</div>', 'contact_block', 0.9),
            (plain % ('<p>Hos Example Pumps AS, kontakt oss.</p>' + FILLER), '<p>Hos Example Pumps AS, kontakt oss.</p>', 'contact_block', 0.9),
        )
        for html, span, part, score in cases:
            self.accept_one(html, span, 'legal_name', part, score)

    def test_priority_is_number_then_address_then_name_parts_in_the_listed_order(self):
        html = doc(title='Example Pumps AS', body=FILLER + OWN)
        sid, anchor = self.page(html, address=ADDRESS)
        self.accepts(*self.forge(sid, anchor, html))
        self.rejects(*self.forge(sid, anchor, html, kind='legal_name', part='title', span='<title>Example Pumps AS</title>'),
                     'the number outranks the name')
        html = doc(title='Pumper', body=FILLER + '<p>Storgata 1, Oslo</p><footer>Example Pumps AS</footer>')
        sid, anchor = self.page(html, address=ADDRESS)
        self.accepts(*self.forge(sid, anchor, html, kind='registry_address', span='<p>Storgata 1, Oslo</p>', score=0.9))
        self.rejects(*self.forge(sid, anchor, html, kind='legal_name', part='footer', span='<footer>Example Pumps AS</footer>',
                                 score=0.9), 'the address outranks the name')
        html = doc(title='Pumper', body=FILLER + '<footer>Example Pumps AS</footer><p>© 2026 Example Pumps AS</p>')
        sid, anchor = self.page(html)
        self.accepts(*self.forge(sid, anchor, html, kind='legal_name', part='footer', span='<footer>Example Pumps AS</footer>', score=0.9))
        self.rejects(*self.forge(sid, anchor, html, kind='legal_name', part='copyright',
                                 span='<p>© 2026 Example Pumps AS</p>', score=0.9), 'the footer outranks the copyright line')

    # foreign parent veto
    def test_foreign_parent_footer_vetoes_a_name_that_only_the_title_carries(self):
        html = doc(title='Example Pumps AS', body=FILLER + '<footer>© 2020 Parent Group A/S</footer>')
        sid, anchor = self.page(html)
        self.rejects(*self.forge(sid, anchor, html, kind='legal_name', part='title', span='<title>Example Pumps AS</title>'),
                     'foreign parent, nothing of the entity in the text')
        for rescue in ('<p>Storgata 12, 0123 Oslo</p>', '<p>Hos Example Pumps AS</p>'):
            html = doc(title='Example Pumps AS', body=FILLER + '<footer>© 2020 Parent Group A/S</footer>' + rescue)
            sid, anchor = self.page(html)
            self.accepts(*self.forge(sid, anchor, html, kind='legal_name', part='title', span='<title>Example Pumps AS</title>'), rescue)
        html = doc(title='Example Pumps AS', body=FILLER + '<footer>© 2020 Parent Group A/S</footer><p>Org.nr 923 609 016</p>')
        sid, anchor = self.page(html)
        self.accepts(*self.forge(sid, anchor, html, span='<p>Org.nr 923 609 016</p>'))

    def test_foreign_legal_forms_all_veto_and_a_norwegian_line_does_not(self):
        for line in ('© Foo A/S', '© Foo Bar GmbH', '© Foo Ltd.', '© Foo Inc', '© Foo AB', 'Copyright Foo Oy',
                     '© 2020 Foo SA', '(c) Foo BV'):
            html = doc(title='Example Pumps AS', body=FILLER + '<p>' + line + '</p>')
            sid, anchor = self.page(html)
            self.rejects(*self.forge(sid, anchor, html, kind='legal_name', part='title', span='<title>Example Pumps AS</title>'), line)
        html = doc(title='Example Pumps AS', body=FILLER + '<p>© 2020 Pumper AS</p>')
        sid, anchor = self.page(html)
        self.accepts(*self.forge(sid, anchor, html, kind='legal_name', part='title', span='<title>Example Pumps AS</title>'))

    def test_foreign_copyright_line_beside_the_own_number_is_not_vetoed(self):
        html = doc(title='Pumper', body=FILLER + OWN + '<footer>© 2020 Falck A/S</footer>')
        self.accept_one(html, OWN, 'org_number')


class FrozenRegistryTests(Base):
    """The anchor is a row of the frozen registry, the form used by the evaluator, not a live brreg response."""

    def frozen(self, csv_source, website, email, name=NAME):
        rows = [{'organisation_number': SUBJECT, 'name': name}]
        if csv_source:
            body = io.StringIO(newline='')
            writer = csv.DictWriter(body, ['organisasjonsnummer', 'navn', 'hjemmeside', 'epostadresse'], delimiter=';')
            writer.writeheader()
            writer.writerow({'organisasjonsnummer': SUBJECT, 'navn': name, 'hjemmeside': website, 'epostadresse': email})
            raw = body.getvalue().encode()
        else:
            raw = (json.dumps({'organisation_number': SUBJECT, 'name': name, 'website': website, 'email': email}) + '\n').encode()
        archive = gzip.compress(raw, mtime=0)
        path = Path(self.temp.name) / ('registry.' + ('csv' if csv_source else 'jsonl') + '.gz')
        path.write_bytes(archive)
        receipt = {'source_class': 'frozen_registry', 'source_url': 'https://example.org/frozen',
                   'retrieved_at': '2026-10-08T08:00:00Z', 'sha256': digest(archive), 'uncompressed_sha256': digest(raw),
                   'dataset_format': 'csv' if csv_source else 'jsonl'}
        return acquire_batch(path, receipt, [SUBJECT], self.store, time.monotonic() + 10)[SUBJECT]

    def test_csv_and_jsonl_rows_carry_the_mailbox_and_the_site(self):
        for csv_source in (True, False):
            html = doc()
            anchor = self.frozen(csv_source, 'example.no', EMAIL)
            sid, _ = self.page(html, anchor=anchor)
            claim, evidence = self.forge(sid, anchor, html)
            self.accepts(claim, evidence)
            wrong = self.frozen(csv_source, 'example.no', 'post@other.no')
            sid, _ = self.page(html, anchor=wrong)
            self.rejects(*self.forge(sid, wrong, html), 'mailbox of another domain, csv=%s' % csv_source)
            nomail = self.frozen(csv_source, 'example.no', '')
            sid, _ = self.page(html, anchor=nomail)
            self.rejects(*self.forge(sid, nomail, html), 'no mailbox, csv=%s' % csv_source)


if __name__ == '__main__':
    unittest.main()
