"""Corroborate structured company records against visible legal contact data."""
import re
from urllib.parse import urljoin, urlsplit

from .fetch import safe_url, website_hosts
from .html_sources import Sections, names, org_numbers

SCHEMA_CONTEXTS = {'http://schema.org', 'https://schema.org', 'http://www.schema.org', 'https://www.schema.org'}


def schema_context(root, path):
    context = root.get('@context') if isinstance(root, dict) else None
    for part in path:
        root = root[part]
        if isinstance(root, dict) and '@context' in root:
            context = root['@context']
    if isinstance(context, dict) and set(context) == {'@vocab'}:
        context = context['@vocab']
    return isinstance(context, str) and context.rstrip('/') in SCHEMA_CONTEXTS


def contact_proof(raw, node, subject, legal_name, url):
    kinds = node.get('@type')
    kinds = kinds if isinstance(kinds, list) else [kinds]
    if ('Organization' not in kinds or any(node.get(k) not in (None, '') for k in ('identifier', 'taxID', 'vatID'))
            or not isinstance(node.get('name'), str)
            or ' '.join(node['name'].split()).casefold() != ' '.join(legal_name.split()).casefold()):
        return None
    address = node.get('address')
    if not isinstance(address, dict):
        return None
    parts = [address.get(k) for k in ('streetAddress', 'postalCode', 'addressLocality')]
    if any(not isinstance(v, str) or not v.strip() for v in parts):
        return None
    for key in ('@id', 'url'):
        if node.get(key):
            if not isinstance(node[key], str):
                return None
            try:
                safe_url(urljoin(url, node[key]), website_hosts(urlsplit(url).hostname))
            except ValueError:
                return None
    page = Sections(raw)
    footers = [n for n in page.nodes if n['tag'] == 'footer']
    if not footers or any(org_numbers(f['text']) - {subject} for f in footers):
        return None
    scopes = {}
    for footer in footers:
        containers = [n for n in page.nodes if n['tag'] not in {'html', 'body'}
                      and n['start'] < footer['start'] and footer['end'] < n['end']]
        if len(containers) != sum(tag not in {'html', 'body'} for tag in footer['ancestors']):
            return None
        scope = min(containers, key=lambda n: n['start']) if containers else footer
        if len(scope['text']) > 1500:
            return None
        scopes[footer['start']] = scope
        context = re.sub(re.escape(legal_name), '', scope['text'], flags=re.I)
        if (re.search(r'\b(?:customers?|clients?|kunde\w*|parent|subsidiar\w*|morselskap|datterselskap|not|ikke|hvis|dersom|if|behalf|vegne)\b', context, re.I)
                or re.search(r'["\u201c\u201d\u00ab\u00bb]|(?<!\w)[\x27\u2018\u2019](?!\w)', context)):
            return None
    candidates = []
    expected_address = (r'(?<!\w)' + re.escape(' '.join(parts[0].split()).casefold())
        + r'\s*[,;]?\s+' + re.escape(' '.join(parts[1].split()).casefold())
        + r'\s+' + re.escape(' '.join(parts[2].split()).casefold()) + r'(?!\w)')
    for n in page.nodes:
        if n['tag'] not in {'footer', 'div', 'section', 'address', 'p'} or not 10 <= len(n['text']) <= 1500:
            continue
        if not any(f['start'] <= n['start'] and n['end'] <= f['end'] for f in footers):
            continue
        if not names(n['text'], legal_name) or org_numbers(n['text']) != {subject}:
            continue
        normalized = ' '.join(n['text'].split()).casefold()
        if not re.search(expected_address, normalized):
            continue
        if not any(n['start'] <= child['start'] and child['end'] <= n['end']
                   and child['tag'] in {'p', 'span', 'strong', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
                   and ' '.join(child['text'].split()).casefold() == ' '.join(legal_name.split()).casefold()
                   for child in page.nodes):
            continue
        context = re.sub(re.escape(legal_name), '', n['text'], flags=re.I)
        if (re.search(r"[?'\"\u2018\u2019\u201c\u201d\u00ab\u00bb:]\s*(?:not|ikke)", context, re.I)
                or re.search(r'\b(?:customer|client|kunde|not|ikke|hvis|dersom|if|behalf|vegne)\b', context, re.I)):
            continue
        # Keep the enclosing identity context, including sibling role labels.
        candidates.extend(scopes[f['start']] for f in footers if f['start'] <= n['start'] and n['end'] <= f['end'])
    return min(candidates, key=lambda n: n['end'] - n['start']) if candidates else None
