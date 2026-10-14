"""Independent audit of the registry-corroborated website claim.

Re-derives everything from retained bytes: the registry row (via the anchor), the page receipt chain, the page's
readable text, its title/heading, conflicts and the corroboration. Imports no maker extraction or acceptance.
"""
import hashlib
import json
import re
import unicodedata
from html.parser import HTMLParser
from urllib.parse import urlsplit

from .public_suffix_data import PUBLIC_SUFFIXES

SCOPE, METHOD, PATH = 'registry_declared_host_name_gate', 'registry_host_corroboration_v1', 'registry_corroborated'
ASSESSMENT_KEYS = {'method', 'path', 'status', 'score', 'reasons', 'corroboration', 'anchor_snapshot_id', 'legal_name', 'identifier', 'visible_text_sha256',
                   'registry_website', 'page_url'}
CORROBORATION_KEYS = {'kind', 'registry_field', 'registry_value', 'domain'}
LOCATOR_KEYS = {'html_start', 'html_end', 'identity_part'}

# Domains whose mailbox or site says nothing about who owns a website. FREE_OR_SHARED blocks every corroboration.
FREE_OR_SHARED = (
    'gmail.com googlemail.com hotmail.com hotmail.no outlook.com outlook.no live.com live.no msn.com yahoo.com yahoo.no '
    'icloud.com me.com mac.com proton.me protonmail.com gmx.com gmx.net aol.com mail.com yandex.com zoho.com fastmail.com '
    'tutanota.com online.no getmail.no broadpark.no c2i.net start.no frisurf.no lyse.net chello.no combo.no tele2.no '
    'powertech.no bbnett.no ntebb.no hotelcloud.no webmail.no epost.no nav.no altinn.no brreg.no skatteetaten.no '
    'wixsite.com wix.com squarespace.com myshopify.com github.io gitlab.io github.com gitlab.com netlify.app vercel.app '
    'weebly.com jimdosite.com jimdofree.com business.site blogspot.com wordpress.com pages.dev herokuapp.com webflow.io '
    'carrd.co framer.app wixstudio.io azurewebsites.net web.app godaddysites.com tumblr.com ucoz.com 000webhostapp.com '
    'medium.com substack.com notion.site notion.so linktr.ee mystrikingly.com strikingly.com sites.google.com '
    'proff.no gulesider.no 1881.no finn.no facebook.com instagram.com linkedin.com x.com twitter.com youtube.com '
    'google.com wikipedia.org wikidata.org bisnode.no bisnode.com creditsafe.com creditsafe.no dnb.com purehelp.no '
    'mittanbud.no regnskapstall.no forretning.no ratsit.se allabolag.se opencorporates.com crunchbase.com '
    'mynewsdesk.com tripadvisor.com yelp.com trustpilot.com').split()
# Software, accountant, bank and telco domains: they never corroborate by mailbox, but may be a company's own name.
MAIL_VENDORS = (
    'tripletex.no tripletex.com fiken.no visma.com visma.no conta.no ageras.no cloudnine.no ey.com bdo.no deloitte.no '
    'crowe.no mazars.no grantthornton.no moore.no regnskapsfokus.no unimicro.no poweroffice.no dnb.no sparebank1.no '
    'danskebank.no handelsbanken.no altibox.no telenor.no telenor.net telia.com telia.no').split()
VENDOR_LABELS = frozenset('pwc kpmg azets nordea'.split())
PUBLIC_SECTOR = ('kommune.no fylke.no fylkeskommune.no stat.no dep.no mil.no gov.no herad.no vgs.no fhs.no '
                 'folkebibl.no').split()
SUFFIXES = PUBLIC_SUFFIXES | {'fylkeskommune.no', 'gov.no'}
SECOND_LEVEL = frozenset('co com org net ac gov edu mil ne or go ltd plc me sch nhs'.split())
LEGAL_FORMS = r'(?:a/s|as|asa|ans|da|nuf|sa|se|ab|oy|ltd|inc|llc|gmbh|bv|plc)'
ENTITY_FORMS = 'AS ASA ANS DA NUF SA SE AB A/S Oy Ltd Inc LLC GmbH BV PLC ApS AG ENK KS IKS BA SARL SAS NV'.split()
ENTITY = re.compile(r"(?<![\w&])(?:[\w&.'-]+\s+){1,5}(?:" + '|'.join(re.escape(f) for f in sorted(ENTITY_FORMS, key=len, reverse=True))
                    + r")(?![\w/])")
GROUP = re.compile(r'(?<!\w)(?:konsern\w*|datterselskap\w*|morselskap\w*|s(?:ø|o)ster-?selskap\w*|del\s+av|deler\s+av|'
                   r'part\s+of|member\s+of|medlem\s+av|subsidiar\w*|parent\s+company|owned\s+by|eies\s+av|eid\s+av)(?!\w)',
                   re.I)
LABELLED = re.compile(r'(?:org(?:anisasjons)?\.?\s*(?:nr|nummer)\.?|organi[sz]ation\s+(?:number|no\.?))\s*:?\s*'
                      r'(?:NO\s*)?([0-9]{3}[ .]?[0-9]{3}[ .]?[0-9]{3})(?![0-9])', re.I)
VAT = re.compile(r'(?<![0-9])(?:NO\s*)?([0-9]{3}[ .]?[0-9]{3}[ .]?[0-9]{3})\s*MVA(?!\w)', re.I)
PARKED = ('domain is for sale', 'domain for sale', 'this domain', 'buy this domain', 'hugedomains', 'parked at',
          'domain parking', 'miss hosting', 'her flytter snart en ny gjest', 'has been informing visitors',
          'domenet er til salgs', 'domene til salgs', 'domenet selges', 'dette domenet', 'kjop dette domenet',
          'find the best information and most relevant links on all topics related to')
PLACEHOLDER = ('coming soon', 'kommer snart', 'under construction', 'under bygging', 'under utvikling',
               'default web site page', 'welcome to nginx', 'it works!', 'index of /', 'account suspended',
               'siden er ikke tilgjengelig', 'site not found')
VOID = frozenset('br hr img input meta link source wbr area base embed param track col'.split())
BLOCK = frozenset('div p li ul ol td th tr table section article header footer nav aside address main form dl dt dd '
                  'h1 h2 h3 h4 h5 h6'.split())
HIDDEN_TAGS = frozenset('script style template noscript'.split())


def norm(text):
    return ' '.join(text.split())


def fold(text):
    text = text.lower().replace('æ', 'ae').replace('ø', 'o').replace('å', 'a')
    return ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))


def stem(text):
    return re.sub(r'[^a-z0-9]', '', re.sub(r'(?<!\w)' + LEGAL_FORMS + r'(?!\w)', ' ', fold(text)))


def whole_word(name, text):
    return re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', text, re.I) is not None


class Page(HTMLParser):
    """Titles, headings, footers, site name, JSON-LD and the readable text, with source offsets."""

    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.source = raw.decode('utf-8')
        self.offsets = [0]
        for line in self.source.split('\n')[:-1]:
            self.offsets.append(self.offsets[-1] + len(line) + 1)
        self.stack, self.titles, self.h1s, self.footers, self.site_names, self.scripts, self.chunks = [], [], [], [], [], [], []
        self.elements = []
        self.feed(self.source)
        self.close()
        self.visible = norm(''.join(self.chunks))

    def position(self):
        line, col = self.getpos()
        return self.offsets[line - 1] + col

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        parent_hidden = bool(self.stack) and self.stack[-1]['hidden']
        hidden = (parent_hidden or tag in HIDDEN_TAGS or 'hidden' in attrs or attrs.get('aria-hidden') == 'true'
                  or re.search(r'(?:display\s*:\s*none|visibility\s*:\s*hidden)', attrs.get('style') or '', re.I) is not None)
        if tag in VOID:
            if tag == 'meta' and not hidden and (attrs.get('property') or attrs.get('name') or '').strip().lower() == 'og:site_name':
                self.site_names.append(norm(attrs.get('content') or ''))
            self.handle_data(' ')
            return
        tags = {el['tag'] for el in self.stack}
        self.stack.append({'tag': tag, 'start': self.position(), 'hidden': hidden, 'text': '', 'raw': '', 'buf': '',
                           'quoted': bool(tags & {'blockquote', 'q'}) or tag in ('blockquote', 'q'), 'svg': 'svg' in tags,
                           'in_head': 'head' in tags or tag == 'head',
                           'ld': tag == 'script' and (attrs.get('type') or '').strip().lower() == 'application/ld+json'})
        if tag in BLOCK:
            self.handle_data(' ')

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_data(self, data):
        if not self.stack:
            self.chunks.append(data)
            return
        top = self.stack[-1]
        if top['ld']:
            top['buf'] += data
        tags = {el['tag'] for el in self.stack}
        if not tags & {'script', 'style'}:
            quoted = bool(tags & {'blockquote', 'q'})
            for el in self.stack:
                el['raw'] += data
                if not top['hidden'] and not quoted:
                    el['text'] += data
        if not top['hidden'] and not tags & {'head', 'title'}:
            self.chunks.append(data)

    def handle_endtag(self, tag):
        index = next((i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i]['tag'] == tag), None)
        if index is None:
            return
        if tag in BLOCK:
            self.handle_data(' ')
        node = self.stack[index]
        del self.stack[index:]
        end = self.source.find('>', self.position())
        if end < 0:
            return
        node['end'] = end + 1
        node['text'] = norm(node['text'])
        self.elements.append(node)
        if tag == 'title' and not node['svg']:
            self.titles.append(node)
        elif tag == 'h1' and not node['hidden'] and not node['quoted']:
            self.h1s.append(node)
        elif tag in ('footer', 'address'):
            self.footers.append(norm(node['raw']))
        elif node['ld']:
            self.scripts.append(node['buf'])


def website_candidate(value):
    """The registered site host and nothing else, or None when the row does not declare a plain root address."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or re.search(r'\s', value):
        return None
    try:
        parts = urlsplit(value if '://' in value else 'https://' + value)
        port = parts.port
    except ValueError:
        return None
    host = parts.hostname
    if (parts.scheme not in ('http', 'https') or not host or '.' not in host or host.endswith('.') or port is not None
            or parts.username is not None or parts.password is not None or parts.query or parts.fragment
            or parts.path not in ('', '/') or '?' in value or '#' in value):
        return None
    return host


def registrable(host):
    """The registrable domain, or None when the name is a public suffix or a bare label."""
    labels = host.lower().removeprefix('www.').split('.')
    if len(labels) < 2 or '' in labels:
        return None
    two = '.'.join(labels[-2:])
    suffix2 = (two in SUFFIXES
               or (labels[-1] != 'no' and len(labels[-1]) == 2 and labels[-2] in SECOND_LEVEL))
    if suffix2:
        return '.'.join(labels[-3:]) if len(labels) > 2 else None
    return '.'.join(labels[-2:])


def listed(host, entries):
    return any(host == entry or host.endswith('.' + entry) for entry in entries)


def shared_host(host):
    """Platform, directory, social, free or provider mail and public-sector names never identify one company."""
    host = host.lower().removeprefix('www.')
    return registrable(host) is None or listed(host, FREE_OR_SHARED) or listed(host, PUBLIC_SECTOR)


def vendor_domain(domain):
    domain = domain.lower()
    own = registrable(domain)
    return (shared_host(domain) or listed(domain, MAIL_VENDORS)
            or (own is not None and own.split('.')[0] in VENDOR_LABELS))


def corroboration(anchor, site):
    """The corroborations the registry row itself gives for the site host, email first."""
    result, host = [], site.removeprefix('www.')
    email = anchor.get('epostadresse')
    if isinstance(email, str):
        email = email.strip()
        found = re.fullmatch(r'[^@\s,;<>]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)', email)
        if found:
            mailbox = found[1].lower()
            own = registrable(mailbox)
            if own is not None and own == registrable(host) and not vendor_domain(mailbox) and not shared_host(host):
                result.append({'kind': 'email_domain', 'registry_field': 'epostadresse', 'registry_value': email,
                               'domain': own})
    own = registrable(host)
    if own == host and not shared_host(host):
        label = host.split('.')[0]
        name = anchor['navn']
        if (re.fullmatch(r'[a-z0-9-]+', label) and not label.startswith('xn--') and len(stem(name)) >= 4
                and stem(label) == stem(name)):
            result.append({'kind': 'name_host_label', 'registry_field': 'navn', 'registry_value': name, 'domain': host})
    return result


def foreign_numbers(text, subject):
    found = {re.sub(r'\D', '', n) for n in LABELLED.findall(text) + VAT.findall(text)}
    return found - {subject}


def structured_ids(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ('identifier', 'taxID', 'vatID'):
                yield from flatten(value)
            yield from structured_ids(value)
    elif isinstance(node, list):
        for value in node:
            yield from structured_ids(value)


def flatten(value):
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        yield str(value)
    elif isinstance(value, dict):
        for key in ('value', '@value', 'identifier'):
            if key in value:
                yield from flatten(value[key])
    elif isinstance(value, list):
        for item in value:
            yield from flatten(item)


def normal_id(value):
    value = re.sub(r'[\s.\-]', '', value).upper().removeprefix('NO').removesuffix('MVA')
    return value if re.fullmatch(r'[0-9]{9}', value) else None


def structured_conflict(scripts, subject):
    values = []
    for script in scripts:
        try:
            values.extend(structured_ids(json.loads(script)))
        except ValueError:
            values.extend(re.findall(r'"(?:identifier|taxID|vatID)"\s*:\s*"([^"]*)"', script))
    return {normal_id(v) for v in values} - {None, subject}



NOT_ELEMENTS = frozenset('html body head script style'.split())
LEAD_WORDS = frozenset('om about kontakt contact hos velkommen welcome til to for av by fra from hjem home forside'.split())
TRAIL_WORDS = frozenset('holding group gruppen invest eiendom norge norway sverige sweden danmark denmark international '
                        'nordic europe kapital forvaltning'.split())
CONTACT_WORDS = re.compile(r'(?<!\w)(?:tlf|tel|telefon|mobil|phone|adresse|address|kontakt|contact)(?!\w)|org\.?\s*nr', re.I)
COPYRIGHT_MARK = re.compile(r'©|copyright|\(c\)', re.I)
COPYRIGHT_BEFORE = re.compile(r'(?:(?:©|\(c\)|copyright)\s*)+(?:[0-9]{4}(?:\s*[-–—,/]\s*[0-9]{4})*\s*[-.,–—:]?\s*)?'
                              r'(?:by\s+)?$', re.I)
FOREIGN = re.compile(r"(?<![\w&/])(?:[\w&.'-]+\s+){1,4}(?:A/S|GmbH|Ltd\.?|Inc\.?|AB|Oy|SA|BV)(?![\w/])")
NORWEGIAN_ADDRESS = re.compile(r'(?<![0-9])[0-9]{1,3}[A-Za-z]?,?\s+[0-9]{4}\s+[A-ZÆØÅ][\wÆØÅæøå-]*')


def number_pattern(subject):
    a, b, c = subject[:3], subject[3:6], subject[6:]
    forms = {a + b + c, a + ' ' + b + ' ' + c, a + '.' + b + '.' + c, a + ' ' + b + '.' + c}
    return re.compile(r'(?<![0-9])(?:' + '|'.join(re.escape(f) for f in forms) + r')(?![0-9])')


def own_name(name, text, lead=True):
    """The legal name written as a name of its own: not the tail of a longer capitalised name, not a longer name's head."""
    pattern = r'(?<!\w)' + r'\s+'.join(re.escape(word) for word in name.split()) + r'(?!\w)'
    for found in re.finditer(pattern, text, re.I):
        word = re.search(r'(\w+)\s+$', text[:found.start()])
        if lead and word and word[1][:1].isupper() and word[1].lower() not in LEAD_WORDS:
            continue
        after = re.match(r'\s+(\w+)', text[found.end():])
        if after and after[1].lower() in TRAIL_WORDS:
            continue
        return found
    return None


def address_fold(text):
    return ' '.join(re.sub(r'[,;]', ' ', fold(text)).split())


def streets(anchor):
    address = anchor.get('forretningsadresse')
    lines = address.get('adresse') if isinstance(address, dict) else None
    lines = lines.split('\n') if isinstance(lines, str) else lines if isinstance(lines, list) else []
    found = []
    for line in lines:
        if isinstance(line, str):
            line = address_fold(line)
            if len(line) >= 5 and re.search(r'[a-z]', line) and not re.match(r'(?:c/o|postboks|pb|boks)(?![a-z0-9])', line):
                found.append(line)
    return found


def registry_address_hit(anchor, text):
    address = anchor.get('forretningsadresse')
    if not isinstance(address, dict):
        return False
    folded = address_fold(text)
    postcode = address.get('postnummer')
    town = address.get('poststed')
    folded_town = address_fold(town) if isinstance(town, str) else ''
    towns = [folded_town] if folded_town else []
    # A trailing post-office letter (KRISTIANSUND N) is not required on the page.
    short = re.sub(r' [a-z]$', '', folded_town)
    if short and short != folded_town:
        towns.append(short)
    for street in streets(anchor):
        if not re.search(r'(?<![a-z0-9])' + re.escape(street) + r'(?![a-z0-9])', folded):
            continue
        if ((isinstance(postcode, str) and re.fullmatch(r'[0-9]{4}', postcode)
                and re.search(r'(?<![0-9])' + postcode + r'(?![0-9])', folded))
                or any(re.search(r'(?<![a-z])' + re.escape(item) + r'(?![a-z])', folded) for item in towns)):
            return True
    return False


def contact_marker(text):
    if '@' in text or CONTACT_WORDS.search(text):
        return True
    for found in re.finditer(r'(?<![0-9])(?:\+|00)?[0-9][0-9 .-]{6,16}[0-9](?![0-9])', text):
        digits = re.sub(r'\D', '', found[0])
        if len(digits) == 8 or (len(digits) in (10, 12) and digits.startswith(('47', '0047'))):
            return True
    return False


def identifier(page, subject, anchor):
    """(kind, part, {(start, end)}) of the first hard identifier by priority, or None."""
    name = anchor['navn']
    eligible = [e for e in page.elements if not e['hidden'] and not e['quoted'] and not e['in_head']
                and e['tag'] not in NOT_ELEMENTS]
    candidates = [e for e in eligible if 1 <= len(e['text']) <= 1500]
    number = number_pattern(subject)
    hits = {(e['start'], e['end']) for e in candidates if number.search(e['text'])}
    if hits:
        return 'org_number', 'org_number', hits
    hits = {(e['start'], e['end']) for e in candidates if registry_address_hit(anchor, e['text'])}
    if hits:
        return 'registry_address', 'registry_address', hits
    title = next((t for t in page.titles if t['text']), None)
    if title and own_name(name, title['text']):
        return 'legal_name', 'title', {(title['start'], title['end'])}
    headings = [h for h in page.h1s if h['text']][:3]
    hits = {(h['start'], h['end']) for h in headings if own_name(name, h['text'])}
    if hits:
        return 'legal_name', 'h1', hits
    hits = {(e['start'], e['end']) for e in eligible if e['tag'] in ('footer', 'address') and 1 <= len(e['text']) <= 3000
            and own_name(name, e['text'], lead=False)}
    if hits:
        return 'legal_name', 'footer', hits
    hits = set()
    for e in candidates:
        if len(e['text']) > 400:
            continue
        for found in own_name_matches(name, e['text']):
            word = re.search(r'(\w+)\s+$', e['text'][:found.start()])
            if word and word[1][:1].isupper() and word[1].lower() not in LEAD_WORDS:
                continue
            if COPYRIGHT_BEFORE.search(e['text'][:found.start()]):
                hits.add((e['start'], e['end']))
                break
    if hits:
        return 'legal_name', 'copyright', hits
    hits = {(e['start'], e['end']) for e in candidates if len(e['text']) <= 600 and own_name(name, e['text'], lead=False)
            and contact_marker(e['text'])}
    if hits:
        return 'legal_name', 'contact_block', hits
    return None


def own_name_matches(name, text):
    """Every whole-word occurrence of the name that no longer name follows."""
    pattern = r'(?<!\w)' + r'\s+'.join(re.escape(word) for word in name.split()) + r'(?!\w)'
    for found in re.finditer(pattern, text, re.I):
        after = re.match(r'\s+(\w+)', text[found.end():])
        if not (after and after[1].lower() in TRAIL_WORDS):
            yield found


def foreign_parent(page, name, subject):
    eligible = [e for e in page.elements if not e['hidden'] and not e['quoted'] and not e['in_head']
                and e['tag'] not in NOT_ELEMENTS]
    lines = [e['text'] for e in eligible if e['tag'] in ('footer', 'address')]
    lines += [e['text'] for e in eligible if 1 <= len(e['text']) <= 400 and COPYRIGHT_MARK.search(e['text'])]
    named = re.compile(r'(?<!\w)' + r'\s+'.join(re.escape(word) for word in name.split()) + r'(?!\w)', re.I)
    if not any(FOREIGN.search(named.sub(' ', line)) for line in lines):
        return False
    return not (own_name(name, page.visible) or number_pattern(subject).search(page.visible)
                or NORWEGIAN_ADDRESS.search(page.visible))


def derive(raw, subject, anchor, site):
    """Everything the claim must say, or ValueError naming the first reason the page cannot publish."""
    page = Page(raw)
    name = anchor['navn']
    found = corroboration(anchor, site)
    if not found:
        raise ValueError('Audit website lacks registry corroboration')
    if len(page.visible) < 100:
        raise ValueError('Audit website page is not readable')
    title = next((t for t in page.titles if t['text']), None)
    headings = [h for h in page.h1s if h['text']][:3]
    folded = fold(page.visible + ' ' + (title['text'] if title else ''))
    if any(p in folded for p in PARKED) or (len(page.visible) < 600 and any(p in folded for p in PLACEHOLDER)):
        raise ValueError('Audit website page is parked or a placeholder')
    if foreign_numbers(page.visible, subject) or structured_conflict(page.scripts, subject):
        raise ValueError('Audit website page carries another organisation number')
    texts = [title['text']] if title else []
    texts += [h['text'] for h in headings] + [s for s in page.site_names if s]
    named = re.compile(r'(?<!\w)' + re.escape(name) + r'(?!\w)', re.I)
    if any(ENTITY.search(named.sub(' ', text)) for text in texts):
        raise ValueError('Audit website page names another legal entity')
    if any(GROUP.search(text) for text in texts + page.footers):
        raise ValueError('Audit website page carries a group or ownership marker')
    if foreign_parent(page, name, subject):
        raise ValueError('Audit website page belongs to a foreign parent entity')
    hard = identifier(page, subject, anchor)
    if hard is None:
        raise ValueError('Audit website page carries no hard identifier of the entity')
    kind, part, spans = hard
    score = 0.95 if kind == 'org_number' or part in ('title', 'h1') or len(found) == 2 else 0.9
    return {'spans': spans, 'kind': kind, 'part': part, 'source': page.source, 'corroboration': found, 'score': score,
            'visible_sha': hashlib.sha256(page.visible.encode('utf-8')).hexdigest()}


def audit_website(subject, claim, item, receipt, raw, anchor, proof):
    try:
        _audit(subject, claim, item, receipt, raw, anchor, proof)
    except (KeyError, TypeError, AttributeError, IndexError) as error:
        raise ValueError('Audit website claim is malformed: %r' % (error,)) from error


def _audit(subject, claim, item, receipt, raw, anchor, proof):
    if proof:
        raise ValueError('Audit website corroboration is not published beside a legal operator proof')
    name, registered = anchor.get('navn'), anchor.get('hjemmeside')
    if not isinstance(name, str) or not name.strip():
        raise ValueError('Audit website registry name absent')
    declared = website_candidate(registered)
    page_url = urlsplit(receipt['effective_url'])
    host = receipt['declared_host']
    content_type = receipt.get('content_type')
    if (declared is None or page_url.scheme != 'https' or page_url.hostname != host or page_url.port is not None
            or page_url.username is not None or page_url.password is not None
            or host not in {declared, declared.removeprefix('www.'), 'www.' + declared.removeprefix('www.')}
            or receipt.get('http_status') != 200 or receipt.get('robots_checked') is not True
            or receipt.get('organisation_number') != subject or receipt.get('source_class') != 'company_owned'
            or not isinstance(content_type, str) or 'html' not in content_type.lower().split(';')[0]
            or receipt.get('sha256') != hashlib.sha256(raw).hexdigest()):
        raise ValueError('Audit website page is not the registered host or its receipt is invalid')
    derived = derive(raw, subject, dict(anchor, navn=name), host)
    location = item.get('locator')
    if (not isinstance(location, dict) or set(location) != LOCATOR_KEYS
            or type(location['html_start']) is not int or type(location['html_end']) is not int
            or (location['html_start'], location['html_end']) not in derived['spans']
            or location['identity_part'] != derived['part']
            or item.get('claim_span') != derived['source'][location['html_start']:location['html_end']]
            or 'support_spans' in item):
        raise ValueError('Audit website span is not an element that carries the hard identifier')
    assessment = item.get('identity_assessment')
    reasons = assessment.get('reasons') if isinstance(assessment, dict) else None
    if (not isinstance(assessment, dict) or set(assessment) != ASSESSMENT_KEYS
            or not isinstance(reasons, list) or not reasons or any(not isinstance(r, str) or not r for r in reasons)
            or assessment['method'] != METHOD or assessment['path'] != PATH or assessment['status'] != 'exact'
            or type(assessment['score']) is not float or assessment['score'] != derived['score']
            or assessment['corroboration'] != derived['corroboration']
            or any(set(c) != CORROBORATION_KEYS for c in assessment['corroboration'])
            or assessment['anchor_snapshot_id'] != receipt['ownership_anchor_snapshot_id']
            or assessment['legal_name'] != name or assessment['registry_website'] != registered
            or assessment['page_url'] != item['source_url']
            or assessment['identifier'] != {'kind': derived['kind'], 'part': derived['part']}
            or assessment['visible_text_sha256'] != derived['visible_sha']):
        raise ValueError('Audit website identity assessment differs from the re-derived one')
    canonical = json.dumps([subject, 'verified_website', SCOPE, None, None], ensure_ascii=False, sort_keys=True,
                           separators=(',', ':')).encode()
    claim_id = hashlib.sha256(canonical).hexdigest()
    if (item.get('extraction_method') != METHOD or item.get('source_origin') != receipt.get('source_origin')
            or item.get('id') != item['snapshot_id'] + ':' + claim_id or claim.get('evidence_ids') != [item['id']]
            or claim.get('field') != 'verified_website' or claim.get('scope') != SCOPE
            or claim.get('family') != 'website_owned_profiles' or claim.get('item_key') is not None
            or claim.get('period') is not None or claim.get('availability') != 'available'
            or claim.get('freshness') != 'live_source' or claim.get('claim_id') != claim_id
            or claim.get('value') != 'https://' + host + '/'):
        raise ValueError('Audit website value or canonical identity mismatch')
