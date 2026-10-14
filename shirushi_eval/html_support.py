"""Independent HTML interpretation; never imports application extraction."""
import hashlib
import json
import re
import unicodedata
from functools import lru_cache
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urlsplit

from .public_suffix_data import PUBLIC_SECTOR_SUFFIXES, PUBLIC_SUFFIXES


class Document(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.source = raw.decode('utf-8')
        self.lines = self.source.split('\n')
        self.offsets = [0]
        for line in self.lines[:-1]:
            self.offsets.append(self.offsets[-1] + len(line) + 1)
        self.parents, self.nodes = [], []
        self.feed(self.source)

    def source_position(self):
        line, col = self.getpos()
        return self.offsets[line - 1] + col

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'q' or tag == 'blockquote':
            for parent in self.parents:
                parent['quoted'] = True
        hidden = any(node['hidden'] for node in self.parents)
        hidden = hidden or tag in ('style', 'script', 'template', 'noscript') or 'hidden' in attrs
        hidden = hidden or attrs.get('aria-hidden') == 'true' or bool(re.search(
            r'(?:display\s*:\s*none|visibility\s*:\s*hidden)', attrs.get('style') or '', re.I))
        if tag in ('br', 'hr', 'img', 'input', 'meta', 'link', 'source', 'wbr', 'area', 'base', 'embed', 'param', 'track', 'col'):
            self.handle_data(' ')
            return
        quoted = tag in ('q', 'blockquote') or any(n['tag'] in ('q', 'blockquote') for n in self.parents)
        self.parents.append({'tag': tag, 'start': self.source_position(), 'text': '',
                             'hidden': hidden, 'quoted': quoted, 'attrs': attrs})

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, value):
        if self.parents and not self.parents[-1]['hidden']:
            for node in self.parents:
                node['text'] += value

    def handle_endtag(self, tag):
        if not self.parents or self.parents[-1]['tag'] != tag:
            return
        node = self.parents.pop()
        end = self.source.find('>', self.source_position())
        if end >= 0 and not node['hidden'] and not node['quoted']:
            node['end'] = end + 1
            node['text'] = ' '.join(node['text'].split())
            node['ancestors'] = tuple(parent['tag'] for parent in self.parents)
            self.nodes.append(node)


@lru_cache(maxsize=4)
def document(raw):
    return Document(raw)


def legal_operator(raw, subject, name, registry_url='', page_url=''):
    for node in document(raw).nodes:
        if node['tag'] not in ('footer', 'address', 'p') or len(node['text']) > 1500 or not name:
            continue
        value = node['text']
        if not re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', value, re.I):
            continue
        numbers = re.findall(r'(?:org(?:anisasjons)?\.?\s*(?:nr|nummer)\.?|organi[sz]ation\s+(?:number|no\.?))\s*:?\s*(?:NO\s*)?([0-9]{3}[ .]?[0-9]{3}[ .]?[0-9]{3})(?![0-9])', value, re.I)
        numbers = {re.sub(r'\D', '', number) for number in numbers}
        operator = re.search(r'(?:copyright|\u00a9)\s*(?:[0-9]{4}[\s.,-]*)?(?:by\s+)?' + re.escape(name) + r'(?!\w)|'
            r'(?:website|site|nettsted).{0,40}(?:operated|owned|drives|eies).{0,30}' + re.escape(name) + r'(?!\w)|'
            r'\butgiver\s*:?\s*' + re.escape(name) + r'(?!\w)', value, re.I)
        shop = (re.search(r'(?:^|[.!?]\s+)' + re.escape(name) + r'\s+(?:som\s+)?driver\s+denne\s+nettbutikken\b', value, re.I)
            and re.search(r'\b(?:selger\w*|kj\u00f8psvilk\u00e5r)\b', value, re.I)
            and '?' not in value
            and not re.search(r'\b(?:ikke|not|nei|hvis|dersom|if|unless|would|could|p\u00e5\s+vegne|on\s+behalf|databehandler|processor|hosting|teknisk)\b', value, re.I))
        if numbers == {subject} and (operator or shop):
            return node
        if numbers == {subject} and seller_contract(value, name):
            return node
        if registry_url and page_url and node['tag'] == 'p':
            from urllib.parse import urlsplit
            registered = urlsplit(registry_url if '://' in registry_url else 'https://' + registry_url).hostname
            actual = urlsplit(page_url).hostname
            if not registered or not actual or registered.removeprefix('www.') != actual.removeprefix('www.'):
                continue
            # Independently reconstruct the narrow named operator statement.
            prefix = re.escape(name) + r'(?:\s*\([^)]{1,160}\))?(?:\s*,?\s+ved\s+[^,.]{1,80},?)?\s+er\s+'
            controller = re.search(r'(?<!\w)' + prefix + r'behandlingsansvarlig\s+for\s+[^.]{1,400}'
                r'\bdrift\s+og\s+vedlikehold\s+av\s+(?:www\.)?' + re.escape(actual.removeprefix('www.')) +
                r'(?![\w-]|\.[\w-])', value, re.I)
            operation = re.search(r'(?:^|[.!?]\s+)(?:dette\s+)?nettstedet\s+drives\s+av\s+'
                + re.escape(name) + r'(?=\s*[,.;!]|$)', value, re.I)
            other_operator = any(re.search(r'\bnettstedet\s+drives\s+av\s+(?!'
                + re.escape(name) + r'(?=\s*[,.;!]|$))', n['text'], re.I) for n in document(raw).nodes)
            if ((controller or (operation and not other_operator))
                    and '?' not in value
                    and not re.search(r'\b(?:ikke|not|nei|hvis|dersom|if|unless|would|could|vegne|databehandler|processor|kunde\w*)\b', value, re.I)):
                all_numbers = re.findall(r'(?:org(?:anisasjons)?\.?\s*(?:nr|nummer)\.?|organi[sz]ation\s+(?:number|no\.?))\s*:?\s*(?:NO\s*)?([0-9]{3}[ .]?[0-9]{3}[ .]?[0-9]{3})(?![0-9])',
                    ' '.join(n['text'] for n in document(raw).nodes), re.I)
                if not {re.sub(r'\D', '', number) for number in all_numbers} - {subject}:
                    return node
    return None


def seller_contract(value, name):
    return bool(re.search(r'\b(?:terms|conditions|vilk\u00e5r|avtale)\b', value, re.I)
        and re.search(r'\b(?:customers?|purchase|orders?|seller|kund|kj\u00f8p|selger)\w*\b', value, re.I)
        and re.search(r'\b(?:between|mellom)\s+' + re.escape(name) + r'(?!\w).{0,300}\b'
            r'(?:and\s+(?:(?:their|its|our|the)\s+)?customers?|og\s+(?:(?:deres|v\u00e5re|sine)\s+)?kund\w*)\b', value, re.I))


# Ownership proved by one visible block that names the registry entity, carries its labelled
# organisation number and ties to the page's own site (a mailbox at the site or a domain equal to
# the name). Re-derived here from source bytes; the data lists below are the published contract.
BLOCK_TAGS = {'footer': 1500, 'address': 1500, 'p': 600, 'li': 600, 'div': 600, 'td': 600, 'span': 600}
BLOCK_DIRECTORIES = (
    'proff.no gulesider.no 1881.no brreg.no purehelp.no bisnode.no bisnode.com creditsafe.com creditsafe.no dnb.com '
    'dnb.no linkedin.com facebook.com instagram.com twitter.com x.com youtube.com google.com mittanbud.no '
    'regnskapstall.no forretning.no ratsit.se allabolag.se opencorporates.com crunchbase.com finn.no nav.no '
    'wikipedia.org wikidata.org mynewsdesk.com tripadvisor.com yelp.com trustpilot.com').split()
BLOCK_SHARED = frozenset((
    'medium.com substack.com notion.site notion.so linktr.ee google.com mystrikingly.com strikingly.com weebly.com '
    'jimdosite.com jimdofree.com carrd.co squarespace.com wixsite.com wix.com webflow.io godaddysites.com business.site '
    'github.io gitlab.io netlify.app vercel.app pages.dev herokuapp.com blogspot.com wordpress.com tumblr.com ucoz.com '
    '000webhostapp.com myshopify.com azurewebsites.net web.app framer.app wixstudio.io gmail.com hotmail.com hotmail.no '
    'outlook.com outlook.no yahoo.com yahoo.no online.no live.com live.no icloud.com proton.me protonmail.com').split())
BLOCK_PATH_TENANTS = ('medium.com linktr.ee sites.google.com notion.so notion.site github.com gitlab.com linkedin.com '
                      'facebook.com instagram.com youtube.com x.com twitter.com').split()
BLOCK_NAME_TLDS = frozenset('no com org net eu'.split())
BLOCK_FORMS = 'as asa ans da nuf sa se ab a/s oy ltd inc llc gmbh bv plc'.split()
BLOCK_NUMBER = (r'(?:org(?:anisasjons)?\.?\s*(?:nr|nummer)\.?|organi[sz]ation\s+(?:number|no\.?))'
                r'\s*:?\s*(?:NO\s*)?([0-9]{3}[ .]?[0-9]{3}[ .]?[0-9]{3})(?![0-9])')
BLOCK_CONTEXT = re.compile(
    r'(?<!\w)(?:customers?|clients?|kunde\w*|suppliers?|leverand\w*|partners?|samarbeid\w*|referanse\w*|references?|'
    r'testimonials?|sponsor\w*|members?|medlem\w*|parent|subsidiar\w*|morselskap|datterselskap|konsern\w*|ikke|not|'
    r'hvis|dersom|if|behalf|vegne|formerly|tidligere|fka|c/o|webdesign\w*|design\w*|utviklet|laget|levert|powered|'
    r'developed|built|created|hosted|hosting|videreutvikling|regnskapsf(?:\u00f8|o|oe)rer\w*|revisor|accountant|'
    r'agency|byr(?:\u00e5|aa)|eier|eies|eid|kj.pt\w*|oppkj.\w*|acquired|faktura\w*|fakturer\w*|invoice\w*|'
    r'arbeidsgiver|employer|forhandler|dealer|reseller|leietaker|tenant|pressekontakt|konkurs\w*|bankrupt\w*|'
    r'regnskapskontor|prosjekt\w*|project|oppdrag\w*)(?!\w)', re.I)
BLOCK_ENTITY = re.compile(
    r"(?<![\w&])(?:[\w&.'-]+\s+){1,5}(ASA|ANS|NUF|ApS|GmbH|SARL|SAS|PLC|Ltd|Inc|LLC|IKS|AS|DA|SA|SE|AB|A/S|Oy|BV|AG|ENK|KS|BA|NV)"
    r"(?![\w/])")
BLOCK_MARKER = '\u2022'


def ascii_fold(text):
    text = text.lower().replace('\u00e6', 'ae').replace('\u00f8', 'o').replace('\u00e5', 'a')
    return ''.join(c for c in unicodedata.normalize('NFD', text) if not unicodedata.combining(c))


def name_stem(text):
    text = re.sub(r'(?<!\w)(?:' + '|'.join(re.escape(f) for f in BLOCK_FORMS) + r')(?!\w)', ' ', ascii_fold(text))
    return re.sub(r'[^a-z0-9]', '', text)


def registrable(domain):
    """The registrable domain, or None for a public suffix or a bare label (suffix check before any equality)."""
    name = re.sub(r'^www\.', '', domain.lower())
    labels = name.split('.')
    if len(labels) < 2 or name in PUBLIC_SUFFIXES:
        return None
    if '.'.join(labels[-2:]) in PUBLIC_SUFFIXES:
        return '.'.join(labels[-3:]) if len(labels) > 2 else None
    return '.'.join(labels[-2:])


def tied_domain(domain, site):
    own, theirs = registrable(domain), registrable(site)
    return own is not None and own == theirs and own not in BLOCK_SHARED


def denied_host(host):
    own = registrable(host)
    return (any(host == d or host.endswith('.' + d) for d in BLOCK_DIRECTORIES + BLOCK_PATH_TENANTS)
            or own is None or own in BLOCK_SHARED
            or any(host.endswith('.' + suffix) for suffix in PUBLIC_SECTOR_SUFFIXES))


def mail_domain(address):
    address = address.strip().lower().rstrip('.-')
    found = re.fullmatch(r'[a-z0-9._%+-]+@([a-z0-9-]+(?:\.[a-z0-9-]+)+)', address)
    return found[1] if found else None


def block_domains(node, page):
    domains = set()
    for token in re.findall(r'[A-Za-z0-9._%+@-]+', node['text']):
        if token.count('@') == 1:
            domains.add(mail_domain(token))
    for link in page.nodes:
        href = (link['attrs'].get('href') or '').strip()
        if (link['tag'] == 'a' and node['start'] <= link['start'] and link['end'] <= node['end']
                and href[:7].lower() == 'mailto:'):
            for address in href[7:].split('?', 1)[0].split(','):
                domains.add(mail_domain(address))
    domains.discard(None)
    return domains


def name_domain_tie(site, name):
    if registrable(site) != site or site in BLOCK_SHARED or site.rsplit('.', 1)[-1] not in BLOCK_NAME_TLDS:
        return False
    label = ascii_fold(site.split('.')[0])
    return (re.fullmatch(r'[a-z0-9-]+', label) is not None and len(name_stem(name)) >= 4
            and name_stem(label) == name_stem(name))


def legal_contact_block(raw, subject, name, page_url=''):
    """The first visible block (end-tag order) proving that this site's operator is the registry entity."""
    host = urlsplit(page_url).hostname if page_url else None
    if not name or not host or denied_host(host):
        return None
    site = re.sub(r'^www\.', '', host)
    page = document(raw)
    named = re.compile(r'(?<!\w)' + re.escape(name) + r'(?!\w)', re.I)
    number = '[ .]?'.join(re.escape(subject[i:i + 3]) for i in (0, 3, 6))
    digits = re.compile(r'(?<![0-9])' + number + r'(?![0-9])')
    for node in page.nodes:
        text = node['text']
        if node['tag'] not in BLOCK_TAGS or len(text) > BLOCK_TAGS[node['tag']] or not named.search(text):
            continue
        labelled = {re.sub(r'\D', '', n) for n in re.findall(BLOCK_NUMBER, text, re.I)}
        if labelled != {subject}:
            continue
        marked = named.sub(BLOCK_MARKER, text)
        if re.search('["\u201c\u201d\u00ab\u00bb?]', marked):
            continue
        anchors = [m.span() for m in re.finditer(BLOCK_MARKER, marked)] + [m.span() for m in digits.finditer(marked)]
        if any(BLOCK_CONTEXT.search(marked[max(0, a - 80):a] + ' ' + marked[b:b + 80]) for a, b in anchors):
            continue
        if BLOCK_ENTITY.search(marked.replace(BLOCK_MARKER, ' ')):
            continue
        if (any(tied_domain(domain, site) for domain in block_domains(node, page))
                or name_domain_tie(site, name)):
            return dict(node, kind='legal_contact_block')
    return None


def ownership_proof(raw, subject, name, registry_url='', page_url=''):
    """The earlier proof kinds decide first and are unchanged; the contact block is the fallback."""
    return legal_operator(raw, subject, name, registry_url, page_url) or legal_contact_block(raw, subject, name, page_url)


def audit_html(subject, claim, item, receipt, raw, legal_name, ownership_raw, registry_url='', ownership_url=''):
    proof = ownership_proof(ownership_raw, subject, legal_name, registry_url, ownership_url)
    linked = item['extraction_method'] == 'registry_linked_subject_html_v1'
    scope = 'registry_linked_html' if linked else 'company_owned_html'
    if linked:
        from urllib.parse import urlsplit
        host = urlsplit(registry_url if '://' in registry_url else 'https://' + registry_url).hostname
        actual = urlsplit(receipt['effective_url']).hostname
        if not host or not actual or host.removeprefix('www.') != actual.removeprefix('www.'):
            raise ValueError('Audit named content lacks registry host linkage')
    elif proof is None:
        raise ValueError('Audit HTML lacks legal operator evidence')
    location = item['locator']
    if (type(location.get('html_start')) is not int or type(location.get('html_end')) is not int
            or location.get('legal_name') != legal_name):
        raise ValueError('Audit HTML locator mismatch')
    page = document(raw)
    node = next((node for node in page.nodes if node['start'] == location['html_start']
                 and node['end'] == location['html_end']), None)
    if node is None or page.source[node['start']:node['end']] != item['claim_span']:
        raise ValueError('Audit HTML span is hidden, malformed or misplaced')
    text = node['text']
    field = claim['field']
    if field == 'verified_website':
        if linked:
            raise ValueError('Registry linkage cannot establish website ownership')
        owner = ownership_proof(raw, subject, legal_name, registry_url, receipt['effective_url'])
        if (owner is None or (owner['start'], owner['end']) != (node['start'], node['end'])
                or location.get('operator') is not True):
            raise ValueError('Audit website span lacks operator evidence')
        block = owner.get('kind') == 'legal_contact_block'
        if block and (ownership_raw != raw or ownership_url != receipt['effective_url']):
            raise ValueError('Audit contact block is not on the ownership page')
        path = '/'
        if not block and seller_contract(text, legal_name):
            from urllib.parse import urlsplit
            path = urlsplit(receipt['effective_url']).path.rsplit('/', 1)[0] + '/'
        expected = 'https://' + receipt['declared_host'] + path
        family, key = 'website_owned_profiles', None
    else:
        dated = field == 'public_activity' and location.get('dated_article') is True
        if not dated and (not 10 <= len(text) <= 2000 or not re.search(r'(?<!\w)' + re.escape(legal_name) + r'(?!\w)', text, re.I)):
            raise ValueError('Audit HTML fact does not identify its subject')
        numbers = re.findall(r'(?:org(?:anisasjons)?\.?\s*(?:nr|nummer)\.?|organi[sz]ation\s+(?:number|no\.?))\s*:?\s*(?:NO\s*)?([0-9]{3}[ .]?[0-9]{3}[ .]?[0-9]{3})(?![0-9])', text, re.I)
        if {re.sub(r'\D', '', number) for number in numbers} - {subject}:
            raise ValueError('Audit HTML contains conflicting legal identifiers')
        if field == 'business_description':
            if node['tag'] != 'p' or not re.search(r'(?<!\w)' + re.escape(legal_name) +
                    r'\s+er\s+(?:en|et)\s+(?:(?:moderne|norsk|norske|ledende|lokal|lokalt|internasjonalt)\s+){0,3}'
                    r'(?:konsulentselskap|konsulentfirma|produksjonsbedrift|produsent|leverand\u00f8r|industribedrift)\b', text, re.I):
                raise ValueError('Audit unsupported company definition')
            expected, family, key = text, 'business_products', None
        elif field == 'product_service':
            offers = re.search(r'(?<!\w)' + re.escape(legal_name) + r'\s+(?:offers|provides|supplies|manufactures|produces|tilbyr|leverer|produserer)\b', text, re.I)
            publisher = (re.search(r'(?:^|[.!?]\s+)(?:nettstedet\s+drives\s+av\s+|'
                r'bak\s+nettavisen(?:\s+[a-z0-9.-]+)?\s+st\u00e5r\s+)?' + re.escape(legal_name) + r'\s*,?\s+(?:som(?:\s+ogs\u00e5)?\s+)?'
                r'(?:utgir\s+fagblad(?:et)?|er\s+utgiverselskapet\s+for)\b', text, re.I)
                and '?' not in text
                and not re.search(r'\b(?:ikke|not|nei|aldri|never|hvis|dersom|if|unless|would|could|vegne|behalf)\b', text, re.I))
            heading = (node['tag'] in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6') and offers
                and offers.start() == 0 and '?' not in text
                and not re.search(r'\b(?:ikke|not|no|none|ingen|intet|nei|never|aldri|hvis|dersom|if|unless|would|could|vegne|behalf|agent)\b', text, re.I))
            first_person = (node['tag'] == 'p'
                and re.match(re.escape(legal_name) + r'\s+(?:er\s+(?:[\w\u00e5\u00e6\u00f8-]+\s+){0,4}'
                    r'(?:selskap|mobilitetsselskap|konsulentselskap|produsent|leverand\u00f8r|representant)|'
                    r'is\s+(?:a|an)\s+(?:company|consultancy|manufacturer|supplier))\b[^.!?]{0,400}[.]\s+'
                    r'(?:(?:v\u00e5r\s+oppgave|our\s+task)\s+(?:er|is)\s+[^.!?]{1,400}[.]\s+)?'
                    r'(?:vi|we)\s+(?:tilbyr|leverer|produserer|offers?|provides?|supplies|manufactures?|produces?|gir\s+r\u00e5d)\b', text, re.I)
                and not re.search(r'\b(?:AS|ASA|Ltd|Inc|LLC|PLC)\b', text[len(legal_name):], re.I)
                and not re.search(r"[?'\"\u2018\u2019\u201c\u201d\u00ab\u00bb:]", text)
                and not re.search(r'\b(?:mentioned|discussed|statement|said|says|omtalt|uttalelse|sier)\b', text, re.I)
                and not re.search(r'\b(?:ikke|not|no|none|ingen|intet|nei|never|aldri|hvis|dersom|if|unless|would|could|vegne|behalf|agent|kunde|customer|konsern\w*|group|gruppen)\b', text, re.I))
            if not ((node['tag'] in ('p', 'li') and (offers or publisher)) or heading or first_person):
                raise ValueError('Audit unsupported product/service attribution')
            expected, family, key = text, 'business_products', hashlib.sha256(text.encode()).hexdigest()
        elif field == 'public_activity':
            if location.get('dated_article') is True:
                from .article_support import audit_article
                expected, family, key = audit_article(raw, subject, legal_name, node, location,
                    receipt, registry_url)
            else:
                dates = re.findall(r'(?<![0-9])[0-9]{4}-[0-9]{2}-[0-9]{2}(?![0-9])', text)
                if (node['tag'] not in ('p', 'article') or len(dates) != 1 or not re.search(
                        r'(?<!\w)' + re.escape(legal_name) + r'\s+(?:launched|opened|announced|signed|lanserte|\u00e5pnet|kunngjorde|signerte)\b', text, re.I)
                        or date.fromisoformat(dates[0]) > date.fromisoformat(receipt.get('evaluation_cutoff', receipt['retrieved_at'])[:10])):
                    raise ValueError('Audit unsupported dated activity')
                expected = {'statement': text, 'activity_date': dates[0], 'source_url': receipt['effective_url']}
                family = 'jobs_dated_activity'
                key = hashlib.sha256((receipt['effective_url'] + '\n' + text).encode()).hexdigest()
        else:
            raise ValueError('Audit unsupported HTML claim')
    encoded = json.dumps([subject, field, scope, key, None], ensure_ascii=False,
                         sort_keys=True, separators=(',', ':')).encode()
    if (claim['value'] != expected or claim.get('family') != family or claim.get('item_key') != key
            or claim.get('period') is not None or claim.get('scope') != scope
            or claim.get('claim_id') != hashlib.sha256(encoded).hexdigest()):
        raise ValueError('Audit HTML value or canonical identity mismatch')


def audit_catalogue(subject, claim, item, receipt, raw, legal_name, ownership_raw, ownership_receipt):
    from urllib.parse import urljoin, urlsplit
    owner = legal_operator(ownership_raw, subject, legal_name)
    if owner is None or not seller_contract(owner['text'], legal_name):
        raise ValueError('Catalogue lacks verified seller contract')
    prefix = urlsplit(ownership_receipt['effective_url']).path.rsplit('/', 1)[0] + '/'
    loc = item['locator']
    page = document(raw)
    node = next((n for n in page.nodes if n['start'] == loc.get('html_start') and n['end'] == loc.get('html_end')), None)
    if node is None or node['tag'] != 'a' or loc.get('catalogue') is not True or page.source[node['start']:node['end']] != item['claim_span']:
        raise ValueError('Catalogue source locator mismatch')
    link = urljoin(receipt['effective_url'], node['attrs'].get('href', ''))
    parts = urlsplit(link)
    page = urlsplit(receipt['effective_url'])
    if (parts.scheme != 'https' or parts.hostname != page.hostname or parts.username or parts.password
            or parts.port not in (None, 443) or not page.path.startswith(prefix) or not parts.path.startswith(prefix)
            or not re.search(r'/(?:products?|produkter)/[^/]+/?$', parts.path, re.I)
            or not 4 <= len(node['text']) <= 200
            or node['text'].lower() in {'products', 'produkter', 'les mer', 'read more', 'shop now'}):
        raise ValueError('Catalogue link escapes seller scope')
    link = parts._replace(fragment='').geturl()
    value = {'name': node['text'], 'source_url': link}
    encoded = json.dumps([subject, 'product_service', 'company_owned_catalogue', link, None], ensure_ascii=False,
                         sort_keys=True, separators=(',', ':')).encode()
    if (claim['field'] != 'product_service' or claim['value'] != value or claim.get('family') != 'business_products'
            or claim.get('scope') != 'company_owned_catalogue' or claim.get('item_key') != link
            or claim.get('period') is not None or claim['claim_id'] != hashlib.sha256(encoded).hexdigest()):
        raise ValueError('Catalogue value or canonical identity mismatch')
