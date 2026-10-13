"""Independent audit of hiring_signal and dated_news. Re-derives both from the retained page."""
import hashlib
import json
import re
from urllib.parse import urlsplit, urlunsplit

from shirushi.html_sources import Sections

PRODUCT_LINK = r'produkt|product|service|tjenest|(?<![a-z])pris(?:er|liste)?(?![a-z])'
CAREER_LINK = r'job|career|karriere|stilling|ledig|rekrutter'
HEADINGS = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
QUOTE = re.compile(r"[?'\"\u2018\u2019\u201c\u201d\u00ab\u00bb:]")
DENIAL = re.compile(
    r'\b(?:false|fake|allegation|denied|benektet|rykte|usant|falsk|rumou?rs?|not|ikke|never|aldri|'
    r'said|says|sier|imagine|scenario|possibilit\w*|possible|hypothet\w*|forestill|mulig\w*|hvis|dersom|if|unless|would|could)\b',
    re.I)
DENIAL_SENTENCE = re.compile(
    r'\b(?:ikke|not|no|none|ingen|never|aldri|hvis|dersom|if|unless|would|could|vegne|behalf|agent|said|says|sier)\b',
    re.I)


def fail(reason):
    raise ValueError(reason)


def canonical_url(url):
    parts = urlsplit(url)
    host = (parts.hostname or '').encode('idna').decode('ascii').lower()
    if (parts.scheme != 'https' or not host or parts.username is not None or parts.password is not None
            or parts.port not in (None, 443) or host.endswith('.') or '\\' in url):
        fail('hiring url is not a credential-free https url')
    return urlunsplit(('https', host, parts.path or '/', parts.query, ''))


def careers_url(url):
    parts = urlsplit(url)
    target = (parts.path + '?' + parts.query if parts.query else parts.path).lower()
    return re.search(PRODUCT_LINK, target) is None and re.search(CAREER_LINK, target) is not None


def heading(raw):
    page = Sections(raw)
    chosen = next((node for node in page.nodes if node['tag'] == 'h1' and node['text']), None)
    if chosen is None:
        chosen = next((node for node in page.nodes if node['tag'] == 'title' and node['text']), None)
    if chosen is None:
        return None
    return (page.source[chosen['start']:chosen['end']],
            {'html_start': chosen['start'], 'html_end': chosen['end']})


def articles(raw, url):
    page = Sections(raw)
    found = {}
    for article in page.blocks:
        if article['tag'] != 'article':
            continue
        children = [node for node in page.nodes if article['start'] < node['start'] and node['end'] < article['end']]
        if any(node['tag'] == 'article' for node in children):
            continue
        text = article['text']
        if QUOTE.search(text) or DENIAL.search(text) or DENIAL_SENTENCE.search(text):
            continue
        times = [node for node in children if node['tag'] == 'time' and node['attrs'].get('datetime')]
        headings = [node for node in children if node['tag'] in HEADINGS and node['text']]
        if len(times) != 1 or not headings:
            continue
        published = times[0]['attrs']['datetime']
        if not isinstance(published, str):
            continue
        headline = headings[0]['text']
        value = {'headline': headline, 'published_at': published, 'source_url': url}
        item_key = hashlib.sha256((headline + '\n' + published + '\n' + str(article['start'])).encode()).hexdigest()
        found[item_key] = (value, page.source[article['start']:article['end']],
                           {'html_start': article['start'], 'html_end': article['end']})
    return found


def accepted_website(raw, subject, anchor, receipt, proof):
    """The same page must already be an accepted website: operator proof, or the tier-B derivation."""
    if proof:
        return
    from .website_support import derive, website_candidate
    site = website_candidate(anchor.get('hjemmeside'))
    host = receipt.get('declared_host')
    alias = {site, site[4:] if site and site.startswith('www.') else 'www.' + site} if site else set()
    if host not in alias:
        fail('page has no accepted website')
    derive(raw, subject, anchor, site)


def scope_ok(claim, receipt, anchor, proof):
    scope = claim.get('scope')
    registered = anchor.get('hjemmeside', '')
    registered = urlsplit(registered if '://' in str(registered) else 'https://' + str(registered)).hostname
    actual = urlsplit(receipt['effective_url']).hostname
    registry = bool(registered and actual and registered.removeprefix('www.') == actual.removeprefix('www.'))
    if scope == 'company_owned_html':
        if not proof:
            fail('page lacks operator proof')
    elif scope == 'registry_linked_html':
        if proof or not registry:
            fail('registry-linked page is not the registry host')
    else:
        fail('scope is not a company-page scope')


def identity(subject, claim, field, item_key):
    encoded = json.dumps([subject, field, claim.get('scope'), item_key, None], ensure_ascii=False,
                         sort_keys=True, separators=(',', ':')).encode()
    if (claim.get('claim_id') != hashlib.sha256(encoded).hexdigest() or claim.get('item_key') != item_key
            or claim.get('family') != 'jobs_dated_activity' or claim.get('period') is not None):
        fail('claim identity differs from the derived value')


def audit_recall(subject, claim, item, receipt, raw, anchor, proof):
    scope_ok(claim, receipt, anchor, proof)
    accepted_website(raw, subject, anchor, receipt, proof)
    method = item.get('extraction_method')
    if item.get('support_spans') != {} or not isinstance(item.get('locator'), dict):
        fail('locator or support differs from the page')
    if method == 'careers_page_url_v1':
        if claim.get('field') != 'hiring_signal':
            fail('claim is not a careers-page claim')
        url = receipt['effective_url']
        if not careers_url(url):
            fail('page is not a careers url')
        expected = canonical_url(url)
        found = heading(raw)
        if found is None or claim.get('value') != expected or item.get('claim_span') != found[0] or item.get('locator') != found[1]:
            fail('hiring value or span differs from the page')
        identity(subject, claim, 'hiring_signal', expected)
        return
    if method == 'dated_article_datetime_v1':
        if claim.get('field') != 'dated_news':
            fail('claim is not a dated-news claim')
        found = articles(raw, receipt['effective_url']).get(claim.get('item_key'))
        if found is None or claim.get('value') != found[0] or item.get('claim_span') != found[1] or item.get('locator') != found[2]:
            fail('dated news value or span differs from the page')
        identity(subject, claim, 'dated_news', claim.get('item_key'))
        return
    fail('extraction method is not a recall-family method')
