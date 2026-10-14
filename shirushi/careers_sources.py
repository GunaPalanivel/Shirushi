"""Careers-page URL published only when the caller already accepted the website."""
import re
from urllib.parse import urlsplit

from .fetch import safe_url
from .html_sources import Sections

FIELD = 'hiring_signal'
METHOD = 'careers_page_url_v1'


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


def hiring_values(raw, url):
    """One hiring_signal for a careers URL, or nothing. The caller gates on verified_website."""
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
