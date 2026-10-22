"""Independent audit of social_profile claims; re-derives every link from the retained page bytes."""
import hashlib
import json
import re
import unicodedata
from functools import lru_cache
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from .html_support import BLOCK_ENTITY, BLOCK_NUMBER, name_stem
from .reference import strict_json

METHOD = 'social_profile_link_v1'
DOMAINS = (('facebook.com', 'facebook'), ('fb.com', 'facebook'), ('linkedin.com', 'linkedin'), ('instagram.com', 'instagram'),
           ('x.com', 'x'), ('twitter.com', 'x'), ('youtube.com', 'youtube'), ('tiktok.com', 'tiktok'))
CANONICAL_HOST = {'facebook': 'facebook.com', 'linkedin': 'linkedin.com', 'instagram': 'instagram.com', 'x': 'x.com',
                  'youtube': 'youtube.com', 'tiktok': 'tiktok.com'}
PLAIN_SUBDOMAINS = {'', 'www', 'm', 'mobile', 'web', 'touch', 'mbasic'}
FACEBOOK_REJECT = set((
    'sharer sharer.php share share.php dialog policy.php privacy events groups plugins login login.php recover help profile.php '
    'hashtag tr watch marketplace gaming stories story.php permalink.php photo photo.php video.php videos reel reels l.php ads '
    'business about legal terms terms.php settings public directory search home.php notes connect r.php messages bookmarks '
    'friends places pg').split())
FACEBOOK_TABS = set('about info community reviews services home reels mentions menu offers photos videos'.split())
INSTAGRAM_REJECT = set('p reel reels stories explore accounts tv direct about legal developer web directory tags locations share oauth '
                       'challenge privacy press api'.split())
INSTAGRAM_TAILS = ('reels', 'tagged', 'channel', 'guides')
X_REJECT = set('intent share home search i hashtag explore settings login signup tos privacy messages compose notifications '
               'widgets.js about download'.split())
STOP_TOKENS = set('as asa ans da enk iks sa sam sti stiftelsen nuf ab b v limited ltd inc plc the og and'.split())
GENERIC_TOKENS = set('bygg service norge norway group gruppen eiendom holding invest norske norsk'.split())
GROUP_WORDS = ('group', 'gruppen', 'konsern', 'holding', 'invest', 'eiendom')
COUNTRY_WORDS = ('norge', 'norway', 'norsk', 'norske')
HIDDEN_CLASSES = {'d-none', 'hidden', 'hide', 'sr-only', 'visually-hidden', 'screen-reader-text', 'is-hidden'}
NON_CANDIDATE = {'script', 'style', 'template', 'noscript', 'blockquote', 'q', 'pre', 'code', 'textarea'}
VOID = {'br', 'hr', 'img', 'input', 'meta', 'link', 'source', 'wbr', 'area', 'base', 'embed', 'param', 'track', 'col'}
OWNER_PATHS = ('@graph', 'publisher', 'mainEntity', 'provider', 'copyrightHolder')
SKIPPED_TYPES = {'Person', 'Review', 'Comment', 'Rating', 'Question', 'Answer'}
CONTEXT_WORDS = re.compile(
    r'(?<!\w)(?:customers?|clients?|kunde\w*|partner\w*|samarbeids\w*|leverand\w*|suppliers?|sponsor\w*|referanse\w*|references?|'
    r'testimonial\w*|medlem\w*|members?|konsern\w*|group|gruppen|parent|morselskap|datterselskap|subsidiar\w*|søster\w*|sister|'
    r'affiliate\w*|tilknyttet|laget\s+av|utviklet|developed|design\w*|webdesign\w*|nettside\w*\s+(?:av|by)|powered|built|created|'
    r'made\s+by|produced|hosted|hosting|levert\s+av|drevet\s+av|foto\w*|photo\w*|del\s+av|part\s+of|byrå|agency|forhandler|'
    r'dealer|reseller)(?!\w)', re.I)


def fail(reason):
    raise ValueError('Audit social ' + reason)


def fold(text):
    text = text.lower().replace('æ', 'ae').replace('ø', 'o').replace('å', 'a')
    return ''.join(c for c in unicodedata.normalize('NFD', text) if not unicodedata.combining(c))


def canonical(link):
    """The canonical profile of an absolute URL string, or None."""
    if not isinstance(link, str):
        return None
    link = link.strip()
    if link.startswith('//'):
        link = 'https:' + link
    if len(link) > 2000:
        return None
    try:
        parts = urlsplit(link)
        port, host = parts.port, parts.hostname
    except ValueError:
        return None
    if parts.scheme not in ('http', 'https') or port not in (None, 80, 443) or not host:
        return None
    for domain, platform in DOMAINS:
        if host == domain or host.endswith('.' + domain):
            sub = '' if host == domain else host[:-len(domain) - 1]
            break
    else:
        return None
    if not (sub in PLAIN_SUBDOMAINS or (platform == 'facebook' and re.fullmatch(r'[a-z]{2}-[a-z]{2}', sub))
            or (platform == 'linkedin' and re.fullmatch(r'[a-z]{2}', sub))):
        return None
    raw_segments = [s for s in parts.path.split('/') if s]
    if not raw_segments or len(raw_segments) > 8:
        return None
    segments = [unquote(s) for s in raw_segments]
    for s in segments:
        if len(s) > 150 or any(c.isspace() or unicodedata.category(c) == 'Cc' or c in '/?#' for c in s):
            return None
    first = segments[0].lower()
    if platform == 'facebook' and first == 'plugins':
        inner = parse_qs(parts.query).get('href')
        return canonical(inner[0]) if inner else None
    chosen = choose(platform, segments)
    if chosen is None:
        return None
    path = '/'.join(chosen)
    return {'platform': platform, 'segments': chosen, 'value': (CANONICAL_HOST[platform] + '/' + path).lower(),
            'url': 'https://' + CANONICAL_HOST[platform] + '/' + path}


def choose(platform, segs):
    first = segs[0].lower()
    if platform == 'facebook':
        if first in FACEBOOK_REJECT or first.endswith('.php') or re.fullmatch(r'v[0-9]+\.[0-9]+', first):
            return None
        if first in ('people', 'pages'):
            if len(segs) >= 3 and re.fullmatch(r'[0-9]+', segs[2]) and segs[1].lower() != 'category':
                return [first, segs[1], segs[2]]
            return None
        if len(segs) == 1 or (len(segs) == 2 and segs[1].lower() in FACEBOOK_TABS):
            return [segs[0]]
        return None
    if platform == 'linkedin':
        return ['company', segs[1]] if first == 'company' and len(segs) >= 2 else None
    if platform == 'instagram':
        if (re.fullmatch(r'[A-Za-z0-9._]{1,30}', segs[0]) and first not in INSTAGRAM_REJECT
                and (len(segs) == 1 or (len(segs) == 2 and segs[1].lower() in INSTAGRAM_TAILS))):
            return [segs[0]]
        return None
    if platform == 'x':
        if len(segs) == 1 and re.fullmatch(r'[A-Za-z0-9_]{1,15}', segs[0]) and first not in X_REJECT:
            return [segs[0]]
        return None
    if platform == 'youtube':
        if segs[0].startswith('@') and len(segs[0]) > 1:
            return [segs[0]]
        if first in ('channel', 'user', 'c') and len(segs) >= 2:
            return [first, segs[1]]
        return None
    return [segs[0]] if len(segs) == 1 and segs[0].startswith('@') and len(segs[0]) > 1 else None


def handle_part(canon):
    segs = canon['segments']
    return (segs[1] if len(segs) > 1 else segs[0]).lstrip('@')


def gate(legal_name, canon):
    """(score, tokens) when the handle carries the legal-name tokens, else None."""
    if not isinstance(legal_name, str):
        return None
    folded = fold(legal_name)
    core = [t for t in re.split(r'[^a-z0-9]+', folded) if len(t) > 1 and t not in STOP_TOKENS]
    concatenated = ''.join(core)
    if len(concatenated) < 3:
        return None
    text = re.sub(r'[^a-z0-9]', '', fold(handle_part(canon)))
    if 'aa' not in re.sub(r'[^a-z0-9]', '', folded):
        text = text.replace('aa', 'a')
    if any(w in text and w not in folded for w in GROUP_WORDS):
        return None
    distinctive = [t for t in core if t not in GENERIC_TOKENS]
    if concatenated in text and distinctive:
        return 0.98, core
    if not distinctive and text == concatenated:
        return 0.98, core
    long_distinctive = [t for t in distinctive if len(t) >= 3]
    if (len(long_distinctive) == 1 and long_distinctive[0] in text
            and not any(w in folded and w not in text for w in COUNTRY_WORDS)):
        return 0.95, long_distinctive
    occurring = [t for t in core if t in text]
    if len(core) >= 2 and len(occurring) * 4 >= len(core) * 3 and any(t in distinctive for t in occurring):
        return 0.90, occurring
    return None


def group_site(url):
    parts = urlsplit(url)
    host = parts.hostname or ''
    if host.endswith('.no'):
        return False
    first = next((s for s in parts.path.split('/') if s), '').lower()
    labels = host.split('.')
    return bool(re.fullmatch(r'[a-z]{2}[-_][a-z]{2}', first)
                or (len(labels) >= 3 and re.fullmatch(r'[a-z]{2}(?:-[a-z]{2})?', labels[0])))


def market_channel(canon):
    handle = handle_part(canon).lower()
    return handle.endswith(('.no', '-no', '_no')) or any(w in fold(handle) for w in ('norge', 'norway', 'norsk'))


class Tree(HTMLParser):
    """Elements with source offsets; an unmatched end tag closes back to the nearest open element of that name."""

    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.source = raw.decode('utf-8')
        self.offsets = [0]
        for line in self.source.split('\n')[:-1]:
            self.offsets.append(self.offsets[-1] + len(line) + 1)
        self.stack, self.elements, self.scripts = [], [], []
        self.feed(self.source)
        self.close()
        for element in self.stack:
            element['end'] = len(self.source)

    def position(self):
        line, column = self.getpos()
        return self.offsets[line - 1] + column

    def open(self, tag, attributes, closed):
        start = self.position()
        attrs = {k: (v if v is not None else '') for k, v in attributes}
        parent = self.stack[-1] if self.stack else None
        outside = parent['out'] if parent else False
        style = attrs.get('style') or ''
        hidden = ('hidden' in attrs or attrs.get('aria-hidden') == 'true'
                  or bool(re.search(r'(?:display\s*:\s*none|visibility\s*:\s*hidden)', style, re.I))
                  or bool(set((attrs.get('class') or '').lower().split()) & HIDDEN_CLASSES))
        element = {'tag': tag, 'start': start, 'open_end': start + len(self.get_starttag_text()), 'end': None, 'attrs': attrs,
                   'parent': parent, 'parent_out': outside, 'out': outside or hidden or tag in NON_CANDIDATE}
        self.elements.append(element)
        if closed or tag in VOID:
            element['end'] = element['open_end']
        else:
            self.stack.append(element)

    def handle_starttag(self, tag, attrs):
        self.open(tag, attrs, False)

    def handle_startendtag(self, tag, attrs):
        self.open(tag, attrs, True)

    def handle_endtag(self, tag):
        index = next((i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i]['tag'] == tag), None)
        if index is None:
            return
        position = self.position()
        found = self.source.find('>', position)
        end = found + 1 if found >= 0 else len(self.source)
        closing = self.stack[index:]
        del self.stack[index:]
        for element in closing:
            element['end'] = end
        script = closing[0]
        if tag == 'script' and (script['attrs'].get('type') or '').lower() == 'application/ld+json':
            self.scripts.append({'start': script['open_end'], 'end': position, 'out': script['parent_out']})


@lru_cache(maxsize=4)
def tree(raw):
    return Tree(raw)


def literal_tree(text):
    """Offsets of every string literal of a valid JSON text, as a nested structure."""
    position = 0

    def skip():
        nonlocal position
        while text[position] in ' \t\r\n':
            position += 1

    def string():
        nonlocal position
        start = position
        position += 1
        while text[position] != '"':
            position += 2 if text[position] == '\\' else 1
        position += 1
        return ('s', start, position)

    def value():
        nonlocal position
        skip()
        char = text[position]
        if char == '"':
            return string()
        if char in '[{':
            position += 1
            items, mapping = [], {}
            skip()
            if text[position] in ']}':
                position += 1
                return ('o', mapping) if char == '{' else ('a', items)
            while True:
                skip()
                if char == '{':
                    key = json.loads(text[slice(*string()[1:])])
                    skip()
                    position += 1
                    mapping[key] = value()
                else:
                    items.append(value())
                skip()
                if text[position] == ',':
                    position += 1
                    continue
                position += 1
                return ('o', mapping) if char == '{' else ('a', items)
        start = position
        while position < len(text) and text[position] not in ',]} \t\r\n':
            position += 1
        return ('x', start, position)

    return value()


def at_path(node, path):
    for step in path:
        if node[0] == 'o' and isinstance(step, str):
            node = node[1][step]
        elif node[0] == 'a' and type(step) is int:
            node = node[1][step]
        else:
            raise KeyError(step)
    return node


def skipped(node, subject):
    kinds = node.get('@type')
    kinds = kinds if isinstance(kinds, list) else [kinds]
    if any(k in SKIPPED_TYPES for k in kinds if isinstance(k, str)):
        return True
    for key in ('identifier', 'taxID', 'vatID'):
        values = node.get(key)
        for value in values if isinstance(values, list) else [values]:
            if isinstance(value, dict):
                value = value.get('value')
            if isinstance(value, (str, int)) and not isinstance(value, bool):
                digits = re.sub(r'\D', '', str(value))
                if len(digits) == 9 and digits != subject:
                    return True
    return False


def owner_nodes(value, path, subject):
    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from owner_nodes(item, path + [index], subject)
    elif isinstance(value, dict) and not skipped(value, subject):
        yield path, value
        for key in OWNER_PATHS:
            if key in value:
                yield from owner_nodes(value[key], path + [key], subject)


def visible_text(segment, forms):
    segment = re.sub(r'<!--.*?(?:-->|\Z)', ' ', segment, flags=re.S)
    segment = re.sub(r'<(script|style|svg)\b.*?(?:</\1\s*>|\Z)', ' ', segment, flags=re.S | re.I)

    def plain(markup):
        return ' '.join(unescape(re.sub(r'<[^>]*>', ' ', markup)).split())

    segment = re.sub(r'<a\b[^>]*>(.*?)</a\s*>', lambda m: ' ' if len(plain(m.group(1))) <= 30 else m.group(0), segment,
                     flags=re.S | re.I)
    text = plain(segment)
    for form in forms:
        pattern = r'\s+'.join(re.escape(word) for word in form.split())
        if pattern:
            text = re.sub(pattern, ' ', text, flags=re.I)
    return ' '.join(text.split())


def context_excluded(page, element, forms, subject):
    node = element
    for _ in range(6):
        node = node['parent']
        if node is None:
            return False
        text = visible_text(page.source[node['open_end']:element['start']], forms)
        if sum(c.isalpha() for c in text) >= 3:
            text = text[-120:]
            numbers = {re.sub(r'\D', '', n) for n in re.findall(BLOCK_NUMBER, text, re.I)}
            return bool(numbers - {subject} or CONTEXT_WORDS.search(text) or BLOCK_ENTITY.search(text))
    return False


@lru_cache(maxsize=4)
def derive(raw, page_url, subject, legal_name):
    """Every publishable value of the page: value -> (span, locator), per the first non-excluded occurrence."""
    page = tree(raw)
    if not isinstance(legal_name, str) or not legal_name.strip():
        return {}
    forms = [legal_name]
    grouped = group_site(page_url)
    candidates = []

    def consider(source, raw_url, start, end, extra):
        canon = canonical(urljoin(page_url, raw_url.strip())) if isinstance(raw_url, str) else None
        if canon is None:
            return
        scored = gate(legal_name, canon)
        if scored is None or (grouped and not market_channel(canon)):
            return
        locator = dict(extra, source=source, raw_url=raw_url, html_start=start, html_end=end, platform=canon['platform'],
                       handle_score=scored[0], handle_tokens=list(scored[1]), canonical_url=canon['url'])
        candidates.append((start, len(candidates), canon['value'], page.source[start:end], locator))

    for element in page.elements:
        if element['out']:
            continue
        attrs = element['attrs']
        extra = {'element_end': element['end']}
        sources = []
        if element['tag'] == 'a' and attrs.get('href'):
            sources.append(('a_href', attrs['href']))
        if attrs.get('data-href'):
            sources.append(('data_href', attrs['data-href']))
        if element['tag'] == 'iframe' and attrs.get('src'):
            sources.append(('iframe_src', attrs['src']))
        if sources and not context_excluded(page, element, forms, subject):
            for source, raw_url in sources:
                consider(source, raw_url, element['start'], element['open_end'], extra)
    for index, script in enumerate(page.scripts):
        if script['out']:
            continue
        text = page.source[script['start']:script['end']]
        try:
            document = strict_json(text)
            literals = literal_tree(text)
        except (ValueError, RecursionError, IndexError):
            continue
        for path, node in owner_nodes(document, [], subject):
            same_as = node.get('sameAs')
            if same_as is None:
                continue
            name = node.get('name')
            if name not in (None, '') and (not isinstance(name, str) or (name.strip() and name_stem(name) != name_stem(legal_name))):
                continue
            for position, link in enumerate(same_as if isinstance(same_as, list) else [same_as]):
                if not isinstance(link, str):
                    continue
                try:
                    found = at_path(literals, path + ['sameAs'] + ([position] if isinstance(same_as, list) else []))
                except (KeyError, IndexError):
                    continue
                if found[0] != 's':
                    continue
                consider('json_ld_same_as', link, script['start'] + found[1], script['start'] + found[2],
                         {'script_index': index, 'node_path': path + ['sameAs', position]})
    published = {}
    for start, order, value, span, locator in sorted(candidates, key=lambda c: c[:2]):
        published.setdefault(value, (span, locator))
    return published


def audit_social(subject, claim, item, receipt, raw, anchor, proof):
    """Accept exactly the social_profile claims the spec allows for this retained page."""
    scope = claim.get('scope')
    registered = anchor.get('hjemmeside', '')
    registered = urlsplit(registered if '://' in registered else 'https://' + registered).hostname
    actual = urlsplit(receipt['effective_url']).hostname
    registry = bool(registered and actual and registered.removeprefix('www.') == actual.removeprefix('www.'))
    if scope == 'registry_linked_html':
        if not registry:
            fail('profile page is not on the registry host')
    elif scope == 'company_owned_html':
        if not proof:
            fail('profile page lacks operator proof')
    else:
        fail('scope is not a company-page scope')
    value = claim.get('value')
    if claim.get('field') != 'social_profile' or item.get('extraction_method') != METHOD or not isinstance(value, str):
        fail('claim is not a profile link claim')
    found = derive(raw, receipt['effective_url'], subject, anchor.get('navn', '')).get(value)
    if found is None:
        fail('value is not a publishable profile link of this page')
    span, locator = found
    actual_locator = item.get('locator')
    if (not isinstance(actual_locator, dict) or actual_locator != locator or item.get('claim_span') != span
            or any(type(actual_locator[k]) is not int for k in ('html_start', 'html_end', 'element_end', 'script_index')
                   if k in actual_locator)
             or item.get('support_spans') != {}):
        fail('locator, span or support differs from the derived link')
    encoded = json.dumps([subject, 'social_profile', scope, value, None], ensure_ascii=False,
                         sort_keys=True, separators=(',', ':')).encode()
    if (claim.get('item_key') != value or claim.get('family') != 'website_owned_profiles' or claim.get('period') is not None
            or claim.get('claim_id') != hashlib.sha256(encoded).hexdigest()):
        fail('claim identity differs from the canonical value')
