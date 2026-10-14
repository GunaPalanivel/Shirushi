"""Independent corroboration of a structured company profile and contact record."""
import hashlib
import json
import re
from urllib.parse import urljoin, urlsplit

from .html_support import document
from .live_support import StructuredScripts
from .reference import strict_json


def audit_profile(subject, claim, item, receipt, raw, anchor):
    registered = anchor.get('hjemmeside', '')
    registered = urlsplit(registered if '://' in registered else 'https://' + registered).hostname
    actual = urlsplit(receipt['effective_url']).hostname
    if not registered or not actual or registered.removeprefix('www.') != actual.removeprefix('www.'):
        raise ValueError('Audit corroborated profile lacks registered source host')
    locator = item['locator']
    scripts = StructuredScripts(raw).items
    index = locator.get('script_index')
    if type(index) is not int or not 0 <= index < len(scripts) or scripts[index] != item['claim_span']:
        raise ValueError('Audit corroborated profile script mismatch')
    node = strict_json(scripts[index])
    context = node.get('@context') if isinstance(node, dict) else None
    for part in locator['node_path']:
        if isinstance(node, list) and type(part) is int and part >= 0:
            node = node[part]
        elif isinstance(node, dict) and part == '@graph':
            node = node[part]
        else:
            raise ValueError('Audit profile path is not a graph organization')
        if isinstance(node, dict) and '@context' in node:
            context = node['@context']
    if isinstance(context, dict) and set(context) == {'@vocab'}:
        context = context['@vocab']
    if (not isinstance(context, str) or context.rstrip('/') not in
            {'http://schema.org', 'https://schema.org', 'http://www.schema.org', 'https://www.schema.org'}):
        raise ValueError('Audit profile schema context is not supported')
    kind = node.get('@type')
    kinds = kind if isinstance(kind, list) else [kind]
    name = anchor['navn']
    if ('Organization' not in kinds or any(node.get(k) not in (None, '') for k in ('identifier', 'taxID', 'vatID'))
            or not isinstance(node.get('name'), str)
            or ' '.join(node['name'].split()).casefold() != ' '.join(name.split()).casefold()):
        raise ValueError('Audit profile legal name/type/identifier contradiction')
    address = node.get('address')
    if not isinstance(address, dict):
        raise ValueError('Audit profile lacks address context')
    values = [address.get(k) for k in ('streetAddress', 'postalCode', 'addressLocality')]
    if any(not isinstance(v, str) or not v.strip() for v in values):
        raise ValueError('Audit profile address fields absent')
    for key in ('@id', 'url'):
        if node.get(key):
            if not isinstance(node[key], str):
                raise ValueError('Audit profile source URL type invalid')
            url = urlsplit(urljoin(receipt['effective_url'], node[key]))
            if (url.scheme != 'https' or url.username is not None or url.password is not None
                    or url.port not in (None, 443) or not url.hostname
                    or url.hostname.removeprefix('www.') != actual.removeprefix('www.')):
                raise ValueError('Audit profile belongs to another source URL')
    page = document(raw)
    footers = [n for n in page.nodes if n['tag'] == 'footer']
    def identifiers(text):
        matches = re.findall(r'(?:org(?:anisasjons)?\.?\s*(?:nr|nummer)\.?|organi[sz]ation\s+(?:number|no\.?))'
            r'\s*:?\s*(?:NO\s*)?([0-9]{3}[ .]?[0-9]{3}[ .]?[0-9]{3})(?![0-9])', text, re.I)
        return {re.sub(r'\D', '', v) for v in matches}
    if not footers or any(identifiers(f['text']) - {subject} for f in footers):
        raise ValueError('Audit profile footer contains conflicting identity')
    contexts = {}
    for footer in footers:
        enclosing = [n for n in page.nodes if n['tag'] not in ('html', 'body')
                     and n['start'] < footer['start'] and footer['end'] < n['end']]
        expected = sum(tag not in ('html', 'body') for tag in footer['ancestors'])
        if len(enclosing) != expected:
            raise ValueError('Audit profile identity container is not closed')
        surrounding_node = min(enclosing, key=lambda n: n['start']) if enclosing else footer
        if len(surrounding_node['text']) > 1500:
            raise ValueError('Audit profile identity container is unbounded')
        contexts[footer['start']] = surrounding_node
        surrounding = re.sub(re.escape(name), '', surrounding_node['text'], flags=re.I)
        if (re.search(r'\b(?:customers?|clients?|kunde\w*|parent|subsidiar\w*|morselskap|datterselskap|not|ikke|hvis|dersom|if|behalf|vegne)\b', surrounding, re.I)
                or re.search(r'["\u201c\u201d\u00ab\u00bb]|(?<!\w)[\x27\u2018\u2019](?!\w)', surrounding)):
            raise ValueError('Audit profile enclosing footer is not an own-identity record')
    proofs = []
    address_expression = (r'(?<!\w)' + re.escape(' '.join(values[0].split()).casefold())
        + r'\s*[,;]?\s+' + re.escape(' '.join(values[1].split()).casefold())
        + r'\s+' + re.escape(' '.join(values[2].split()).casefold()) + r'(?!\w)')
    for n in page.nodes:
        if n['tag'] not in ('footer', 'div', 'section', 'address', 'p') or not 10 <= len(n['text']) <= 1500:
            continue
        if not any(f['start'] <= n['start'] and n['end'] <= f['end'] for f in footers):
            continue
        if (identifiers(n['text']) != {subject}
                or not re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', n['text'], re.I)):
            continue
        normalized = ' '.join(n['text'].split()).casefold()
        if not re.search(address_expression, normalized):
            continue
        if not any(n['start'] <= child['start'] and child['end'] <= n['end']
                   and child['tag'] in ('p', 'span', 'strong', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6')
                   and ' '.join(child['text'].split()).casefold() == ' '.join(name.split()).casefold()
                   for child in page.nodes):
            continue
        context = re.sub(re.escape(name), '', n['text'], flags=re.I)
        if (re.search(r"[?'\"\u2018\u2019\u201c\u201d\u00ab\u00bb:]\s*(?:not|ikke)", context, re.I)
                or re.search(r'\b(?:customer|client|kunde|not|ikke|hvis|dersom|if|behalf|vegne)\b', context, re.I)):
            continue
        proofs.extend(contexts[f['start']] for f in footers if f['start'] <= n['start'] and n['end'] <= f['end'])
    if not proofs:
        raise ValueError('Audit profile cannot bind name/address to legal number')
    proof = min(proofs, key=lambda n: n['end'] - n['start'])
    if (type(locator.get('identity_html_start')) is not int or type(locator.get('identity_html_end')) is not int
            or (proof['start'], proof['end']) != (locator['identity_html_start'], locator['identity_html_end'])
            or item.get('support_spans') != {'legal_identity': page.source[proof['start']:proof['end']]}):
        raise ValueError('Audit profile identity support locator mismatch')
    value = node.get('description')
    encoded = json.dumps([subject, 'business_description', 'registry_linked_structured', None, None],
                         ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    if (not isinstance(value, str) or not 10 <= len(value.strip()) <= 2000 or claim['value'] != value
            or claim['field'] != 'business_description' or claim.get('family') != 'business_products'
            or claim.get('scope') != 'registry_linked_structured' or claim.get('period') is not None
            or claim.get('item_key') is not None or claim['claim_id'] != hashlib.sha256(encoded).hexdigest()):
        raise ValueError('Audit profile description or canonical identity mismatch')
