"""Careers-page URL and role links, published only when the caller already accepted the website."""
import re
from urllib.parse import urljoin, urlsplit

from .fetch import SourceUnavailable, safe_url
from .html_sources import Sections

FIELD = 'hiring_signal'
METHOD = 'careers_page_url_v1'
ROLE_METHOD = 'career_role_link_v1'
ROLE_PATH = re.compile(r'job|career|karriere|stilling|ledig', re.I)
GENERIC_ROLE = re.compile(
    r'^(?:careers?|jobs?|karriere|ledige stillinger|se alle|vis alle|read more|les mer|home|hjem)$', re.I)


def careers_page(url):
    """True when content_links would place this URL in the careers group."""
    from .web_sources import CAREER_LINK, PRODUCT_LINK, lead_target
    target = lead_target(url)
    return re.search(PRODUCT_LINK, target) is None and re.search(CAREER_LINK, target) is not None


def heading_span(raw):
    page = Sections(raw)
    chosen = next((node for node in page.nodes if node['tag'] == 'h1' and node['text']), None)
    if chosen is None:
        chosen = next((node for node in page.nodes if node['tag'] == 'title' and node['text']), None)
    if chosen is None:
        return None
    return (page.source[chosen['start']:chosen['end']],
            {'html_start': chosen['start'], 'html_end': chosen['end']})


def role_links(raw, url):
    """Same-host job links on a careers page. At most eight, in page order."""
    if not careers_page(url):
        return
    page = Sections(raw)
    host = urlsplit(url).hostname
    if not host:
        return
    seen = set()
    count = 0
    for node in page.nodes:
        if node['tag'] != 'a' or count >= 8:
            continue
        text = ' '.join((node.get('text') or '').split())
        href = (node.get('attrs') or {}).get('href') or ''
        if not href or not 4 <= len(text) <= 80 or GENERIC_ROLE.search(text):
            continue
        try:
            absolute = safe_url(urljoin(url, href), {host})
        except (ValueError, SourceUnavailable):
            continue
        path = (urlsplit(absolute).path or '').lower()
        if ROLE_PATH.search(path) is None or absolute.rstrip('/') == url.rstrip('/'):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        count += 1
        yield (FIELD, absolute, page.source[node['start']:node['end']],
               {'html_start': node['start'], 'html_end': node['end']}, {})


def hiring_values(raw, url):
    """One hiring_signal for the careers URL. Role links are a separate method."""
    if not careers_page(url):
        return
    try:
        value = safe_url(url, {urlsplit(url).hostname})
    except ValueError:
        return
    found = heading_span(raw)
    if not found or not found[0]:
        return
    span, locator = found
    yield FIELD, value, span, locator, {}
