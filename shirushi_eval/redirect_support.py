"""Independent audit of a company page reached through a registry-declared host's redirect chain.

Re-derives every rule from the retained receipts and bytes; imports no maker code. A page on a host outside the
registry aliases is accepted only when the chain root satisfies all of: a bounded permanent https chain issued by
the registry host, a destination that is not a shared namespace, the exact legal name on the destination page, and
robots policies of both the registry host and the destination that were retained and still allow the requests."""
import hashlib
import ipaddress
import re
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from .html_support import document
from .reference import strict_json

PERMANENT = (301, 308)
MAX_HOPS = 3
USER_AGENT = 'Shirushi/0.1'

# Hosts that are shared namespaces, social or directory profiles, redirectors, parking pages or bank/insurance
# groups: a redirect into them says nothing about who the destination belongs to.
DENIED_DOMAINS = {
    'site builders and hosting': (
        'wixsite.com', 'wix.com', 'squarespace.com', 'myshopify.com', 'shopify.com', 'webflow.io', 'webflow.com',
        'wordpress.com', 'weebly.com', 'blogspot.com', 'github.io', 'netlify.app', 'vercel.app', 'pages.dev',
        'herokuapp.com', 'azurewebsites.net', 'onrender.com', 'godaddysites.com', 'business.site', 'canva.site',
        'carrd.co', 'notion.site', 'framer.website', 'strikingly.com', 'jimdosite.com'),
    'social, directory, marketplace and registry pages': (
        'facebook.com', 'fb.com', 'instagram.com', 'linkedin.com', 'lnkd.in', 'twitter.com', 'x.com', 'youtube.com',
        'tiktok.com', 'proff.no', 'gulesider.no', '1881.no', 'finn.no', 'brreg.no'),
    'link shorteners': ('bit.ly', 't.co', 'tinyurl.com', 'goo.gl', 'ow.ly', 'buff.ly', 'cutt.ly', 'rebrand.ly',
                        'is.gd', 'shorturl.at'),
    'parking and for sale': ('sedoparking.com', 'parkingcrew.net', 'hugedomains.com', 'dan.com', 'afternic.com'),
    'bank and insurance groups': (
        'sparebank1.no', 'dnb.no', 'nordea.no', 'nordea.com', 'handelsbanken.no', 'danskebank.no', 'gjensidige.no',
        'storebrand.no', 'if.no', 'tryg.no', 'fremtind.no', 'eika.no', 'sbanken.no'),
}
DENIED = frozenset(domain for group in DENIED_DOMAINS.values() for domain in group)

# Public suffixes of more than one label that the auditor knows; a conservative handwritten subset.
NORID_CATEGORIES = ('priv', 'kommune', 'fylkesbibl', 'folkebibl', 'museum', 'idrett', 'vgs', 'fhs', 'herad', 'gielda',
                    'suohkan', 'tjielte', 'uenorge', 'dep', 'mil', 'stat')
NORID_COUNTIES = ('aa', 'ah', 'bu', 'fm', 'hl', 'hm', 'jan-mayen', 'mr', 'nl', 'nt', 'of', 'ol', 'oslo', 'rl', 'sf', 'st',
                  'svalbard', 'tm', 'tr', 'va', 'vf')
COUNTRY_SECOND_LEVELS = ('co.uk', 'org.uk', 'ac.uk', 'gov.uk', 'me.uk', 'ltd.uk', 'plc.uk', 'net.uk', 'sch.uk', 'com.au',
                         'net.au', 'org.au', 'co.nz', 'co.jp', 'com.br', 'co.za', 'com.tr', 'co.in', 'com.cn', 'com.hk',
                         'com.sg', 'com.mx', 'co.il')
MULTI_LABEL_SUFFIXES = frozenset(label + '.no' for label in NORID_CATEGORIES + NORID_COUNTIES) | frozenset(COUNTRY_SECOND_LEVELS)
GENERIC_SECOND_LEVELS = frozenset(('co', 'com', 'org', 'net', 'gov', 'edu', 'ac', 'or', 'ne', 'go', 'ltd', 'plc', 'me', 'sch'))
NON_PUBLIC_TLDS = frozenset(('local', 'localhost', 'internal', 'lan', 'home', 'corp', 'intranet', 'arpa', 'onion'))
LABEL = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?')
TLD = re.compile(r'(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})')


class Refusal(ValueError):
    """A rule the chain or its evidence does not satisfy; the text names the rule."""


def aliases(host):
    """The host and its www counterpart: the only hosts one declared site may occupy."""
    return {host, host[4:] if host.startswith('www.') else 'www.' + host}


def public_host(host):
    """Lowercase ASCII DNS name with a real TLD: no IP spelling, no single label, no private-use suffix."""
    if not isinstance(host, str) or not host.isascii() or host != host.lower() or len(host) > 253:
        return False
    labels = host.split('.')
    if len(labels) < 2 or not all(LABEL.fullmatch(label) for label in labels) or not TLD.fullmatch(labels[-1]):
        return False
    if labels[-1] in NON_PUBLIC_TLDS or labels[-1].startswith('0x'):
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return True
    return False


def registrable_domain(host):
    """Suffix plus one label, or None for a bare suffix, a single label or a malformed name."""
    if not isinstance(host, str) or not host:
        return None
    labels = host.lower().split('.')
    if len(labels) < 2 or not all(labels):
        return None
    width = 1
    for size in (3, 2):
        if len(labels) >= size and '.'.join(labels[-size:]) in MULTI_LABEL_SUFFIXES:
            width = size
            break
    else:
        if len(labels[-1]) == 2 and labels[-2] in GENERIC_SECOND_LEVELS:
            width = 2
    if len(labels) == width:
        return None
    return '.'.join(labels[-(width + 1):])


def shared_host(host):
    return any(host == domain or host.endswith('.' + domain) for domain in DENIED)


def split_url(url):
    """(host, path, query) of a canonical credential-free https URL on port 443, else None."""
    if (not isinstance(url, str) or '#' in url or '\\' in url or not url.startswith('https://')
            or any(ord(c) <= 32 or ord(c) == 127 for c in url)):
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if (parts.scheme != 'https' or not parts.path.startswith('/') or '@' in parts.netloc or ':' in parts.netloc
            or not public_host(parts.netloc)):
        return None
    return parts.netloc, parts.path, parts.query


def destination_failure(host):
    if not public_host(host):
        return 'chain: host ' + repr(host) + ' is not a public DNS name'
    if shared_host(host):
        return 'chain: host ' + host + ' is a shared, profile, redirector or group domain'
    if registrable_domain(host) is None:
        return 'chain: host ' + host + ' is a bare public suffix'
    return None


def chain_failure(requested, chain, effective, registry_host, path='/'):
    """Why a persisted chain is not a registry-issued cross-domain permanent chain, or None when it is."""
    try:
        return chain_reason(requested, chain, effective, registry_host, path)
    except (TypeError, ValueError, AttributeError) as exc:
        return 'chain: malformed (' + type(exc).__name__ + ')'


def chain_reason(requested, chain, effective, registry_host, path):
    if not isinstance(registry_host, str) or not public_host(registry_host):
        return 'chain: the registry declares no usable host'
    start = split_url(requested)
    if start is None:
        return 'chain: requested url is not a canonical https url'
    registry = aliases(registry_host)
    if start[0] not in registry:
        return 'chain: requested url is not on the registry host'
    if start[1] != path or start[2]:
        return 'chain: requested url is not the fixed registry path'
    if not isinstance(chain, list) or not 1 <= len(chain) <= MAX_HOPS:
        return 'chain: must hold between 1 and %d hops' % MAX_HOPS
    expected, destination, allowed = requested, None, None
    for number, hop in enumerate(chain):
        if not isinstance(hop, dict) or not {'from', 'to', 'http_status'} <= set(hop):
            return 'chain: hop %d is malformed' % number
        if hop['from'] != expected:
            return 'chain: hop %d does not continue the previous url' % number
        if type(hop['http_status']) is not int or hop['http_status'] not in PERMANENT:
            return 'chain: hop %d is not a permanent redirect' % number
        source, target = split_url(hop['from']), split_url(hop['to'])
        if source is None or target is None:
            return 'chain: hop %d is not a canonical https url' % number
        if destination is None and target[0] in registry:
            expected = hop['to']
            continue
        if destination is None:  # the crossing hop
            if source[0] not in registry or source[1] != path or source[2]:
                return 'chain: the crossing hop is not issued for the fixed registry path'
            destination, allowed = target[0], aliases(target[0])
            for host in sorted(allowed):
                reason = destination_failure(host)
                if reason:
                    return reason
        elif target[0] not in allowed:
            return 'chain: hop %d leaves the destination domain' % number
        expected = hop['to']
    if destination is None:
        return 'chain: never leaves the registry host aliases'
    if effective != expected:
        return 'chain: does not end at the effective url'
    return None


IDENTITY_TAGS = ('title', 'h1', 'footer', 'address')
CONTACT_WORDS = ('contact', 'kontakt')
CONTACT_LIMIT = 1500


def identity_block(node):
    """Blocks where a site states who it is: title, h1, footer, address or a bounded contact element."""
    if node['tag'] in IDENTITY_TAGS:
        return True
    marks = ' '.join(str(node['attrs'].get(key) or '') for key in ('id', 'class')).lower()
    return (node['tag'] not in ('html', 'body', 'main') and any(word in marks for word in CONTACT_WORDS)
            and len(node['text']) <= CONTACT_LIMIT)


def legal_name_visible(raw, name):
    """True when the exact legal name is a whole word in the visible text of an identity block.

    Scripts and hidden or quoted parts never count; a mention in body text, lower headings, lists, news items
    or main-column paragraphs does not anchor, because those can describe someone else's company."""
    if not isinstance(name, str) or not name.split():
        return False
    try:
        page = document(raw)
    except (UnicodeDecodeError, ValueError):
        return False
    pattern = r'(?<!\w)' + r'\s+'.join(re.escape(word) for word in name.split()) + r'(?!\w)'
    return any(identity_block(node) and re.search(pattern, node['text'], re.I) for node in page.nodes)


def load(audit, kind, identifier, label):
    try:
        data = audit.read(kind, identifier)
        return strict_json(data) if kind == 'receipts' else data
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise Refusal(label + ' unreadable: ' + str(exc)) from None


def receipt_with_bytes(audit, identifier, label):
    receipt = load(audit, 'receipts', identifier, label)
    if not isinstance(receipt, dict):
        raise Refusal(label + ' is not an object')
    return receipt, load(audit, 'objects', receipt.get('content_sha256'), label + ' object')


def robots_failure(audit, identifier, label, source_url, page_url, rule_host, chain_path=None):
    """Re-read a retained robots policy and require that it allows page_url for the crawler."""
    receipt, raw = receipt_with_bytes(audit, identifier, label)
    status = receipt.get('http_status')
    if (receipt.get('source_class') != 'robots_policy' or receipt.get('source_url') != source_url
            or type(status) is not int or status not in (200, 404)):
        raise Refusal(label + ' is not the retained robots policy of ' + source_url)
    if status == 200 and receipt.get('sha256') != hashlib.sha256(raw).hexdigest():
        raise Refusal(label + ' hash differs from its receipt')
    chain = receipt.get('redirect_chain')
    if chain:  # robots.txt may only cross domains from the registry host, under the same rules
        if chain_path is None:
            targets = [split_url(hop.get('to')) if isinstance(hop, dict) else None for hop in chain] if isinstance(chain, list) else [None]
            if any(target is None or target[0] not in aliases(rule_host) for target in targets):
                raise Refusal(label + ' left its host')
        else:
            reason = chain_failure(source_url, chain, receipt.get('effective_url'), rule_host, chain_path)
            if reason:
                raise Refusal(label + ' ' + reason)
    elif receipt.get('effective_url') != source_url:
        raise Refusal(label + ' effective url differs without a chain')
    try:
        rules = raw.decode('utf-8').splitlines() if status == 200 else []
    except UnicodeDecodeError:
        raise Refusal(label + ' is not text') from None
    parser = RobotFileParser(source_url)
    parser.parse(rules)
    if not parser.can_fetch(USER_AGENT, page_url):
        raise Refusal(label + ' disallows ' + page_url)


def link_failure(audit, subject, receipt, anchor):
    """None when the company page is registry-linked through a verified redirect chain, else the reason."""
    try:
        verify(audit, subject, receipt, anchor)
    except Refusal as exc:
        return str(exc)
    except (ValueError, KeyError, TypeError, OSError, AttributeError) as exc:
        return 'chain: unreadable evidence (' + type(exc).__name__ + ')'
    return None


def verify(audit, subject, receipt, anchor):
    website = anchor.get('hjemmeside')
    parts = urlsplit(website if '://' in website else 'https://' + website) if isinstance(website, str) and website else None
    registry_host = parts.hostname if parts else None
    if not registry_host:
        raise Refusal('chain: the registry declares no website')
    if not receipt.get('robots_snapshot_id'):
        raise Refusal('robots: the page has no retained robots policy')
    identifier = receipt.get('redirect_anchor_snapshot_id')
    if identifier is None:
        root = receipt
        raw = audit.read('objects', receipt['content_sha256'])
    else:
        if not isinstance(identifier, str):
            raise Refusal('anchor: redirect anchor is not a snapshot identity')
        root, raw = receipt_with_bytes(audit, identifier, 'root receipt (anchor)')
        if root.get('redirect_anchor_snapshot_id') is not None:
            raise Refusal('anchor: a chain root cannot itself point at another anchor')
    if root.get('source_class') != 'company_owned':
        raise Refusal('root receipt (anchor) is not a company page')
    reason = chain_failure(root.get('requested_url'), root.get('redirect_chain'), root.get('effective_url'), registry_host, '/')
    if reason:
        raise Refusal(reason)
    effective = urlsplit(root['effective_url'])
    if (root.get('organisation_number') != subject):
        raise Refusal('root receipt organisation differs from the claim')
    if type(root.get('http_status')) is not int or root['http_status'] != 200 or root.get('robots_checked') is not True:
        raise Refusal('root receipt is not a robots-checked 200 response')
    if root.get('ownership_anchor_snapshot_id') != receipt.get('ownership_anchor_snapshot_id'):
        raise Refusal('root receipt ownership anchor differs from the claim')
    if (root.get('declared_host') != effective.hostname or root.get('source_url') != root['effective_url']
            or root.get('sha256') != hashlib.sha256(raw).hexdigest()):
        raise Refusal('root receipt host, source url or hash differs from its retained page')
    if root.get('declared_host') != receipt.get('declared_host'):
        raise Refusal('root receipt host differs from the claim host')
    if not legal_name_visible(raw, anchor.get('navn')):
        raise Refusal('legal name is not in a title, h1, footer, address or contact block of the chain root page')
    robots_failure(audit, root.get('robots_snapshot_id'), 'robots receipt of the destination',
                   'https://' + effective.hostname + '/robots.txt', root['effective_url'], effective.hostname)
    if root is not receipt:
        robots_failure(audit, receipt['robots_snapshot_id'], 'robots receipt of the claim page',
                       'https://' + receipt['declared_host'] + '/robots.txt', receipt['effective_url'], receipt['declared_host'])
    origin = split_url(root['requested_url'])[0]
    registry_id = root.get('registry_robots_snapshot_id')
    if not isinstance(registry_id, str):
        raise Refusal('registry robots receipt is absent')
    robots_failure(audit, registry_id, 'registry robots receipt', 'https://' + origin + '/robots.txt',
                   root['requested_url'], registry_host, chain_path='/robots.txt')
