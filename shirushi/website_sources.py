"""Registry-corroborated publication of the registry-declared website (tier B).

The registry row declares a homepage. It is published as the verified website only when the page
loads and is readable, a field of the same registry row corroborates the host independently of page
text (the e-mail domain equals the site's registrable domain, or the legal name without its legal form
equals the bare host label), and the page title, headings and footer do not point at another legal
entity, group or organisation number. Parked, placeholder and script-only pages abstain.
"""
import re
from urllib.parse import urlsplit

from .claims import claim_id
from .contracts import loads
from .fetch import SourceUnavailable, website_candidate, website_hosts
from .html_sources import DIRECTORY_HOSTS, OTHER_ENTITY, SHARED_DOMAINS, Sections, ascii_fold, name_domain_tie, names, org_numbers
from .redirects import denylisted, registrable_domain
from .snapshots import digest
from .web_sources import Page, nodes

METHOD = 'registry_host_corroboration_v1'
SCOPE = 'registry_declared_host_name_gate'
MIN_TEXT = 100
PLACEHOLDER_TEXT = 600

# A shared mailbox or host proves nothing about one company: consumer and ISP mail, accounting and
# payroll software, accounting-firm chains, banks, telecoms and public-sector bodies. Not exhaustive;
# the page checks and the registry-field requirement are the other guards.
NOT_CORROBORATING = frozenset((
    'gmail.com', 'googlemail.com', 'hotmail.com', 'hotmail.no', 'outlook.com', 'outlook.no', 'live.com', 'live.no',
    'msn.com', 'yahoo.com', 'yahoo.no', 'icloud.com', 'me.com', 'mac.com', 'proton.me', 'protonmail.com', 'gmx.com',
    'online.no', 'getmail.no', 'broadpark.no', 'c2i.net', 'start.no', 'frisurf.no', 'lyse.net', 'altibox.no',
    'telenor.no', 'telenor.net', 'telia.com', 'telia.no', 'chello.no', 'combo.no', 'tele2.no', 'powertech.no',
    'bbnett.no', 'ntebb.no', 'hotelcloud.no', 'webmail.no', 'epost.no',
    'tripletex.no', 'tripletex.com', 'fiken.no', 'visma.com', 'visma.no', 'conta.no', 'ageras.no', 'cloudnine.no',
    'pwc.no', 'pwc.com', 'kpmg.no', 'kpmg.com', 'ey.com', 'no.ey.com', 'bdo.no', 'deloitte.no', 'azets.no', 'azets.com',
    'crowe.no', 'mazars.no', 'grantthornton.no', 'moore.no', 'regnskapsfokus.no', 'unimicro.no', 'poweroffice.no',
    'dnb.no', 'nordea.com', 'nordea.no', 'sparebank1.no', 'danskebank.no', 'handelsbanken.no',
    'nav.no', 'altinn.no', 'brreg.no', 'skatteetaten.no',
))
PUBLIC_SECTOR = ('kommune.no', 'fylke.no', 'fylkeskommune.no', 'stat.no', 'dep.no', 'mil.no', 'gov.no', 'herad.no',
                 'vgs.no', 'fhs.no', 'folkebibl.no')

PARKED = ('domain is for sale', 'domain for sale', 'this domain', 'buy this domain', 'hugedomains', 'parked at',
          'domain parking', 'miss hosting', 'her flytter snart en ny gjest', 'has been informing visitors',
          'domenet er til salgs', 'domene til salgs', 'domenet selges', 'dette domenet', 'kjop dette domenet',
          'find the best information and most relevant links on all topics related to')
PLACEHOLDER = ('coming soon', 'kommer snart', 'under construction', 'under bygging', 'under utvikling',
               'default web site page', 'welcome to nginx', 'it works!', 'index of /', 'account suspended',
               'siden er ikke tilgjengelig', 'site not found')
# A group, parent or ownership marker in an identity zone: the page may describe another organisation.
GROUP_MARKER = re.compile(r'konsern\w*|datterselskap\w*|morselskap\w*|s[øo]sterselskap\w*|(?:del|deler)\s+av\b|'
                          r'part\s+of\b|member\s+of\b|medlem\s+av\b|subsidiar\w*|parent\s+company|owned\s+by\b|'
                          r'eies\s+av\b|eid\s+av\b', re.I)
VAT_NUMBER = re.compile(r'(?<![0-9])(?:NO\s*)?([0-9]{3}[ .]?[0-9]{3}[ .]?[0-9]{3})\s*MVA', re.I)


# Boundaries of these elements separate words: <div>Firma AS</div><div>Gate 1</div> is not "Firma ASGate 1".
BLOCK_BREAK = frozenset(('div', 'p', 'li', 'ul', 'ol', 'td', 'th', 'tr', 'table', 'section', 'article', 'header', 'footer',
                         'nav', 'aside', 'address', 'main', 'form', 'dl', 'dt', 'dd', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'))


class Home(Sections):
    """Sections plus og:site_name meta tags and the visible body text (no head, scripts, hidden or comments)."""

    def __init__(self, raw):
        self.sitename, self.visible = [], []
        super().__init__(raw)

    def handle_endtag(self, tag):
        if tag in BLOCK_BREAK:
            self.handle_data(' ')
        super().handle_endtag(tag)

    def handle_starttag(self, tag, attrs):
        if tag in BLOCK_BREAK:
            self.handle_data(' ')
        values = dict(attrs)
        if (tag == 'meta' and (values.get('property') or values.get('name') or '').lower() == 'og:site_name'
                and not any(x['hidden'] for x in self.stack)):
            start = self.position()
            self.sitename.append((' '.join((values.get('content') or '').split()), start,
                                  self.source.find('>', start) + 1))
        super().handle_starttag(tag, attrs)

    def handle_data(self, data):
        if not any(x['hidden'] or x['tag'] in ('head', 'title') for x in self.stack):
            self.visible.append(data)
        super().handle_data(data)


def excluded(domain, mail=False):
    """Shared, directory, platform and public-sector domains never corroborate or become a website.

    mail=True also excludes shared mail providers, software vendors, banks and agencies as an
    e-mail domain; a company that is itself one of them still ties its own host by its legal name.
    """
    listed = set(SHARED_DOMAINS) | set(DIRECTORY_HOSTS) | set(PUBLIC_SECTOR) | (NOT_CORROBORATING if mail else set())
    return any(domain == d or domain.endswith('.' + d) for d in listed) or denylisted(domain)


def email_domain(value):
    match = re.fullmatch(r'[^\s@]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})', value.strip()) if isinstance(value, str) else None
    return match[1].lower() if match else None


def corroboration(legal_name, host, email):
    """Facts of the registry row itself that tie the registered host to this company."""
    site = host.removeprefix('www.')
    if excluded(site) or registrable_domain(site) is None:
        return []
    result = []
    domain = email_domain(email)
    if domain and not excluded(domain, mail=True) and registrable_domain(domain) == registrable_domain(site):
        result.append({'kind': 'email_domain', 'registry_field': 'epostadresse', 'registry_value': email.strip(),
                       'domain': registrable_domain(site)})
    if name_domain_tie(legal_name, site):
        result.append({'kind': 'name_host_label', 'registry_field': 'navn', 'registry_value': legal_name, 'domain': site})
    return result


def conflicting_numbers(text, scripts, subject):
    found = org_numbers(text) | {re.sub(r'\D', '', m) for m in VAT_NUMBER.findall(text)}
    for script in scripts:
        try:
            parsed = loads(script)
        except ValueError:
            continue
        for _, node in nodes(parsed):
            for key in ('identifier', 'taxID', 'vatID'):
                values = node.get(key)
                for value in values if isinstance(values, list) else [values]:
                    value = value.get('value') if isinstance(value, dict) else value
                    if isinstance(value, str) and len(re.sub(r'\D', '', value)) == 9:
                        found.add(re.sub(r'\D', '', value))
    return found - {subject}


# A name continued by one of these words, or preceded by a capitalised name word, is another entity's name.
NAME_EXTENSION = re.compile(r'\s*(?:holding|group|gruppen|invest|eiendom|norge|norway|sverige|sweden|danmark|denmark|'
                            r'international|nordic|europe|kapital|forvaltning)\b', re.I)
NAME_INTRO = frozenset(('om', 'about', 'kontakt', 'contact', 'hos', 'velkommen', 'welcome', 'til', 'to', 'for', 'av',
                        'by', 'fra', 'from', 'hjem', 'home', 'forside'))
FOREIGN_ENTITY = re.compile(r"(?<![\w&])(?:[\w&.'-]+\s+){1,4}(?:A/S|GmbH|Ltd\.?|Inc\.?|AB|Oy|SA|BV)(?![\w/])")
NORWEGIAN_ADDRESS = re.compile(r'[0-9]{1,3}\s?[A-Za-z]?,?\s+[0-9]{4}\s+[A-Z\u00c6\u00d8\u00c5][A-Za-z\u00e6\u00f8\u00e5\u00c6\u00d8\u00c5-]+')
CONTACT_MARKER = re.compile(r'@|(?<![0-9])(?:\+?47\s?)?[0-9]{2}\s?[0-9]{2}\s?[0-9]{2}\s?[0-9]{2}(?![0-9])|'
                            r'\b(?:tlf|tel|telefon|mobil|phone|adresse|address|kontakt|contact|org\.?\s?nr)\b', re.I)
NO_IDENTIFIER = ('no hard identifier on the page (organisation number, registry street with postcode or town, '
                 'or exact legal name with its legal form in title, heading, footer, copyright line or contact block)')


def name_pattern(legal_name):
    return r'\s+'.join(re.escape(w) for w in legal_name.split())


def exact_name(text, legal_name, prefix=True):
    """The whole legal name with its legal form as a name of its own, not part of a longer name.

    With prefix=True a capitalised word directly before the name (no separator between) continues it;
    footers and contact blocks pass prefix=False because address labels and towns precede the name there.
    """
    for match in re.finditer(r'(?<!\w)' + name_pattern(legal_name) + r'(?!\w)', text, re.I):
        before = re.search(r'([^\W\d_]+)\s*$', text[:match.start()])
        if prefix and before and before[1].lower() not in NAME_INTRO and not before[1][0].islower():
            continue
        if NAME_EXTENSION.match(text, match.end()):
            continue
        return True
    return False


def fold(value):
    return ' '.join(re.sub(r'[,;]', ' ', ascii_fold(value)).split())


def registry_streets(anchor):
    """Street lines of the registry business address (c/o and post box lines are not streets)."""
    address = anchor.get('forretningsadresse')
    lines = address.get('adresse') if isinstance(address, dict) else None
    lines = [lines] if isinstance(lines, str) else lines if isinstance(lines, list) else []
    result = []
    for line in lines:
        line = fold(line) if isinstance(line, str) else ''
        if len(line) >= 5 and re.search('[a-z]', line) and not re.match(r'(?:c/o|postboks|pb\b|boks)', line):
            result.append(line)
    return result


def number_pattern(subject):
    return re.compile(r'(?<![0-9])%s[ .]?%s[ .]?%s(?![0-9])' % (subject[:3], subject[3:6], subject[6:]))


def hard_identifier(home, subject, legal_name, anchor):
    """First hard identifier of this exact entity on the page and the smallest element that carries it."""
    by_size = sorted((n for n in home.nodes if n['tag'] not in ('html', 'body', 'head', 'script', 'style')
                      and n['text'] and len(n['text']) <= 1500), key=lambda n: (len(n['text']), n['start']))
    number = number_pattern(subject)
    node = next((n for n in by_size if number.search(n['text'])), None)
    if node:
        return {'kind': 'org_number', 'part': 'org_number'}, node
    address = anchor.get('forretningsadresse') if isinstance(anchor.get('forretningsadresse'), dict) else {}
    postcode, town = str(address.get('postnummer') or ''), fold(str(address.get('poststed') or ''))
    # "KRISTIANSUND N" is the post office of Kristiansund: a trailing single letter is not part of the town
    towns = {t for t in (town, re.sub(r' [a-z]$', '', town)) if t}
    for street in registry_streets(anchor):
        pattern = re.compile(r'(?<![a-z0-9])' + name_pattern(street) + r'(?![a-z0-9])')
        for node in by_size:
            folded = fold(node['text'])
            if pattern.search(folded) and (
                    (re.fullmatch(r'[0-9]{4}', postcode) and re.search(r'(?<![0-9])' + postcode + r'(?![0-9])', folded))
                    or any(re.search(r'(?<![a-z])' + re.escape(t) + r'(?![a-z])', folded) for t in towns)):
                return {'kind': 'registry_address', 'part': 'registry_address'}, node
    candidates = [('title', n) for n in home.nodes if n['tag'] == 'title' and n['text']]
    candidates += [('h1', n) for n in sorted((n for n in home.nodes if n['tag'] == 'h1' and n['text']),
                                             key=lambda n: n['start'])[:3]]
    candidates += [('footer', n) for n in sorted((n for n in home.nodes if n['tag'] in ('footer', 'address')
                                                  and len(n['text']) <= 3000), key=lambda n: (len(n['text']), n['start']))]
    mark = r'(?:(?:\u00a9|copyright|\(c\))\s*)+(?:[0-9]{4}[\s.,\u2013-]*)*(?:by\s+)?'
    copyright_name = re.compile(mark + name_pattern(legal_name) + r'(?!\w)', re.I)
    candidates += [('copyright', n) for n in by_size if len(n['text']) <= 400 and copyright_name.search(n['text'])]
    candidates += [('contact_block', n) for n in by_size if len(n['text']) <= 600 and CONTACT_MARKER.search(n['text'])]
    for part, node in candidates:
        if exact_name(node['text'], legal_name, prefix=part in ('title', 'h1', 'copyright')):
            return {'kind': 'legal_name', 'part': part}, node
    return None, None


def foreign_parent(home, text, subject, legal_name):
    """A footer or copyright line naming a foreign-form entity while the page shows nothing Norwegian."""
    lines = [n['text'] for n in home.nodes if n['tag'] in ('footer', 'address')
             or (len(n['text']) <= 400 and re.search('\u00a9|copyright|\\(c\\)', n['text'], re.I))]
    if not any(FOREIGN_ENTITY.search(re.sub(name_pattern(legal_name), ' ', line, flags=re.I)) for line in lines):
        return False
    return not (exact_name(text, legal_name) or number_pattern(subject).search(text) or NORWEGIAN_ADDRESS.search(text))


def website_assessment(raw, subject, anchor, page_url):
    """Decide whether this retained page publishes the registry-declared website; always explains why."""
    result = {'publishable': False, 'score': 0.0, 'status': 'abstain', 'method': METHOD, 'path': 'registry_corroborated',
              'reasons': [], 'corroboration': [], 'span': None, 'locator': None, 'identifier': None,
              'visible_text_sha256': None}

    def refuse(reason):
        result['reasons'] = [reason]
        return result

    legal_name = anchor.get('navn') or ''
    try:
        registered = urlsplit(website_candidate(anchor.get('hjemmeside', '')))
    except (SourceUnavailable, ValueError, TypeError):
        return refuse('registry row has no usable website')
    page = urlsplit(page_url)
    if registered.path not in ('', '/') or registered.query:
        return refuse('only a registered site root is a homepage candidate')
    if not legal_name or page.hostname not in website_hosts(registered.hostname):
        return refuse('page host is not the registry-declared host or its www alias')
    result['corroboration'] = corroboration(legal_name, page.hostname, anchor.get('epostadresse'))
    if not result['corroboration']:
        return refuse('no corroboration from the registry row (epostadresse domain or legal name equal to host label)')
    home = Home(raw)
    # Join chunks with nothing between them. A space join splits <b> inside a word.
    # Block and void tags already append their own gap. Same rule as the auditor.
    text = ' '.join(''.join(home.visible).split())
    result['visible_text_sha256'] = digest(text.encode('utf-8'))
    if len(text) < MIN_TEXT:
        return refuse('page has no readable text (fewer than %d visible characters, static fetch)' % MIN_TEXT)
    title = next((n for n in home.nodes if n['tag'] == 'title' and n['text']), None)
    headings = sorted((n for n in home.nodes if n['tag'] == 'h1' and n['text']), key=lambda n: n['start'])[:3]
    folded = ascii_fold(text + ' ' + (title['text'] if title else ''))
    if (any(m in folded for m in PARKED)
            or (len(text) < PLACEHOLDER_TEXT and any(m in folded for m in PLACEHOLDER))):
        return refuse('parked or placeholder page')
    zones = [n['text'] for n in ([title] if title else []) + headings] + [s[0] for s in home.sitename if s[0]]
    footers = [n['text'] for n in home.nodes if n['tag'] in ('footer', 'address')]
    if conflicting_numbers(text, Page(raw).scripts, subject):
        return refuse('conflicting organisation number on the page')
    if any(OTHER_ENTITY.search(re.sub(re.escape(legal_name), ' ', zone, flags=re.I)) for zone in zones):
        return refuse('title, heading or site name names another legal entity')
    if any(GROUP_MARKER.search(zone) for zone in zones + footers):
        return refuse('group, parent or ownership marker in an identity zone')
    if foreign_parent(home, text, subject, legal_name):
        return refuse('foreign parent entity in footer or copyright line and no Norwegian legal name, number or address')
    identifier, node = hard_identifier(home, subject, legal_name, anchor)
    if identifier is None:
        return refuse(NO_IDENTIFIER)
    strong = identifier['kind'] == 'org_number' or identifier['part'] in ('title', 'h1')
    result.update(publishable=True, status='exact', score=0.95 if strong or len(result['corroboration']) > 1 else 0.9,
                  identifier=identifier, span=raw.decode('utf-8')[node['start']:node['end']],
                  locator={'html_start': node['start'], 'html_end': node['end'], 'identity_part': identifier['part']},
                  reasons=['registry row corroborates the registered host (' + ', '.join(
                               c['registry_field'] for c in result['corroboration']) + ')',
                           'hard identifier on the page: ' + identifier['kind'].replace('_', ' ') + ' (' + identifier['part'] + ')',
                           'page loads over HTTPS, is readable (%d visible characters) and is not parked' % len(text),
                           'no conflicting organisation number, other legal entity, group or foreign-parent marker'])
    return result


def website_decision(raw, receipt, sid, subject, anchor):
    """A verified_website decision for the retained page, or None; claim and evidence match the other web routes."""
    assessment = website_assessment(raw, subject, anchor, receipt['effective_url'])
    if not assessment['publishable']:
        return None
    cid = claim_id(subject, 'verified_website', SCOPE)
    eid = sid + ':' + cid
    claim = {'claim_id': cid, 'field': 'verified_website', 'value': 'https://' + receipt['declared_host'] + '/',
             'scope': SCOPE, 'family': 'website_owned_profiles', 'item_key': None, 'period': None,
             'availability': 'available', 'evidence_ids': [eid], 'freshness': 'live_source'}
    shown = {key: assessment[key] for key in ('method', 'path', 'status', 'score', 'reasons', 'corroboration', 'identifier',
                                                     'visible_text_sha256')}
    shown.update(anchor_snapshot_id=receipt['ownership_anchor_snapshot_id'], legal_name=anchor['navn'],
                 registry_website=anchor['hjemmeside'], page_url=receipt['effective_url'])
    evidence = {'id': eid, 'snapshot_id': sid, 'source_url': receipt['effective_url'], 'source_class': 'company_owned',
                'source_origin': receipt['source_origin'], 'retrieved_at': receipt['retrieved_at'],
                'content_sha256': digest(raw), 'claim_span': assessment['span'], 'locator': assessment['locator'],
                'extraction_method': METHOD, 'identity_assessment': shown}
    return {'field': 'verified_website', 'family': 'website_owned_profiles', 'accepted': True,
            'claim': claim, 'evidence': evidence}
