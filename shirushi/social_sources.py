"""Company-owned social profile links read from pages already anchored to the company."""
import html
import json
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from .contracts import loads
from .content_sources import trade_name
from .html_sources import OTHER_ENTITY, VOID, ascii_fold, name_stem, org_numbers

FIELD = 'social_profile'  # Public alias hook: the organiser's own field name is unconfirmed.
METHOD = 'social_profile_link_v1'
GATE_METHOD = 'deterministic_social_handle_identity_v1'

PLATFORMS = {'facebook.com': 'facebook', 'fb.com': 'facebook', 'linkedin.com': 'linkedin', 'instagram.com': 'instagram',
             'x.com': 'x', 'twitter.com': 'x', 'youtube.com': 'youtube', 'tiktok.com': 'tiktok'}
CANONICAL_HOST = {'facebook': 'facebook.com', 'linkedin': 'linkedin.com', 'instagram': 'instagram.com', 'x': 'x.com',
                  'youtube': 'youtube.com', 'tiktok': 'tiktok.com'}
COMMON_SUBDOMAINS = {'', 'www', 'm', 'mobile', 'web', 'touch', 'mbasic'}
FACEBOOK_REJECT = frozenset('''sharer sharer.php share share.php dialog policy.php privacy events groups plugins login login.php
    recover help profile.php hashtag tr watch marketplace gaming stories story.php permalink.php photo photo.php video.php videos
    reel reels l.php ads business about legal terms terms.php settings public directory search home.php notes connect r.php
    messages bookmarks friends places pg pages_manager'''.split())
FACEBOOK_TABS = frozenset('about info community reviews services home reels mentions menu offers photos videos'.split())
INSTAGRAM_REJECT = frozenset('''p reel reels stories explore accounts tv direct about legal developer web directory tags locations
    share oauth challenge privacy press api'''.split())
INSTAGRAM_TABS = frozenset('reels tagged channel guides'.split())
X_REJECT = frozenset('''intent share home search i hashtag explore settings login signup tos privacy messages compose notifications
    widgets.js about download'''.split())

# Words that make a handle a trade-description rather than evidence of the name.
GENERIC = frozenset('bygg service norge norway group gruppen eiendom holding invest norske norsk'.split())
LEGAL_WORDS = frozenset('as asa ans da enk iks sa sam sti stiftelsen nuf ab b v limited ltd inc plc the og and'.split())
# A national subsidiary (Falck Norge) must not take the group's global handle for its own.
COUNTRY = frozenset('norge norway norsk norske'.split())
# A handle carrying one of these when the legal name does not names a parent or sister entity.
GROUP_WORDS = ('group', 'gruppen', 'konsern', 'holding', 'invest', 'eiendom')

HIDDEN_TAGS = {'template', 'noscript', 'style', 'script'}
HIDDEN_CLASSES = {'d-none', 'hidden', 'hide', 'sr-only', 'visually-hidden', 'screen-reader-text', 'is-hidden'}
QUOTED_TAGS = {'blockquote', 'q', 'pre', 'code', 'textarea', 'xmp'}
# JSON-LD sameAs counts when its node is the page's own organisation: top level, @graph, or one of these properties.
SAME_AS_OWNERS = {'publisher', 'mainEntity', 'provider', 'copyrightHolder'}
SAME_AS_DENIED_TYPES = {'Person', 'Review', 'Comment', 'Rating', 'Question', 'Answer'}

RELATION = re.compile(r'(?<!\w)(?:customers?|clients?|kunde\w*|partner\w*|samarbeids\w*|leverand\w*|suppliers?|sponsor\w*|'
    r'referanse\w*|references?|testimonial\w*|medlem\w*|members?|konsern\w*|group|gruppen|parent|morselskap|datterselskap|'
    r'subsidiar\w*|søster\w*|sister|affiliate\w*|tilknyttet|laget\s+av|utviklet|developed|design\w*|webdesign\w*|'
    r'nettside\w*\s+(?:av|by)|powered|built|created|made\s+by|produced|hosted|hosting|levert\s+av|drevet\s+av|foto\w*|'
    r'photo\w*|del\s+av|part\s+of|byrå|agency|forhandler|dealer|reseller)(?!\w)', re.I)


def canonical_profile(link):
    """Canonical company profile of an absolute social URL, or None for shares, logins, posts, people and other hosts."""
    if not isinstance(link, str):
        return None
    link = link.strip()
    if link.startswith('//'):
        link = 'https:' + link
    try:
        parts = urlsplit(link)
        host, port = (parts.hostname or ''), parts.port
    except ValueError:
        return None
    if parts.scheme not in ('http', 'https') or port not in (None, 80, 443) or len(link) > 2000:
        return None
    domain = next((d for d in PLATFORMS if host == d or host.endswith('.' + d)), None)
    if domain is None:
        return None
    platform, sub = PLATFORMS[domain], host[:-len(domain)].rstrip('.')
    if not (sub in COMMON_SUBDOMAINS or (platform == 'facebook' and re.fullmatch(r'[a-z]{2}-[a-z]{2}', sub))
            or (platform == 'linkedin' and re.fullmatch(r'[a-z]{2}', sub))):
        return None
    segments = [unquote(s) for s in parts.path.split('/') if s]
    if (not segments or len(segments) > 8 or any(len(s) > 150 or re.search(r'[\s/?#\x00-\x1f]', s) for s in segments)):
        return None
    first, rest = segments[0].lower(), segments[1:]
    path = None
    if platform == 'facebook':
        if first in FACEBOOK_REJECT or first.endswith('.php') or re.fullmatch(r'v\d+\.\d+', first):
            return None
        if first in ('people', 'pages'):
            if len(segments) >= 3 and segments[2].isdigit() and segments[1].lower() != 'category':
                path = [first, segments[1], segments[2]]
        elif not rest or (len(rest) == 1 and rest[0].lower() in FACEBOOK_TABS):
            path = [segments[0]]
    elif platform == 'linkedin':
        if first == 'company' and rest:
            path = [first, rest[0]]
    elif platform == 'instagram':
        if first not in INSTAGRAM_REJECT and re.fullmatch(r'[A-Za-z0-9._]{1,30}', segments[0]) \
                and (not rest or (len(rest) == 1 and rest[0].lower() in INSTAGRAM_TABS)):
            path = [segments[0]]
    elif platform == 'x':
        if first not in X_REJECT and not rest and re.fullmatch(r'[A-Za-z0-9_]{1,15}', segments[0]):
            path = [segments[0]]
    elif platform == 'youtube':
        if first in ('channel', 'user', 'c') and rest:
            path = [first, rest[0]]
        elif segments[0].startswith('@') and len(segments[0]) > 1:
            path = [segments[0]]
    elif platform == 'tiktok':
        if segments[0].startswith('@') and len(segments[0]) > 1 and not rest:
            path = [segments[0]]
    if not path:
        return None
    tail = '/'.join(path)
    return {'platform': platform, 'url': 'https://' + CANONICAL_HOST[platform] + '/' + tail,
            'handle_key': (CANONICAL_HOST[platform] + '/' + tail).lower()}


def tokens(name):
    if not isinstance(name, str):
        return []
    return [t for t in re.split(r'[^a-z0-9]+', ascii_fold(name)) if len(t) > 1 and t not in LEGAL_WORDS]


def handle_text(profile):
    """Lower-case ASCII letters and digits of the name part of a canonical profile URL."""
    segments = profile['url'].split('/')[3:]
    if profile['platform'] == 'facebook' and segments[0] in ('people', 'pages'):
        part = segments[1]
    elif profile['platform'] in ('linkedin', 'youtube') and len(segments) > 1:
        part = segments[1]
    else:
        part = segments[0]
    return re.sub(r'[^a-z0-9]', '', ascii_fold(part))


def handle_gate(legal_name, profile, names=()):
    """The handle must contain the legal-name or a trade-name's tokens; generic trade words alone are no evidence."""
    text, best = handle_text(profile), None
    for form in (legal_name, *names):
        text = handle_text(profile)
        core = tokens(form)
        concat = ''.join(core)
        if len(concat) < 3 or not isinstance(form, str):
            continue
        distinct = [t for t in core if t not in GENERIC]
        folded = ascii_fold(form)
        if 'aa' in text and 'aa' not in folded:
            text = text.replace('aa', 'a')  # Narvikgaarden for Narvikgården
        country = [t for t in core if t in COUNTRY and t not in text]
        if any(word in text and word not in folded for word in GROUP_WORDS):
            result = (0.0, [], 'handle names a group or sister entity the form does not')
        elif distinct and concat in text:
            result = (0.98, core, 'name tokens appear in sequence in the handle')
        elif len(distinct) == 1 and len(distinct[0]) >= 3 and distinct[0] in text and not country:
            result = (0.95, distinct, 'the single distinctive name token appears in the handle')
        elif distinct and len(core) >= 2:
            matched = [t for t in core if t in text]
            ok = len(matched) / len(core) >= 0.75 and any(t in matched for t in distinct)
            result = (0.90, matched, 'at least 75 percent of the name tokens appear in the handle') if ok else (0.0, [], 'name tokens absent from the handle')
        elif not distinct and text == concat:
            result = (0.98, core, 'the handle equals the generic name')
        else:
            result = (0.0, [], 'name tokens absent from the handle')
        if best is None or result[0] > best[0]:
            best = result
    best = best or (0.0, [], 'no usable name tokens')
    return {'score': best[0], 'publishable': best[0] >= 0.90, 'matched': best[1], 'reason': best[2], 'method': GATE_METHOD}


class Scan(HTMLParser):
    """Element tree with offsets; unmatched end tags close back to the nearest open element of that name."""

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.source, self.elements, self.stack, self.offsets = source, [], [], [0]
        for line in source.split('\n')[:-1]:
            self.offsets.append(self.offsets[-1] + len(line) + 1)
        self.feed(source)
        self.close()
        for index in self.stack:
            self.elements[index]['end'] = len(source)

    def position(self):
        line, column = self.getpos()
        return self.offsets[line - 1] + column

    def handle_starttag(self, tag, attrs):
        attrs = {k: (v or '') for k, v in attrs}
        parent = self.elements[self.stack[-1]] if self.stack else None
        classes = set((attrs.get('class') or '').lower().split())
        style = re.sub(r'\s+', '', attrs.get('style', '').lower())
        inherited = bool(parent and parent['hidden'])
        hidden = (inherited or tag in HIDDEN_TAGS or 'hidden' in attrs or attrs.get('aria-hidden') == 'true'
                  or 'display:none' in style or 'visibility:hidden' in style or bool(classes & HIDDEN_CLASSES))
        start = self.position()
        element = {'tag': tag, 'attrs': attrs, 'start': start, 'tag_end': start + len(self.get_starttag_text()),
                   'end': None, 'parent': self.stack[-1] if self.stack else -1, 'inherited_hidden': inherited,
                   'hidden': hidden, 'quoted': tag in QUOTED_TAGS or bool(parent and parent['quoted'])}
        self.elements.append(element)
        if tag not in VOID:
            self.stack.append(len(self.elements) - 1)
        else:
            element['end'] = element['tag_end']

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            index = self.stack.pop()
            self.elements[index]['end'] = self.elements[index]['tag_end']

    def handle_endtag(self, tag):
        names = [self.elements[i]['tag'] for i in self.stack]
        if tag not in names:
            return
        close = self.position()
        end = self.source.find('>', close)
        end = len(self.source) if end < 0 else end + 1
        while True:
            element = self.elements[self.stack.pop()]
            element['end'] = end
            element['close_start'] = close
            if element['tag'] == tag:
                return


def plain(markup):
    markup = re.sub(r'<(script|style|template|noscript|svg)\b.*?</\1\s*>|<!--.*?-->', ' ', markup, flags=re.S | re.I)

    def short_anchor(match):
        return ' ' if len(re.sub(r'<[^>]*>', ' ', match.group(0)).strip()) <= 30 else match.group(0)
    markup = re.sub(r'<a\b[^>]*>.{0,200}?</a\s*>', short_anchor, markup, flags=re.S | re.I)
    return ' '.join(html.unescape(re.sub(r'<[^>]*>', ' ', markup)).split())


def context_exclusion(scan, element, subject, forms):
    """Reason the link sits in another entity's block (credit, partner, parent group, other organisation), else None."""
    index = scan.elements.index(element)
    parent = element['parent']
    for _ in range(6):
        if parent < 0:
            return None
        container = scan.elements[parent]
        before = plain(scan.source[container['tag_end']:element['start']])
        for form in sorted(forms, key=len, reverse=True):
            before = re.sub(re.escape(form), ' ', before, flags=re.I)
        if sum(c.isalpha() for c in before) >= 3 or container['tag'] in ('body', 'html'):
            before = before[-120:]
            if org_numbers(before) - {subject}:
                return 'other organisation number in the block'
            if RELATION.search(before):
                return 'credit, partner, customer or group block'
            if OTHER_ENTITY.search(before):
                return 'another legal entity is named in the block'
            return None
        parent = container['parent']
    return None


def link_candidates(scan, url):
    for element in scan.elements:
        if element['hidden'] or element['quoted']:
            continue
        attrs = element['attrs']
        if element['tag'] == 'a' and attrs.get('href'):
            yield element, 'a_href', attrs['href']
        if attrs.get('data-href'):
            yield element, 'data_href', attrs['data-href']
        if element['tag'] == 'iframe' and attrs.get('src'):
            yield element, 'iframe_src', attrs['src']


def resolve(base, value):
    try:
        full = urljoin(base, value.strip())
        profile = canonical_profile(full)
        if profile is None:
            parts = urlsplit(full)
            if (parts.hostname or '').removeprefix('www.') in ('facebook.com', 'm.facebook.com') and parts.path.startswith('/plugins/'):
                inner = (parse_qs(parts.query).get('href') or [''])[0]
                profile = canonical_profile(urljoin(full, inner))
        return profile
    except ValueError:
        return None


def same_as_nodes(value, subject, path=()):
    """Same-as owning nodes: top level, @graph and the page's publisher/provider properties; never people or other entities."""
    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from same_as_nodes(item, subject, path + (index,))
    elif isinstance(value, dict):
        kinds = value.get('@type')
        kinds = kinds if isinstance(kinds, list) else [kinds]
        if SAME_AS_DENIED_TYPES & set(k for k in kinds if isinstance(k, str)):
            return
        for key in ('identifier', 'taxID', 'vatID'):
            number = value.get(key)
            number = number.get('value') if isinstance(number, dict) else number
            digits = re.sub(r'\D', '', number) if isinstance(number, str) else ''
            if len(digits) == 9 and digits != subject:
                return
        yield path, value
        if '@graph' in value:
            yield from same_as_nodes(value['@graph'], subject, path + ('@graph',))
        for key in SAME_AS_OWNERS:
            if isinstance(value.get(key), (dict, list)):
                yield from same_as_nodes(value[key], subject, path + (key,))


def json_candidates(scan, subject, forms=()):
    source, index = scan.source, 0
    for element in scan.elements:
        if element['tag'] != 'script' or 'ld+json' not in element['attrs'].get('type', '').lower():
            continue
        script_index, index = index, index + 1
        if element['inherited_hidden'] or element['quoted'] or 'close_start' not in element:
            continue
        body_start, body_end = element['tag_end'], element['close_start']
        try:
            parsed = loads(source[body_start:body_end])
        except ValueError:
            continue
        literals = [(m.start(), m.group(0)) for m in re.finditer(r'"(?:[^"\\]|\\.)*"', source[body_start:body_end])]
        anchor_at = source[body_start:body_end].find('"sameAs"')
        for path, node in same_as_nodes(parsed, subject):
            title = node.get('name')
            # A location, branch or sibling company node (Solberg Bil Notodden, Arendal Auto AS) is another entity.
            if isinstance(title, str) and title.strip() and name_stem(title) not in {name_stem(f) for f in forms}:
                continue
            declared = node.get('sameAs')
            for position, raw_url in enumerate([declared] if isinstance(declared, str) else declared if isinstance(declared, list) else []):
                if not isinstance(raw_url, str):
                    continue
                hits = [(at, text) for at, text in literals if _decoded(text) == raw_url]
                if not hits:
                    continue
                after = [h for h in hits if h[0] >= anchor_at]
                at, text = (after or hits)[0]
                yield (body_start + at, body_start + at + len(text), text, raw_url,
                       {'script_index': script_index, 'node_path': list(path) + ['sameAs', position]})


def _decoded(literal):
    try:
        return json.loads(literal)
    except ValueError:
        return None


def group_site(url):
    """A non-.no host that serves country locales (/nb-no/, no.example.com) is a group's global site."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    labels = (parts.hostname or '').split('.')
    if not labels or labels[-1] == 'no':
        return False
    segments = [s for s in parts.path.split('/') if s]
    return bool((segments and re.fullmatch(r'[a-z]{2}[-_][a-z]{2}', segments[0].lower()))
                or (len(labels) >= 3 and labels[0] != 'www' and re.fullmatch(r'[a-z]{2}(?:-[a-z]{2})?', labels[0])))


def market_handle(profile):
    """The handle itself says it is the Norwegian channel (name.no, name-norge, name_norway)."""
    return bool(re.search(r'(?:[._-]no$|norge|norway|norsk)', profile['handle_key'].split('/', 1)[1]))


def social_links(raw, legal_name, url, names=(), subject=''):
    """Every distinct canonical profile link on the page with its handle gate and context exclusion, sorted by platform and URL."""
    source = raw.decode('utf-8')
    scan = Scan(source)
    forms = [f for f in (legal_name, trade_name(legal_name) if isinstance(legal_name, str) and legal_name.strip() else None, *names)
             if isinstance(f, str) and f.strip()]
    found = []
    for element, kind, value in link_candidates(scan, url):
        profile = resolve(url, value)
        if profile:
            found.append((element['start'], profile, {'source': kind, 'raw_url': value, 'html_start': element['start'],
                          'html_end': element['tag_end'], 'element_end': element['end']},
                          source[element['start']:element['tag_end']], context_exclusion(scan, element, subject, forms)))
    for start, end, text, raw_url, extra in json_candidates(scan, subject, forms):
        profile = resolve(url, raw_url)
        if profile:
            found.append((start, profile, dict({'source': 'json_ld_same_as', 'raw_url': raw_url, 'html_start': start, 'html_end': end}, **extra),
                          text, None))
    best = {}
    group = group_site(url)
    for start, profile, locator, span, excluded in sorted(found, key=lambda f: f[0]):
        if group and not excluded and not market_handle(profile):
            excluded = 'multi-country group site, channel is not market specific'
        current = best.get(profile['handle_key'])
        if current is None or (current['excluded'] and not excluded):
            best[profile['handle_key']] = dict(profile, span=span, locator=locator, excluded=excluded,
                                               gate=handle_gate(legal_name, profile, names))
    return sorted(best.values(), key=lambda c: (c['platform'], c['url']))


def social_values(raw, subject, legal_name, url, names=()):
    """One (field, value, span, locator, support) per published profile: gate passed and no other entity's block."""
    for candidate in social_links(raw, legal_name, url, names, subject):
        if candidate['excluded'] or not candidate['gate']['publishable']:
            continue
        locator = dict(candidate['locator'], platform=candidate['platform'], handle_score=candidate['gate']['score'],
                       handle_tokens=candidate['gate']['matched'])
        yield FIELD, candidate['handle_key'], candidate['span'], dict(locator, canonical_url=candidate['url']), {}
