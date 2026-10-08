"""Breadth-first, supervised live acquisition using the local envelope contract."""
import time
import re
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, SimpleQueue
from collections import defaultdict
from urllib.parse import urlsplit

from .api_sources import ACCOUNTS, ENTITY, SUBUNITS, check_api, propose_api
from .batch import envelope
from .claims import claim_id, slot
from .contracts import load, loads, timestamp
from .extraction import Candidate, extract
from .evidence import EvidenceChecker
from .identity import legal_anchor
from .registry import acquire_batch
from .discovery import AnySearchDiscovery, BraveDiscovery, LegalNameDiscovery
from .html_sources import operator_proof
from .fetch import Budget, BudgetExceeded, Fetcher, SourceUnavailable, safe_url, website_candidate, website_hosts
from .planner import Planner, ROUTE_FAMILIES
from .roles import check_role, propose_roles
from .snapshots import SnapshotStore, digest
from .web_sources import check_web, locale_links, page_links, sitemap_links
from .nav_jobs import NavFeed, check_nav


def acquire_website(fetcher, subject, entity, discovery, max_pages):
    """Follow legal/contact leads before rejecting a site; bound all candidate pages."""
    pages, failures, seen, metadata_seen = [], [], set(), set()
    funnel = {'candidate_domains': 0, 'candidate_pages_retrieved': 0, 'candidate_identity_rejections': 0}
    declared = entity.get('hjemmeside')
    candidates = []
    if declared:
        try:
            candidates.append(website_candidate(declared))
        except SourceUnavailable as exc:
            failures.append({'reason': str(exc), 'availability': exc.availability})
    # Registry email is a retrieval hint, never website attribution. Accountants
    # and shared mail services must still fail the ordinary operator checker.
    email = entity.get('epostadresse')
    match = re.fullmatch(r'[^\s@]+@([A-Za-z0-9.-]+)', email) if isinstance(email, str) else None
    if match:
        host = match[1].lower()
        generic = {'gmail.com', 'hotmail.com', 'hotmail.no', 'outlook.com', 'outlook.no', 'live.com', 'live.no',
                   'yahoo.com', 'yahoo.no', 'icloud.com', 'proton.me', 'protonmail.com', 'online.no'}
        if host not in generic:
            try:
                lead = website_candidate(host)
                if lead not in candidates:
                    candidates.append(lead)
            except SourceUnavailable:
                pass

    def retrieve(url, hosts):
        if len(seen) >= max_pages or url in seen:
            return None
        seen.add(url)
        try:
            page = fetcher.get(url, hosts, robots=True)
            funnel['candidate_pages_retrieved'] += 1
            if 'html' not in page[1]['content_type'].lower():
                raise SourceUnavailable('Website candidate is not HTML', 'not_available')
            try:
                page[0].decode('utf-8')
            except UnicodeDecodeError:
                raise SourceUnavailable('Website candidate requires unsupported non-UTF-8 decoding', 'not_available') from None
            return page
        except SourceUnavailable as exc:
            failures.append({'url': url, 'reason': str(exc), 'availability': exc.availability})
            return None

    # One declared candidate first; search also runs when that lead cannot be
    # legally attributed. Transient candidate text never becomes evidence.
    for phase in range(2):
        if phase:
            if not discovery or len(seen) >= max_pages:
                break
            try:
                candidates = discovery.candidates(subject, entity)
            except SourceUnavailable as exc:
                failures.append({'reason': str(exc), 'availability': exc.availability})
                break
        for candidate in candidates:
            funnel['candidate_domains'] += 1
            root = retrieve(candidate, website_hosts(urlsplit(candidate).hostname))
            if root is None:
                continue
            local = [root]
            url = root[1]['effective_url']
            host = {urlsplit(url).hostname}
            links = page_links(root[0], url)
            locale_url = url
            owner = root if operator_proof(root[0], subject, entity['navn']) else None
            if owner is None:
                # Search can land on a foreign locale. Follow one explicitly
                # linked Norwegian alternate before spending pages on its terms.
                for link in locale_links(root[0], url)[:1]:
                    page = retrieve(link, host)
                    if page:
                        local.append(page)
                        locale_url = page[1]['effective_url']
                        links = page_links(page[0], page[1]['effective_url'])
                        if operator_proof(page[0], subject, entity['navn']):
                            owner = page
                if owner is not None:
                    identity_links = []
                else:
                    identity_links = [link for link in links if re.search(
                        r'legal|jurid|terms|vilk|imprint|kontakt|contact|about|om-oss', urlsplit(link).path, re.I)]
                for _ in range(2):
                    if not identity_links:
                        break
                    link = identity_links.pop(0)
                    page = retrieve(link, host)
                    if page:
                        local.append(page)
                        if operator_proof(page[0], subject, entity['navn']):
                            owner = page
                            break
                        identity_links = [child for child in page_links(page[0], page[1]['effective_url'])
                                          if child not in seen and re.search(r'legal|jurid|terms|vilk|imprint',
                                                                            urlsplit(child).path, re.I)] + identity_links
            if owner is None and len(seen) < max_pages and len(metadata_seen) < 2:
                # Some seller terms are absent from navigation but explicitly
                # listed in robots-advertised XML. Two metadata fetches total
                # per company, separate from the bounded HTML page attempts.
                prefix = urlsplit(locale_url).path.rsplit('/', 1)[0] + '/'
                try:
                    pending_maps = list(getattr(fetcher, 'advertised_sitemaps', lambda *a: [])(locale_url, host))
                    while pending_maps and len(metadata_seen) < 2 and owner is None:
                        map_url = pending_maps.pop(0)
                        if map_url in metadata_seen:
                            continue
                        metadata_seen.add(map_url)
                        raw, receipt = fetcher.get(map_url, host, robots=True)
                        kind, leads = sitemap_links(raw, receipt['effective_url'], prefix)
                        if kind == 'sitemapindex':
                            pending_maps = leads[:1] + pending_maps
                            continue
                        for link in leads:
                            page = retrieve(link, host)
                            if page:
                                local.append(page)
                                if operator_proof(page[0], subject, entity['navn']):
                                    owner = page
                                    break
                            if len(seen) >= max_pages:
                                break
                except (SourceUnavailable, ValueError) as exc:
                    failures.append({'url': locale_url, 'reason': 'Sitemap lead unavailable: ' + str(exc),
                                     'availability': getattr(exc, 'availability', 'not_available')})
            if owner is None:
                funnel['candidate_identity_rejections'] += 1
                failures.append({'url': url, 'reason': 'No exact legal operator proof', 'availability': 'ambiguous'})
                # A registry lead can still carry exact-identifier JSON-LD.
                if phase == 0:
                    pages.extend(local)
                continue
            proof = operator_proof(owner[0], subject, entity['navn'])
            prefix = (urlsplit(owner[1]['effective_url']).path.rsplit('/', 1)[0] + '/'
                      if proof['kind'] == 'seller_terms' else '/')
            scoped_home = 'https://' + next(iter(host)) + prefix
            # Persist ownership first, then independently check content pages.
            local = [owner] + [page for page in local if page is not owner
                              and urlsplit(page[1]['effective_url']).path.startswith(prefix)]
            content_links = [scoped_home] + links + page_links(owner[0], owner[1]['effective_url'])
            for link in dict.fromkeys(content_links):
                if not urlsplit(link).path.startswith(prefix):
                    continue
                page = retrieve(link, host)
                if page:
                    local.append(page)
            return local, failures, funnel
    return pages, failures, funnel


def unique_decisions(decisions):
    """Conflicting same-slot values abstain; duplicate evidence is not a vote."""
    grouped, rejected = defaultdict(list), []
    for decision in decisions:
        if decision['accepted']:
            grouped[slot(decision['claim'])].append(decision)
        else:
            rejected.append(decision)
    result = []
    for identity, group in grouped.items():
        if any(type(d['claim']['value']) is not type(group[0]['claim']['value']) or
               d['claim']['value'] != group[0]['claim']['value'] for d in group):
            result.append({'field': group[0]['field'], 'claim_id': identity, 'accepted': False,
                           'availability': 'ambiguous', 'reason': 'Conflicting source values for the same claim slot'})
        else:
            result.append(group[0])
    # Rejected candidates are audit entries, not duplicate terminal claim slots.
    accepted_slots = {slot(d.get('claim', d)) for d in result}
    for decision in rejected:
        if slot(decision) not in accepted_slots:
            result.append(decision)
            accepted_slots.add(slot(decision))
    return result



def covered_families(claims):
    # Registry URLs and registered activities are facts/leads, not verified external coverage.
    # Keep historical claim metadata compatible, but do not schedule from it.
    return {family for claim in claims
            if claim['availability'] == 'available' and claim['field'] not in ('declared_website', 'registered_activity')
            for family in [claim.get('family') or ('people' if claim['field'].startswith('registered_role:') else None)]
            if family is not None}


def verify_previous(store, prior, subject, checker=None):
    evidence = {e['id']: e for e in prior['evidence']}
    referenced = set()
    for claim in prior['claims'] + prior.get('history', []):
        if claim['availability'] != 'available':
            continue
        for ref in claim['evidence_ids']:
            referenced.add(ref)
            item = evidence[ref]
            if item['source_class'] == 'frozen_registry':
                decision = (checker or EvidenceChecker(store, [subject])).check(
                    Candidate(subject, claim['field'], claim['value'], item['snapshot_id']), subject)
            elif item['source_class'] == 'company_owned':
                decisions = check_web(store, subject, item['snapshot_id'], checker=checker)
                decision = next((d for d in decisions if slot(d['claim']) == slot(claim)), None)
            elif item['source_class'] == 'nav_jobs':
                decisions = check_nav(store, subject, item['snapshot_id'], checker=checker)
                decision = next((d for d in decisions if slot(d['claim']) == slot(claim)), None)
            elif item['source_class'] == 'brreg_roles_snapshot':
                decision = check_role(store, Candidate(subject, claim['field'], claim['value'],
                                                      item['snapshot_id'], item['locator']), subject)
            else:
                decision = check_api(store, Candidate(subject, claim['field'], claim['value'],
                                                     item['snapshot_id'], item['locator']), subject)
            if (not decision or not decision['accepted'] or decision['claim']['value'] != claim['value']
                    or any(decision['claim'].get(key) != claim.get(key)
                           for key in ('field', 'claim_id', 'scope', 'family', 'item_key', 'period'))
                    or decision['evidence'] != item):
                raise ValueError('Previous live claim failed source verification')
            if timestamp(claim['last_observed_at']) < timestamp(claim['first_observed_at']):
                raise ValueError('Previous observation times are reversed')
    if referenced != set(evidence):
        raise ValueError('Unreferenced prior evidence')


def worker(connection, job):
    from .resources import worker_memory_limit
    worker_memory_limit()
    store = SnapshotStore(job['store'])
    events = SimpleQueue()
    budget = Budget(job['config'], job['deadline'], events.put)
    pool = ThreadPoolExecutor(max_workers=job['config']['workers'], thread_name_prefix='shirushi-io')
    fetcher, planner = Fetcher(budget), Planner(job['config']['routing_policy'])
    discovery = ((AnySearchDiscovery if job['discovery'].get('provider') == 'anysearch' else BraveDiscovery)
                 (fetcher, job['discovery']) if job.get('discovery') else LegalNameDiscovery())
    nav = NavFeed(fetcher, cutoff=job.get('cutoff')) if 'nav_jobs' in job['config']['enabled_sources'] else None
    subjects, previous = job['subjects'], job['previous']
    checker = EvidenceChecker(store, subjects, job['deadline'])
    states = {s: {'decisions': [], 'attempts': [], 'entity': None, 'failure': None} for s in subjects}
    try:
        for subject, prior in previous.items():
            try:
                verify_previous(store, prior, subject, checker)
            except Exception as exc:
                connection.send(('invalid_previous', None, f'{type(exc).__name__}: {exc}'))
                return
            connection.send(('prior_verified', subject, prior))

        def flush_accounting():
            latest = None
            while True:
                try:
                    latest = events.get_nowait()
                except Empty:
                    break
            if latest is not None:
                connection.send(('accounting', None, latest))

        # Threads acquire bytes only. The collector owns state, snapshots, checks,
        # planner statistics and every supervisor Pipe publication.
        def acquire(subject, route, entity, employer_names=()):
            clock = time.monotonic()
            before = getattr(budget.local, 'requests', 0)
            cost_before = getattr(budget.local, 'cost', 0.0)
            pages, failures, error = [], [], None
            funnel = {'candidate_domains': 0, 'candidate_pages_retrieved': 0, 'candidate_identity_rejections': 0}
            try:
                if route == 'company_owned':
                    pages, failures, funnel = acquire_website(fetcher, subject, entity, discovery,
                                                              job['config']['max_pages_per_company'])
                    if not pages:
                        raise SourceUnavailable('No legally attributable website candidate', 'not_available')
                elif route == 'nav_jobs':
                    pages, failures = nav.for_company(subject, entity, employer_names)
                else:
                    url = (ENTITY + subject + '/roller' if route == 'brreg_roles' else
                           (ACCOUNTS if route == 'brreg_accounts' else SUBUNITS if route == 'brreg_subunits' else ENTITY) + subject)
                    pages.append(fetcher.get(url, {'data.brreg.no'}))
            except (BudgetExceeded, SourceUnavailable, ValueError, KeyError, TypeError, OSError) as exc:
                error = exc
            return {'pages': pages, 'page_failures': failures, 'error': error, 'funnel': funnel,
                    'requests': getattr(budget.local, 'requests', 0) - before,
                    'third_party_cost_usd': getattr(budget.local, 'cost', 0.0) - cost_before,
                    'runtime_ms': int((time.monotonic() - clock) * 1000)}

        available_pages = []
        def snapshot(subject, source, url, hosts, robots=False):
            if not available_pages:
                raise SourceUnavailable('No acquired page')
            raw, receipt = available_pages.pop(0)
            receipt = dict(receipt)
            robots_response = receipt.pop('robots_response', None)
            if robots_response:
                robots_raw, robots_receipt = robots_response
                receipt['robots_snapshot_id'] = store.save(robots_raw, dict(robots_receipt,
                    source_class='robots_policy', sha256=digest(robots_raw), access_policy='public-robots-policy'))
            safe_url(receipt['effective_url'], hosts)
            content_type = receipt['content_type'].lower()
            if (source == 'company_owned' and 'html' not in content_type) or (
                    source != 'company_owned' and 'json' not in content_type):
                raise SourceUnavailable('Unexpected source content type')
            metadata = dict(receipt, organisation_number=subject, source_class=source,
                             requested_url=receipt['source_url'], source_url=receipt['effective_url'],
                             snapshot_kind='brreg_roles_json' if source == 'brreg_roles_snapshot' else source,
                             sha256=digest(raw), access_policy='public-company-page-robots' if robots else 'brreg-open-data-nlod-2.0',
                             robots_checked=robots, declared_host=urlsplit(receipt['effective_url']).hostname,
                             ownership_anchor_snapshot_id=states[subject].get('entity_sid') if robots else None,
                             operator_snapshot_id=states[subject].get('operator_sid') if robots else None)
            if job.get('cutoff'):
                metadata['evaluation_cutoff'] = job['cutoff']
            if metadata['operator_snapshot_id'] is None:
                del metadata['operator_snapshot_id']
            sid = store.save(raw, metadata)
            return raw, sid

        def publish(subject, terminal=False):
            state = states[subject]
            decisions = unique_decisions(state['decisions'])
            present = {slot(d.get('claim', d)) for d in decisions}
            decisions.extend({'field': c['field'], 'claim_id': slot(c), 'accepted': False,
                              'withdrawn': c['field'] == 'job_posting' or c.get('scope') == 'nav_verified_employer',
                              'reason': 'current_active_posting_not_verified' if c['field'] == 'job_posting'
                                        or c.get('scope') == 'nav_verified_employer'
                                        else 'unobserved_in_current_sources'}
                             for c in (previous.get(subject) or {}).get('claims', [])
                             if slot(c) not in present and c['availability'] == 'available')
            prior = previous.get(subject)
            if prior:
                prior = dict(prior, claims=[c for c in prior['claims'] if not c['field'].startswith('coverage:')])
            result = envelope(subject, job['run_id'], job['started_at'], decisions, prior, state['failure'])
            covered = covered_families(result['claims'])
            result['opportunities'] = [{'family': family, 'status': 'covered' if family in covered else 'unknown',
                                       'reason': 'supported_source_fact' if family in covered else 'no_verified_fact',
                                       'scope': 'local_provisional_taxonomy'}
                                      for family in ('business_products', 'people', 'operating_locations',
                                                     'financials_history', 'website_owned_profiles', 'jobs_dated_activity')]
            for opportunity in result['opportunities']:
                if opportunity['status'] == 'unknown':
                    routes = [a for a in state['attempts'] if opportunity['family'] in ROUTE_FAMILIES.get(a['source'], set())]
                    availability = routes[-1].get('availability', 'not_available') if routes else 'failed'
                    result['claims'].append({'field': 'coverage:' + opportunity['family'], 'value': None,
                                             'availability': availability, 'reason': routes[-1].get('reason', 'No supported fact in checked source')
                                             if routes else 'Route not scheduled', 'evidence_ids': []})
            result['operations']['requests'] = sum(a['requests'] for a in state['attempts'])
            result['operations']['third_party_cost_usd'] = sum(a.get('third_party_cost_usd', 0) for a in state['attempts'])
            result['operations']['runtime_ms'] = sum(a['runtime_ms'] for a in state['attempts'])
            body = {'envelope': result, 'decisions': decisions, 'attempts': state['attempts']}
            flush_accounting()
            connection.send(('result' if terminal else 'checkpoint', subject, body))

        def attempt(subject, route, acquired):
            state = states[subject]
            available_pages[:] = acquired['pages']
            old_families = covered_families([d['claim'] for d in state['decisions'] if d['accepted']])
            initial = len(state['decisions'])
            report = {'source': route, 'status': 'checked'}
            if route == 'company_owned':
                report['funnel'] = dict(acquired['funnel'])
                if isinstance(discovery, (AnySearchDiscovery, LegalNameDiscovery)):
                    report['discovery'] = discovery.diagnostics.get(subject, [])
            if acquired['page_failures']:
                report['page_failures'] = acquired['page_failures']
            try:
                if not available_pages and acquired['error']:
                    raise acquired['error']
                if route == 'brreg_entity':
                    raw, sid = snapshot(subject, route, ENTITY + subject, {'data.brreg.no'})
                    body = loads(raw)
                    if body['organisasjonsnummer'] != subject or body['_links']['self']['href'] != ENTITY + subject:
                        raise SourceUnavailable('Entity identity mismatch', 'ambiguous')
                    proposals = propose_api(store, sid)
                    decisions = [check_api(store, c, subject) for c in proposals]
                    report['rejected_candidates'] = [{'field': d['field'], 'reason': d['reason']}
                        for d in decisions if not d['accepted']]
                    # Optional source-field rejection must not discard an exact
                    # legal identity or relax acceptance of the rejected field.
                    if not any(d['accepted'] and d['field'] == 'legal_name'
                               and d['claim']['value'].strip() for d in decisions):
                        raise SourceUnavailable('No verified legal company name', 'ambiguous')
                    decisions = [d if d['accepted'] else dict(d,
                        claim_id=claim_id(subject, d['field'], 'official_entity')) for d in decisions]
                    state['entity'] = body
                    state['entity_sid'] = sid
                    state['decisions'].extend(decisions)
                elif route == 'brreg_roles':
                    _, sid = snapshot(subject, 'brreg_roles_snapshot', ENTITY + subject + '/roller', {'data.brreg.no'})
                    state['decisions'].extend(dict(check_role(store, c, subject), family='people') for c in propose_roles(store, sid))
                elif route in ('brreg_accounts', 'brreg_subunits'):
                    url = (ACCOUNTS if route == 'brreg_accounts' else SUBUNITS) + subject
                    _, sid = snapshot(subject, route, url, {'data.brreg.no'})
                    state['decisions'].extend(check_api(store, c, subject) for c in propose_api(store, sid))
                elif route == 'nav_jobs':
                    report['feed_window'] = dict(nav.diagnostics)
                    report['matched_employer_sources'] = len(available_pages)
                    sid = None
                    for raw, receipt, bridge_raw, bridge_receipt in available_pages:
                        bridge = dict(bridge_receipt, organisation_number=subject, source_class='brreg_job_employer',
                                      sha256=digest(bridge_raw), access_policy='brreg-open-data-nlod-2.0')
                        bridge_sid = store.save(bridge_raw, bridge)
                        sid = store.save(raw, dict(receipt, organisation_number=subject, source_class='nav_jobs',
                            sha256=digest(raw), employer_snapshot_id=bridge_sid,
                            legal_identity_snapshot_id=state['entity_sid'],
                            **({'evaluation_cutoff': job['cutoff']} if job.get('cutoff') else {}),
                            access_policy='https://arbeidsplassen.nav.no/vilkar-api'))
                        state['decisions'].extend(check_nav(store, subject, sid, checker=checker))
                    available_pages.clear()
                else:
                    url = available_pages[0][1]['source_url']
                    raw, sid = snapshot(subject, route, url, website_hosts(urlsplit(url).hostname), robots=True)
                    root_host = urlsplit(store.open(sid)[1]['effective_url']).hostname
                    if operator_proof(raw, subject, state['entity']['navn']):
                        state['operator_sid'] = sid
                    try:
                        checked = check_web(store, subject, sid, checker=checker)
                        state['decisions'].extend(checked)
                        report.setdefault('pages', []).append({'source_url': url, 'snapshot_id': sid,
                            'content_sha256': digest(raw), 'effective_url': store.open(sid)[1]['effective_url'],
                            'identity_proof': bool(operator_proof(raw, subject, state['entity']['navn'])),
                            'supported_fields': sorted({d['field'] for d in checked})})
                    except ValueError as exc:
                        report.setdefault('page_failures', []).append({'url': url, 'reason': str(exc)})
                    while available_pages:
                        next_url = available_pages[0][1]['source_url']
                        child_raw, child = snapshot(subject, route, next_url, {root_host}, robots=True)
                        try:
                            checked = check_web(store, subject, child, checker=checker)
                            state['decisions'].extend(checked)
                            report.setdefault('pages', []).append({'source_url': next_url, 'snapshot_id': child,
                                'content_sha256': digest(child_raw), 'effective_url': store.open(child)[1]['effective_url'],
                                'identity_proof': bool(operator_proof(child_raw, subject, state['entity']['navn'])),
                                'supported_fields': sorted({d['field'] for d in checked})})
                        except ValueError as exc:
                            report.setdefault('page_failures', []).append({'url': next_url, 'reason': str(exc)})
                report['snapshot_id'] = sid
                if acquired['error']:
                    raise acquired['error']
            except BudgetExceeded as exc:
                state['failure'] = str(exc)
                report.update(status='failed', availability='failed', reason=str(exc))
                raise
            except (SourceUnavailable, ValueError, KeyError, TypeError, OSError) as exc:
                report.update(status='failed', availability=getattr(exc, 'availability', 'failed'), reason=str(exc))
                if route == 'brreg_entity':
                    state['failure'] = str(exc)
            finally:
                report.update(requests=acquired['requests'], runtime_ms=acquired['runtime_ms'],
                              third_party_cost_usd=acquired['third_party_cost_usd'])
                state['attempts'].append(report)
                new = state['decisions'][initial:]
                if route == 'company_owned':
                    checked = [d['claim'] for d in unique_decisions(new) if d['accepted']]
                    report['funnel'].update(supported_facts=len(checked),
                        verified_website=int(any(c['field'] == 'verified_website' for c in checked)),
                        supported_company_families=sorted(covered_families(checked)))
                if route in ROUTE_FAMILIES:
                    planner.observe(route, covered_families([d['claim'] for d in new if d['accepted']]) - old_families,
                                    len([d for d in unique_decisions(new) if d['accepted']]), acquired['requests'])
                publish(subject)

        def execute_round(routes):
            # Bound submitted futures and retained responses by the worker count.
            for offset in range(0, len(routes), job['config']['workers']):
                chunk = routes[offset:offset + job['config']['workers']]
                futures = [pool.submit(acquire, subject, route, states[subject]['entity'],
                           tuple(d['claim']['value']['name'] for d in states[subject]['decisions']
                                 if d['accepted'] and d['field'] == 'operating_location'
                                 and d['claim'].get('scope') == 'registered_subunit'))
                           for subject, route in chunk]
                exhausted = None
                for (subject, route), future in zip(chunk, futures):
                    while not future.done():
                        flush_accounting()
                        time.sleep(min(0.01, max(0, job['deadline'] - time.monotonic())))
                        if time.monotonic() >= job['deadline']:
                            budget.cancel()
                    try:
                        attempt(subject, route, future.result())
                    except BudgetExceeded as exc:
                        exhausted = exc
                        budget.cancel()
                if exhausted:
                    raise exhausted

        try:
            if job.get('registry'):
                ids = acquire_batch(job['registry'], load(job['registry_receipt']), subjects, store, job['deadline'])
                for subject in subjects:
                    state = states[subject]
                    try:
                        sid = ids[subject]
                        state['entity'] = legal_anchor(store, sid, subject, checker)
                        state['entity_sid'] = sid
                        state['decisions'].extend(checker.check(c, subject) for c in extract(store, sid))
                        state['attempts'].append({'source': 'frozen_registry', 'status': 'checked',
                            'snapshot_id': sid, 'requests': 0, 'runtime_ms': 0, 'third_party_cost_usd': 0})
                    except (ValueError, KeyError) as exc:
                        state['failure'] = 'Frozen identity unavailable: ' + str(exc)
                    publish(subject)
            else:
                execute_round([(subject, 'brreg_entity') for subject in subjects])
            pending = {s: [r for r in ROUTE_FAMILIES if r in job['config']['enabled_sources']]
                       if states[s]['entity'] is not None else [] for s in subjects}
            while any(pending.values()):
                routes = []
                for subject in subjects:
                    if pending[subject]:
                        covered = covered_families([d['claim'] for d in states[subject]['decisions'] if d['accepted']])
                        route = planner.choose(pending[subject], covered)
                        pending[subject].remove(route)
                        routes.append((subject, route))
                execute_round(routes)
        except BudgetExceeded as exc:
            for subject in subjects:
                states[subject]['failure'] = str(exc)
        for subject in subjects:
            publish(subject, terminal=True)
        flush_accounting()
        connection.send(('accounting', None, dict(budget.emit(), planner=planner.statistics,
                         configured_io_workers=job['config']['workers'])))
        connection.send(('done', None, None))
    except BaseException as exc:
        connection.send(('fatal', None, f'{type(exc).__name__}: {exc}'))
    finally:
        budget.cancel()
        pool.shutdown(wait=False, cancel_futures=True)
        connection.close()
