"""Breadth-first, supervised live acquisition using the local envelope contract."""
import time
from collections import defaultdict
from urllib.parse import urlsplit

from .api_sources import ACCOUNTS, ENTITY, SUBUNITS, check_api, propose_api
from .batch import envelope
from .claims import slot
from .contracts import loads, timestamp
from .extraction import Candidate
from .fetch import Budget, BudgetExceeded, Fetcher, SourceUnavailable, safe_url
from .planner import Planner, ROUTE_FAMILIES
from .roles import check_role, propose_roles
from .snapshots import SnapshotStore, digest
from .web_sources import check_web, page_links


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


def verify_previous(store, prior, subject):
    evidence = {e['id']: e for e in prior['evidence']}
    referenced = set()
    for claim in prior['claims'] + prior.get('history', []):
        if claim['availability'] != 'available':
            continue
        for ref in claim['evidence_ids']:
            referenced.add(ref)
            item = evidence[ref]
            if item['source_class'] == 'company_owned':
                decisions = check_web(store, subject, item['snapshot_id'])
                decision = next((d for d in decisions if slot(d['claim']) == slot(claim)), None)
            elif item['source_class'] == 'brreg_roles_snapshot':
                decision = check_role(store, Candidate(subject, claim['field'], claim['value'],
                                                      item['snapshot_id'], item['locator']), subject)
            else:
                decision = check_api(store, Candidate(subject, claim['field'], claim['value'],
                                                     item['snapshot_id'], item['locator']), subject)
            if (not decision or not decision['accepted'] or decision['claim']['value'] != claim['value']
                    or decision['claim']['scope'] != claim.get('scope') or decision['evidence'] != item):
                raise ValueError('Previous live claim failed source verification')
            if timestamp(claim['last_observed_at']) < timestamp(claim['first_observed_at']):
                raise ValueError('Previous observation times are reversed')
    if referenced != set(evidence):
        raise ValueError('Unreferenced prior evidence')


def worker(connection, job):
    store = SnapshotStore(job['store'])
    budget = Budget(job['config'], job['deadline'], lambda totals: connection.send(('accounting', None, totals)))
    fetcher, planner = Fetcher(budget), Planner(job['config']['routing_policy'])
    subjects, previous = job['subjects'], job['previous']
    states = {s: {'decisions': [], 'attempts': [], 'entity': None, 'failure': None} for s in subjects}
    try:
        for subject, prior in previous.items():
            try:
                verify_previous(store, prior, subject)
            except Exception as exc:
                connection.send(('invalid_previous', None, f'{type(exc).__name__}: {exc}'))
                return
            connection.send(('prior_verified', subject, prior))

        def snapshot(subject, source, url, hosts, robots=False):
            raw, receipt = fetcher.get(url, hosts, robots=robots)
            content_type = receipt['content_type'].lower()
            if (source == 'company_owned' and 'html' not in content_type) or (
                    source != 'company_owned' and 'json' not in content_type):
                raise SourceUnavailable('Unexpected source content type')
            sid = store.save(raw, dict(receipt, organisation_number=subject, source_class=source,
                             snapshot_kind='brreg_roles_json' if source == 'brreg_roles_snapshot' else source,
                             sha256=digest(raw), access_policy='public-company-page-robots' if robots else 'brreg-open-data-nlod-2.0',
                             robots_checked=robots, declared_host=urlsplit(url).hostname,
                             ownership_anchor_snapshot_id=states[subject].get('entity_sid') if robots else None))
            return raw, sid

        def publish(subject, terminal=False):
            state = states[subject]
            decisions = unique_decisions(state['decisions'])
            present = {slot(d.get('claim', d)) for d in decisions}
            decisions.extend({'field': c['field'], 'claim_id': slot(c), 'accepted': False,
                              'reason': 'unobserved_in_current_sources'}
                             for c in (previous.get(subject) or {}).get('claims', [])
                             if slot(c) not in present and c['availability'] == 'available')
            prior = previous.get(subject)
            if prior:
                prior = dict(prior, claims=[c for c in prior['claims'] if not c['field'].startswith('coverage:')])
            result = envelope(subject, job['run_id'], job['started_at'], decisions, prior, state['failure'])
            covered = {c.get('family') or ('people' if c['field'].startswith('registered_role:') else None)
                       for c in result['claims'] if c['availability'] == 'available'}
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
            result['operations']['runtime_ms'] = sum(a['runtime_ms'] for a in state['attempts'])
            body = {'envelope': result, 'decisions': decisions, 'attempts': state['attempts']}
            connection.send(('result' if terminal else 'checkpoint', subject, body))

        def attempt(subject, route):
            state, clock, before = states[subject], time.monotonic(), budget.requests
            old_families = {d.get('family') for d in state['decisions'] if d['accepted']}
            initial = len(state['decisions'])
            report = {'source': route, 'status': 'checked'}
            try:
                if route == 'brreg_entity':
                    raw, sid = snapshot(subject, route, ENTITY + subject, {'data.brreg.no'})
                    proposals = propose_api(store, sid)
                    decisions = [check_api(store, c, subject) for c in proposals]
                    if any(not d['accepted'] for d in decisions):
                        raise SourceUnavailable('Entity candidate failed evidence verification', 'ambiguous')
                    body = loads(raw)
                    if body['organisasjonsnummer'] != subject or body['_links']['self']['href'] != ENTITY + subject:
                        raise SourceUnavailable('Entity identity mismatch', 'ambiguous')
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
                else:
                    declared = state['entity'].get('hjemmeside')
                    if not declared:
                        raise SourceUnavailable('No official website discovery lead', 'not_available')
                    url = safe_url(declared if '://' in declared else 'https://' + declared)
                    raw, sid = snapshot(subject, route, url, {urlsplit(url).hostname}, robots=True)
                    state['decisions'].extend(check_web(store, subject, sid))
                    for link in page_links(raw, url)[:job['config']['max_pages_per_company'] - 1]:
                        try:
                            _, child = snapshot(subject, route, link, {urlsplit(url).hostname}, robots=True)
                            state['decisions'].extend(check_web(store, subject, child))
                        except SourceUnavailable as exc:
                            # Child failures do not invalidate already checked root facts.
                            report.setdefault('page_failures', []).append({'url': link, 'reason': str(exc),
                                                                          'availability': exc.availability})
                            continue
                report['snapshot_id'] = sid
            except BudgetExceeded as exc:
                state['failure'] = str(exc)
                report.update(status='failed', availability='failed', reason=str(exc))
                raise
            except (SourceUnavailable, ValueError, KeyError, TypeError, OSError) as exc:
                report.update(status='failed', availability=getattr(exc, 'availability', 'failed'), reason=str(exc))
                if route == 'brreg_entity':
                    state['failure'] = str(exc)
            finally:
                report.update(requests=budget.requests - before, runtime_ms=int((time.monotonic() - clock) * 1000))
                state['attempts'].append(report)
                new = state['decisions'][initial:]
                if route in ROUTE_FAMILIES:
                    planner.observe(route, {d.get('family') for d in new if d['accepted']} - old_families,
                                    len([d for d in unique_decisions(new) if d['accepted']]), budget.requests - before)
                publish(subject)

        try:
            # Anchor the entire supplied batch before spending on deeper sources.
            for subject in subjects:
                attempt(subject, 'brreg_entity')
            pending = {s: [r for r in ROUTE_FAMILIES if r in job['config']['enabled_sources']]
                       if states[s]['entity'] is not None else [] for s in subjects}
            while any(pending.values()):
                for subject in subjects:
                    if pending[subject]:
                        covered = {d.get('family') for d in states[subject]['decisions'] if d['accepted']}
                        route = planner.choose(pending[subject], covered)
                        pending[subject].remove(route)
                        attempt(subject, route)
        except BudgetExceeded as exc:
            for subject in subjects:
                states[subject]['failure'] = str(exc)
        for subject in subjects:
            publish(subject, terminal=True)
        connection.send(('accounting', None, dict(budget.emit(), planner=planner.statistics)))
        connection.send(('done', None, None))
    except BaseException as exc:
        connection.send(('fatal', None, f'{type(exc).__name__}: {exc}'))
    finally:
        connection.close()
