"""Cross-domain redirects of the registry-declared website host.

The registry declares a host; that host may redirect to the company's real domain. A bounded,
permanent, https-only chain whose first cross-domain hop is issued by the registry host can
link the destination to the registry, but only when the destination page itself names the
exact legal subject. The chain never proves website ownership.
"""
import ipaddress
from urllib.parse import urlsplit

MAX_HOPS = 3  # matches the fetcher's redirect bound
PERMANENT = (301, 308)  # RFC 9110 15.4.2 and 15.4.9: a new permanent URI; 302/303/307 are temporary
CHAIN_PATHS = ('/', '/robots.txt')  # only fixed paths of the registry host may cross domains

# Destinations that are shared namespaces, group parents, social/directory pages, shorteners or
# parking pages. A match is a host or any subdomain of it. Not exhaustive: the exact legal name
# check on the destination page is the primary guard.
REDIRECT_DENYLIST = frozenset((
    'wixsite.com', 'wix.com', 'squarespace.com', 'myshopify.com', 'shopify.com', 'webflow.io', 'webflow.com',
    'wordpress.com', 'weebly.com', 'blogspot.com', 'github.io', 'netlify.app', 'vercel.app', 'pages.dev',
    'herokuapp.com', 'azurewebsites.net', 'onrender.com', 'godaddysites.com', 'business.site', 'canva.site',
    'carrd.co', 'notion.site', 'framer.website', 'strikingly.com', 'jimdosite.com',
    'facebook.com', 'fb.com', 'instagram.com', 'linkedin.com', 'lnkd.in', 'twitter.com', 'x.com', 'youtube.com',
    'tiktok.com', 'proff.no', 'gulesider.no', '1881.no', 'finn.no', 'brreg.no',
    'bit.ly', 't.co', 'tinyurl.com', 'goo.gl', 'ow.ly', 'buff.ly', 'cutt.ly', 'rebrand.ly', 'is.gd', 'shorturl.at',
    'sedoparking.com', 'parkingcrew.net', 'hugedomains.com', 'dan.com', 'afternic.com',
    'sparebank1.no', 'dnb.no', 'nordea.no', 'nordea.com', 'handelsbanken.no', 'danskebank.no', 'gjensidige.no',
    'storebrand.no', 'if.no', 'tryg.no', 'fremtind.no', 'eika.no', 'sbanken.no',
))

# Handwritten, conservative subset of multi-label public suffixes (no list is copied or fetched).
NORID_COUNTIES = ('aa', 'ah', 'bu', 'fm', 'hl', 'hm', 'jan-mayen', 'mr', 'nl', 'nt', 'of', 'ol', 'oslo', 'rl', 'sf',
                  'st', 'svalbard', 'tm', 'tr', 'va', 'vf')
SHARED_SUFFIXES = frozenset(
    ['fhs.no', 'folkebibl.no', 'fylkesbibl.no', 'gielda.no', 'herad.no', 'idrett.no', 'kommune.no', 'museum.no',
     'priv.no', 'suohkan.no', 'tjielte.no', 'uenorge.no', 'vgs.no', 'dep.no', 'mil.no', 'stat.no',
     'co.uk', 'org.uk', 'ac.uk', 'gov.uk', 'me.uk', 'ltd.uk', 'plc.uk', 'net.uk', 'sch.uk', 'com.au', 'net.au',
     'org.au', 'co.nz', 'co.jp', 'com.br', 'co.za', 'com.tr', 'co.in', 'com.cn', 'com.hk', 'com.sg', 'com.mx', 'co.il']
    + [county + '.no' for county in NORID_COUNTIES] + ['gs.' + county + '.no' for county in NORID_COUNTIES])
GENERIC_SECOND_LEVEL = frozenset(('co', 'com', 'org', 'net', 'gov', 'edu', 'ac', 'or', 'ne', 'go', 'ltd', 'plc', 'me', 'sch'))


def registrable_domain(host):
    """One label above the public suffix, or None when the host is a bare suffix or has no suffix."""
    labels = host.lower().split('.') if isinstance(host, str) and host else []
    if len(labels) < 2 or not all(labels):
        return None
    size = 1
    for count in (3, 2):
        if len(labels) >= count and '.'.join(labels[-count:]) in SHARED_SUFFIXES:
            size = count
            break
    else:
        if len(labels[-1]) == 2 and labels[-2] in GENERIC_SECOND_LEVEL:
            size = 2
    return '.'.join(labels[-(size + 1):]) if len(labels) > size else None


def denylisted(host):
    return any(host == domain or host.endswith('.' + domain) for domain in REDIRECT_DENYLIST)


def _public_host(host):
    if not host:  # IPv6 literals do not survive safe_url's rebuilt URL
        return False
    last = host.rsplit('.', 1)[-1]
    if last.isdigit() or last.startswith('0x'):  # 127.1, 0x7f.1 and similar short IPv4 forms
        return False
    try:
        ipaddress.ip_address(host.strip('[]'))
        return False
    except ValueError:
        return registrable_domain(host) is not None


def _check_destination(host):
    from .fetch import SourceUnavailable
    if not _public_host(host):
        raise SourceUnavailable('Redirect destination is not a public registrable host', 'blocked')
    if denylisted(host):
        raise SourceUnavailable('Redirect destination is a shared platform, group or shortener host', 'blocked')


def redirect_target(location, url, status, chain, allowed_hosts, registry_hosts, original):
    """Resolve one Location under the host scope, returning (target, scope for later hops).

    Without registry_hosts this is the plain same-host/www rule. With them, the first
    cross-domain hop is also allowed when the registry host itself issues a permanent
    redirect for its root (or robots.txt) to a public, unshared https host; later hops stay
    on that destination. Every refusal is 'blocked'.
    """
    from .fetch import SourceUnavailable, safe_url, website_hosts
    if registry_hosts is None:  # default: the plain same-host/www rule, exactly as before
        return safe_url(location, allowed_hosts), allowed_hosts
    target = safe_url(location)
    host = urlsplit(target).hostname
    crossed = registry_hosts is not None and any(
        urlsplit(hop['to']).hostname not in registry_hosts for hop in chain)
    if host in allowed_hosts:
        if crossed and status not in PERMANENT:
            raise SourceUnavailable('Temporary redirect cannot link a cross-domain chain', 'blocked')
        if crossed:  # the destination's www alias can be a bare suffix or a shared host (www.priv.no -> priv.no)
            _check_destination(host)
        return target, allowed_hosts
    scope = SourceUnavailable('Redirect or URL escapes the permitted host scope', 'blocked')
    start, issuer = urlsplit(original), urlsplit(url)  # both the first request and the issuing hop are fixed paths
    if (crossed or issuer.hostname not in registry_hosts
            or start.path not in CHAIN_PATHS or start.query or issuer.path not in CHAIN_PATHS or issuer.query
            or status not in PERMANENT):
        raise scope
    if any(hop['http_status'] not in PERMANENT for hop in chain):
        raise SourceUnavailable('Temporary redirect cannot link a cross-domain chain', 'blocked')
    _check_destination(host)
    # The destination's alias must also be acceptable; later hops re-check it.
    return target, set(allowed_hosts) | website_hosts(host)


def chain_reaches(requested_url, chain, effective_url, registry_hosts):
    """Re-verify a persisted receipt chain under the same rules the fetcher applied."""
    from .fetch import SourceUnavailable, safe_url
    try:
        if safe_url(requested_url) != requested_url or any(type(hop['http_status']) is not int for hop in chain):
            return False
        if (not isinstance(chain, list) or not 1 <= len(chain) <= MAX_HOPS or chain[0]['from'] != requested_url
                or urlsplit(requested_url).hostname not in registry_hosts):
            return False
        scope, seen = set(registry_hosts), []
        for index, hop in enumerate(chain):
            if index and hop['from'] != chain[index - 1]['to']:
                return False
            target, scope = redirect_target(hop['to'], hop['from'], hop['http_status'], seen, scope,
                                            registry_hosts, requested_url)
            if target != hop['to']:
                return False
            seen.append(hop)
        return chain[-1]['to'] == effective_url and urlsplit(effective_url).hostname not in registry_hosts
    except (SourceUnavailable, KeyError, TypeError, AttributeError):
        return False


CONTACT_TOKENS = ('contact', 'kontakt')
CONTACT_MAX_CHARS = 1500  # a contact block is small; wrappers around the whole page do not count


def _identity_block(node):
    if node['tag'] in ('title', 'h1', 'footer', 'address'):
        return True
    label = ((node['attrs'].get('id') or '') + ' ' + (node['attrs'].get('class') or '')).lower()
    return (node['tag'] not in ('html', 'body', 'main') and any(token in label for token in CONTACT_TOKENS)
            and len(node['text']) <= CONTACT_MAX_CHARS)


def names_legal_subject(raw, legal_name):
    """The exact legal name, as a whole word, in the title, an h1, a footer/address or a small contact block.

    Visible text only (scripts, hidden and quoted blocks excluded); a mention in body text, a news item
    or a reseller paragraph does not identify the site.
    """
    from .html_sources import Sections, names
    try:
        return any(names(node['text'], legal_name) for node in Sections(raw).nodes if _identity_block(node))
    except UnicodeDecodeError:
        return False


def registry_hosts_of(registry_url):
    from .fetch import SourceUnavailable, website_candidate, website_hosts
    try:
        return website_hosts(urlsplit(website_candidate(registry_url)).hostname)
    except (SourceUnavailable, ValueError, TypeError):
        return None


def page_links_to_registry(raw, receipt, legal_name, registry_url):
    """Acquisition-time test on a fetched page: verified chain plus the exact legal name."""
    hosts = registry_hosts_of(registry_url)
    return bool(hosts and receipt.get('redirect_chain') and legal_name
                and chain_reaches(receipt.get('requested_url', receipt['source_url']), receipt['redirect_chain'],
                                  receipt['effective_url'], hosts)
                and names_legal_subject(raw, legal_name))


def registry_redirect_link(store, subject, sid, receipt, legal_name, registry_url):
    """Whether a retained company page is registry-linked through its (or its anchor's) redirect chain."""
    from .snapshots import digest
    hosts = registry_hosts_of(registry_url)
    if not hosts or not legal_name or receipt['declared_host'] in hosts:
        return False
    root_sid = receipt.get('redirect_anchor_snapshot_id', sid)
    try:
        raw, root = store.open(root_sid)
        host = urlsplit(root['effective_url']).hostname
        return (root['organisation_number'] == subject and root['source_class'] == 'company_owned'
                and root['http_status'] == 200 and root.get('robots_checked') is True
                and root['sha256'] == digest(raw) and host == receipt['declared_host'] == root['declared_host']
                and root['ownership_anchor_snapshot_id'] == receipt['ownership_anchor_snapshot_id']
                and (root_sid == sid or not root.get('redirect_anchor_snapshot_id'))
                and chain_reaches(root['requested_url'], root['redirect_chain'], root['effective_url'], hosts)
                and names_legal_subject(raw, legal_name))
    except (OSError, ValueError, KeyError, TypeError):
        return False
