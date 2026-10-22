"""Company page assertions with separate subject and website attribution."""
import re
import xml.etree.ElementTree as ET
from datetime import date
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit

from .claims import claim_id
from .contracts import loads, timestamp
from .html_sources import catalogue_values, html_values, operator_proof
from .fetch import safe_url, website_candidate, website_hosts
from .redirects import registry_redirect_link
from .snapshots import digest
from .identity import legal_anchor

LEGAL_LINK = r'vilk|terms|conditions|betingelser|legal|jurid|imprint|privacy|personvern'
IDENTITY_LINK = LEGAL_LINK + r'|kontakt|contact|about|om-oss'


class Page(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.scripts, self.links, self.text, self.locales = [], [], [], []
        self.current = None
        self.feed(raw.decode('utf-8'))
        self.close()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and (attrs.get('type') or '').lower() == 'application/ld+json':
            self.current = ''
        if tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])
        language = (attrs.get('hreflang') or attrs.get('data-language') or attrs.get('title') or '').lower().replace('_', '-')
        if (tag in {'a', 'link'} and attrs.get('href')
                and re.fullmatch(r'(?:no|nb|nn)(?:-no)?', language)):
            self.locales.append(attrs['href'])

    def handle_data(self, data):
        if self.current is not None:
            self.current += data
        else:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.current is not None:
            self.scripts.append(self.current)
            self.current = None


def identified(node, subject):
    if not isinstance(node, dict):
        return False
    values = [node.get(k) for k in ('identifier', 'taxID', 'vatID')]
    for value in values:
        if isinstance(value, dict):
            value = value.get('value')
        if isinstance(value, str) and re.fullmatch(r'(?:NO\s*)?' + subject + r'(?:\s*MVA)?', value.replace(' ', ''), re.I):
            return True
    return False


def nodes(value, path=()):
    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from nodes(item, path + (index,))
    elif isinstance(value, dict):
        yield path, value
        if '@graph' in value:
            yield from nodes(value['@graph'], path + ('@graph',))


def page_values(raw, subject, url, cutoff=None):
    cutoff = cutoff or date.today()
    page = Page(raw)
    # Only explicit machine-readable legal identifiers authorize publication.
    for script_index, text in enumerate(page.scripts):
        try:
            parsed = loads(text)
        except ValueError:
            continue
        for path, node in nodes(parsed):
            kind = node.get('@type')
            kinds = kind if isinstance(kind, list) else [kind]
            if 'Organization' in kinds and identified(node, subject):
                value = node.get('description')
                if isinstance(value, str) and value.strip():
                    yield 'business_description', value, 'business_products', None, script_index, path
                declared = node.get('url')
                if isinstance(declared, str):
                    try:
                        declared = safe_url(declared, {urlsplit(url).hostname})
                    except ValueError:
                        continue
                    yield 'verified_website', declared, 'website_owned_profiles', None, script_index, path
            elif 'JobPosting' in kinds and identified(node.get('hiringOrganization'), subject):
                title, posted = node.get('title'), node.get('datePosted')
                try:
                    posted_date = date.fromisoformat(posted[:10])
                    end = node.get('validThrough')
                    if posted_date > cutoff or (end and date.fromisoformat(end[:10]) < cutoff):
                        continue
                except (ValueError, TypeError):
                    continue
                identity = node.get('identifier')
                if isinstance(identity, dict):
                    identity = identity.get('value')
                if not isinstance(title, str) or not title.strip() or not isinstance(identity, str) or not identity.strip():
                    continue
                yield ('job_posting', {'title': title, 'date_posted': posted, 'posting_id': identity,
                                      'valid_through': end, 'source_url': url},
                       'jobs_dated_activity', identity, script_index, path)
            elif any(k in ('NewsArticle', 'Article') for k in kinds) and identified(node.get('about'), subject):
                title, published = node.get('headline'), node.get('datePublished')
                try:
                    if date.fromisoformat(published[:10]) > cutoff:
                        continue
                except (ValueError, TypeError):
                    continue
                if isinstance(title, str) and title.strip():
                    yield ('public_activity', {'headline': title, 'published_at': published, 'source_url': url},
                           'jobs_dated_activity', url, script_index, path)


def check_web(store, subject, sid, checker=None):
    raw, receipt = store.open(sid)
    if (receipt['organisation_number'] != subject or receipt['source_class'] != 'company_owned'
            or receipt['http_status'] != 200 or receipt['sha256'] != digest(raw)
            or receipt.get('robots_checked') is not True
            or receipt.get('declared_host') != urlsplit(receipt['effective_url']).hostname):
        raise ValueError('Company page receipt mismatch')
    anchor = legal_anchor(store, receipt['ownership_anchor_snapshot_id'], subject, checker)
    declared = anchor.get('hjemmeside', '')
    try:
        declared = website_candidate(declared)
    except ValueError:
        declared = ''
    host = urlsplit(declared).hostname
    registry_host = host is not None and receipt['declared_host'] in website_hosts(host)
    redirect_only = False
    if host is not None and not registry_host:
        # The registry host's permanent redirect plus the exact legal name on the destination (redirects.py).
        registry_host = redirect_only = registry_redirect_link(store, subject, sid, receipt, anchor.get('navn', ''), declared)
    ownership_sid = receipt.get('operator_snapshot_id', sid)
    ownership_raw, ownership_receipt = store.open(ownership_sid)
    legal_name = anchor.get('navn', '')
    proof = operator_proof(ownership_raw, subject, legal_name, anchor.get('hjemmeside', ''),
                           ownership_receipt['effective_url'])
    if proof and (ownership_receipt.get('organisation_number') != subject
                  or ownership_receipt.get('source_class') != 'company_owned'
                  or ownership_receipt.get('robots_checked') is not True
                  or ownership_receipt.get('http_status') != 200
                  or ownership_receipt.get('sha256') != digest(ownership_raw)
                  or urlsplit(ownership_receipt['effective_url']).hostname != receipt['declared_host']
                  or ownership_receipt.get('ownership_anchor_snapshot_id') != receipt['ownership_anchor_snapshot_id']):
        raise ValueError('Website legal operator proof mismatch')
    seller_path = None
    if proof and proof['kind'] == 'seller_terms':
        seller_path = urlsplit(ownership_receipt['effective_url']).path.rsplit('/', 1)[0] + '/'
        if not urlsplit(receipt['effective_url']).path.startswith(seller_path):
            raise ValueError('Company page escapes the verified seller locale/path')
    if not registry_host and not proof:
        raise ValueError('Website discovery is not anchored to this company')
    cutoff = timestamp(receipt.get('evaluation_cutoff', receipt['retrieved_at'])).date()
    if cutoff > timestamp(receipt['retrieved_at']).date():
        raise ValueError('Evaluation cutoff is after acquisition')
    decisions = []
    scripts = Page(raw).scripts
    for field, value, family, item, script, path in page_values(raw, subject, receipt['effective_url'], cutoff):
        if field == 'verified_website' and redirect_only and not proof:
            continue  # a redirect link never establishes website ownership
        identity = claim_id(subject, field, 'company_owned_structured', item)
        eid = sid + ':' + identity
        claim = {'claim_id': identity, 'field': field, 'value': value, 'scope': 'company_owned_structured',
                 'family': family, 'item_key': item, 'period': None,
                 'availability': 'available', 'evidence_ids': [eid], 'freshness': 'live_source'}
        evidence = {'id': eid, 'snapshot_id': sid, 'source_url': receipt['effective_url'],
                    'source_class': 'company_owned', 'source_origin': receipt['source_origin'],
                    'retrieved_at': receipt['retrieved_at'], 'content_sha256': digest(raw),
                    'claim_span': scripts[script], 'locator': {'script_index': script, 'node_path': list(path)},
                    'extraction_method': 'exact_identifier_jsonld_v1'}
        decisions.append({'field': field, 'family': family, 'accepted': True, 'claim': claim, 'evidence': evidence})
    if registry_host and not proof and not any(d['field'] == 'verified_website' for d in decisions):
        # Registry-declared homepage corroborated by the registry row itself (website_sources.py).
        from .website_sources import website_decision
        website = website_decision(raw, receipt, sid, subject, anchor)
        if website:
            decisions.append(website)
    if registry_host:
        from .profile_sources import contact_proof, schema_context
        for script_index, text in enumerate(scripts):
            try:
                parsed = loads(text)
            except ValueError:
                continue
            for path, node in nodes(parsed):
                if not schema_context(parsed, path):
                    continue
                description = node.get('description')
                if not isinstance(description, str) or not 10 <= len(description.strip()) <= 2000:
                    continue
                identity = contact_proof(raw, node, subject, legal_name, receipt['effective_url'])
                if identity is None:
                    continue
                cid = claim_id(subject, 'business_description', 'registry_linked_structured')
                eid = sid + ':' + cid
                claim = {'claim_id': cid, 'field': 'business_description', 'value': description,
                    'scope': 'registry_linked_structured', 'family': 'business_products', 'item_key': None,
                    'period': None, 'availability': 'available', 'evidence_ids': [eid], 'freshness': 'live_source'}
                evidence = {'id': eid, 'snapshot_id': sid, 'source_url': receipt['effective_url'],
                    'source_class': 'company_owned', 'source_origin': receipt['source_origin'],
                    'retrieved_at': receipt['retrieved_at'], 'content_sha256': digest(raw), 'claim_span': text,
                    'support_spans': {'legal_identity': raw.decode('utf-8')[identity['start']:identity['end']]},
                    'locator': {'script_index': script_index, 'node_path': list(path),
                        'identity_html_start': identity['start'], 'identity_html_end': identity['end']},
                    'extraction_method': 'footer_bound_organization_jsonld_v1'}
                decisions.append({'field': 'business_description', 'family': 'business_products',
                                  'accepted': True, 'claim': claim, 'evidence': evidence})
    if proof or registry_host:
        # Registry linkage authorizes checking named assertions, not ownership.
        values = list(html_values(raw, subject, legal_name, receipt['effective_url'], cutoff))
        if registry_host:
            from .article_sources import article_values
            values.extend(article_values(raw, subject, legal_name, receipt['effective_url'], cutoff))
        scope = 'company_owned_html' if proof else 'registry_linked_html'
        method = 'explicit_subject_html_v1' if proof else 'registry_linked_subject_html_v1'
        if proof and ownership_sid == sid:
            source = raw.decode('utf-8')
            values.insert(0, ('verified_website', 'https://' + receipt['declared_host'] + (seller_path or '/'),
                             'website_owned_profiles', None, source[proof['start']:proof['end']],
                             {'html_start': proof['start'], 'html_end': proof['end'], 'legal_name': legal_name,
                              'operator': True}))
        for field, value, family, item, span, locator in values:
            identity = claim_id(subject, field, scope, item)
            eid = sid + ':' + identity
            claim = {'claim_id': identity, 'field': field, 'value': value, 'scope': scope,
                     'family': family, 'item_key': item, 'period': None, 'availability': 'available',
                     'evidence_ids': [eid], 'freshness': 'live_source'}
            evidence = {'id': eid, 'snapshot_id': sid, 'source_url': receipt['effective_url'],
                        'source_class': 'company_owned', 'source_origin': receipt['source_origin'],
                        'retrieved_at': receipt['retrieved_at'], 'content_sha256': digest(raw),
                        'claim_span': span, 'locator': locator, 'extraction_method': method}
            decisions.append({'field': field, 'family': family, 'accepted': True, 'claim': claim, 'evidence': evidence})
        if seller_path:
            for field, value, family, item, span, locator in catalogue_values(raw, receipt['effective_url']):
                if not urlsplit(value['source_url']).path.startswith(seller_path):
                    continue
                identity = claim_id(subject, field, 'company_owned_catalogue', item)
                eid = sid + ':' + identity
                claim = {'claim_id': identity, 'field': field, 'value': value, 'scope': 'company_owned_catalogue',
                         'family': family, 'item_key': item, 'period': None, 'availability': 'available', 'evidence_ids': [eid]}
                evidence = {'id': eid, 'snapshot_id': sid, 'source_url': receipt['effective_url'],
                            'source_class': 'company_owned', 'source_origin': receipt['source_origin'],
                            'retrieved_at': receipt['retrieved_at'], 'content_sha256': digest(raw),
                            'claim_span': span, 'locator': locator, 'extraction_method': 'scoped_catalogue_html_v2'}
                decisions.append({'field': field, 'family': family, 'accepted': True, 'claim': claim, 'evidence': evidence})
    if registry_host:
        from .content_sources import definition_values, section_values, post_values, statement_values
        additions = []
        if not any(d['family'] == 'business_products' for d in decisions):
            sections = list(section_values(raw, subject, legal_name))
            if sections:
                additions.extend(('product_service', value, 'business_products', digest(value.encode()), span, loc, support,
                                  'bounded_company_section_v1')
                    for value, span, loc, support in sections)
            else:
                definitions = list(definition_values(raw, subject, legal_name))
                additions.extend(('business_description', value, 'business_products', None, span, loc, support,
                                  'named_company_definition_v1')
                    for value, span, loc, support in definitions)
                if not definitions:
                    additions.extend((field, value, 'business_products', None if field == 'business_description' else digest(value.encode()),
                                      span, loc, support, 'registry_linked_business_statement_v1')
                        for field, value, span, loc, support in statement_values(raw, subject, legal_name, receipt['effective_url']))
        additions.extend(('public_activity', {'statement': text, 'published_at': published,
            'source_url': receipt['effective_url']}, 'jobs_dated_activity', digest((text + '\n' + published).encode()),
            span, loc, {}, 'dated_post_headline_v1')
            for text, published, span, loc in post_values(raw, subject, legal_name, cutoff))
        for field, value, family, key, span, loc, support, method in additions:
            cid = claim_id(subject, field, 'registry_linked_html', key)
            eid = sid + ':' + cid
            claim = {'claim_id': cid, 'field': field, 'value': value, 'scope': 'registry_linked_html',
                'family': family, 'item_key': key, 'period': None, 'availability': 'available',
                'evidence_ids': [eid], 'freshness': 'live_source'}
            evidence = {'id': eid, 'snapshot_id': sid, 'source_url': receipt['effective_url'],
                'source_class': 'company_owned', 'source_origin': receipt['source_origin'],
                'retrieved_at': receipt['retrieved_at'], 'content_sha256': digest(raw), 'claim_span': span,
                'locator': loc, 'support_spans': support, 'extraction_method': method}
            decisions.append({'field': field, 'family': family, 'accepted': True, 'claim': claim, 'evidence': evidence})
    # Company-owned profile links from pages already anchored above (unanchored pages raised earlier).
    from .social_sources import social_values, METHOD as SOCIAL_METHOD
    social_scope = 'company_owned_html' if proof else 'registry_linked_html'
    for field, value, span, loc, support in social_values(raw, subject, legal_name, receipt['effective_url']):
        cid = claim_id(subject, field, social_scope, value)
        eid = sid + ':' + cid
        claim = {'claim_id': cid, 'field': field, 'value': value, 'scope': social_scope,
                 'family': 'website_owned_profiles', 'item_key': value, 'period': None, 'availability': 'available',
                 'evidence_ids': [eid], 'freshness': 'live_source'}
        evidence = {'id': eid, 'snapshot_id': sid, 'source_url': receipt['effective_url'],
                    'source_class': 'company_owned', 'source_origin': receipt['source_origin'],
                    'retrieved_at': receipt['retrieved_at'], 'content_sha256': digest(raw), 'claim_span': span,
                    'locator': loc, 'support_spans': support, 'extraction_method': SOCIAL_METHOD}
        decisions.append({'field': field, 'family': 'website_owned_profiles', 'accepted': True,
                          'claim': claim, 'evidence': evidence})
    if any(d['field'] == 'verified_website' and d.get('accepted') for d in decisions):
        from .careers_sources import METHOD as CAREERS_METHOD, ROLE_METHOD, hiring_values, role_links
        from .news_sources import METHOD as NEWS_METHOD, news_values
        page_scope = 'company_owned_html' if proof else 'registry_linked_html'
        page_url = receipt['effective_url']
        for method, values in ((CAREERS_METHOD, hiring_values(raw, page_url)),
                               (ROLE_METHOD, role_links(raw, page_url)),
                               (NEWS_METHOD, news_values(raw, page_url))):
            for field, value, span, loc, support in values:
                item = value if isinstance(value, str) else digest(
                    (value['headline'] + '\n' + value['published_at'] + '\n' + str(loc.get('html_start'))).encode())
                cid = claim_id(subject, field, page_scope, item)
                eid = sid + ':' + cid
                claim = {'claim_id': cid, 'field': field, 'value': value, 'scope': page_scope,
                         'family': 'jobs_dated_activity', 'item_key': item, 'period': None,
                         'availability': 'available', 'evidence_ids': [eid], 'freshness': 'live_source'}
                evidence = {'id': eid, 'snapshot_id': sid, 'source_url': page_url,
                            'source_class': 'company_owned', 'source_origin': receipt['source_origin'],
                            'retrieved_at': receipt['retrieved_at'], 'content_sha256': digest(raw),
                            'claim_span': span, 'locator': loc, 'support_spans': support,
                            'extraction_method': method}
                decisions.append({'field': field, 'family': 'jobs_dated_activity', 'accepted': True,
                                  'claim': claim, 'evidence': evidence})
    return decisions


def locale_links(raw, url):
    """Observed Norwegian alternates are leads, never legal ownership proof."""
    result = []
    for link in Page(raw).locales:
        try:
            candidate = safe_url(urljoin(url, link), {urlsplit(url).hostname})
        except ValueError:
            continue
        if candidate != url and candidate not in result:
            result.append(candidate)
    return result


def sitemap_links(raw, url, prefix):
    """Same-host observed XML URLs in the selected locale; never ownership."""
    if len(raw) > 2097152 or re.search(br'<!\s*(?:DOCTYPE|ENTITY)', raw, re.I):
        raise ValueError('Unsafe or oversized sitemap')
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise ValueError('Invalid sitemap XML') from None
    kind = root.tag.rsplit('}', 1)[-1]
    if kind not in ('sitemapindex', 'urlset'):
        raise ValueError('Unknown sitemap format')
    result = []
    for index, element in enumerate(root.iter()):
        if index >= 15000:
            break
        if element.tag.rsplit('}', 1)[-1] != 'loc':
            continue
        try:
            candidate = safe_url(element.text, {urlsplit(url).hostname})
        except ValueError:
            continue
        if urlsplit(candidate).path.startswith(prefix) and candidate not in result:
            result.append(candidate)
    if kind == 'urlset':
        result = [u for u in result if re.search(IDENTITY_LINK, urlsplit(u).path, re.I)]
        result.sort(key=lambda u: not bool(re.search(r'vilk|terms|conditions|betingelser', urlsplit(u).path, re.I)))
    return kind, result


# Stems are matched in the path and query, never the host: a company called
# "...service.no" would otherwise make every link a lead. "hvilken" ("which") is
# not a terms page, but compounds such as "salgsvilkar" still are.
LEGAL_LEAD = LEGAL_LINK.replace('vilk', r'(?<!h)vilk')
IDENTITY_LEAD = LEGAL_LEAD + IDENTITY_LINK[len(LEGAL_LINK):]
PRODUCT_LINK = r'produkt|product|service|tjenest|(?<![a-z])pris(?:er|liste)?(?![a-z])'
SHOWCASE_LINK = r'prosjekt|referanse'
CAREER_LINK = r'job|career|karriere|stilling|ledig|rekrutter'
NEWS_LINK = r'news|nyhet|siste-nytt|^/nytt/?$|press|aktuelt|blog'


def page_key(url):
    """Identity of a page for budgeting: www alias, trailing slash and fragment never make a new page."""
    parts = urlsplit(url)
    return (parts.hostname or '').removeprefix('www.'), unquote(parts.path).rstrip('/'), parts.query


def lead_target(link):
    parts = urlsplit(link)
    return (parts.path + '?' + parts.query if parts.query else parts.path).lower()


def page_links(raw, url):
    result, keys = [], {page_key(url)}
    for link in Page(raw).links:
        candidate = urljoin(url, link)
        if not re.search('|'.join((IDENTITY_LEAD, PRODUCT_LINK, SHOWCASE_LINK, CAREER_LINK, NEWS_LINK, 'omoss')),
                         lead_target(candidate), re.I):
            continue
        try:
            candidate = safe_url(candidate, {urlsplit(url).hostname})
        except ValueError:
            continue
        if page_key(candidate) not in keys:
            keys.add(page_key(candidate))
            result.append(candidate)
    # Identity evidence first, then content, never DOM navigation order.
    def priority(link):
        target = lead_target(link)
        return (0 if re.search(LEGAL_LEAD, target) else
                1 if re.search(PRODUCT_LINK, target) else
                2 if re.search('|'.join((SHOWCASE_LINK, CAREER_LINK, NEWS_LINK)), target) else 3)
    return sorted(result, key=priority)


def content_links(links):
    """After identity proof, share the page budget across observed attributes."""
    groups, showcase, keys = [[], [], [], []], [], set()
    for link in links:
        if page_key(link) in keys:
            continue
        keys.add(page_key(link))
        target = lead_target(link)
        group = (0 if re.search(PRODUCT_LINK, target) else
                 1 if re.search(CAREER_LINK, target) else
                 2 if re.search(NEWS_LINK, target) else 3)
        if group == 3 and re.search(SHOWCASE_LINK, target):
            showcase.append(link)
        else:
            groups[group].append(link)
    # Projects and references describe the offer but rank after named products.
    groups[0].extend(showcase)
    # One product, careers and activity opportunity before deeper catalogues.
    # Links remain untrusted. The ordinary ownership/content checks still apply.
    return [group[index] for index in range(max((len(g) for g in groups), default=0))
            for group in groups if index < len(group)]
