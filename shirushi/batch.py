"""Supervised offline batch execution with ordered, failure-safe terminal slots."""
import multiprocessing
import time
from collections import Counter
from datetime import datetime, timezone

from .contracts import load, validate_envelopes
from .evidence import EvidenceChecker, SPECIFICATIONS
from .extraction import extract
from .refresh import merge
from .registry import acquire_batch
from .roles import acquire_role, propose_roles
from .snapshots import SnapshotStore


def now():
    return datetime.now(timezone.utc).isoformat()


def failure_decisions(previous, reason):
    fields = list(SPECIFICATIONS)
    fields.extend(c['field'] for c in (previous or {}).get('claims', []) if c['field'] not in fields)
    return [{'accepted': False, 'field': field, 'reason': reason} for field in fields]


def envelope(subject, run_id, started, decisions, previous=None, error=None, runtime_ms=0):
    result = dict(merge(previous, decisions, started), organisation_number=subject,
                  run={'run_id': run_id, 'started_at': started, 'completed_at': now(),
                       'terminal_status': 'failed' if error else 'completed'},
                  errors=[{'stage': 'batch_or_source', 'reason': error}] if error else [],
                  operations={'requests': 0, 'runtime_ms': runtime_ms, 'third_party_cost_usd': 0})
    roles = [c for c in result['claims'] if c['field'].startswith('registered_role:') and c['availability'] == 'available']
    result['opportunities'] = [{'family': family, 'status': 'covered' if family == 'people' and roles else 'unknown',
                                'reason': 'supported_registered_roles' if family == 'people' and roles
                                else 'route_not_implemented' if family != 'people' else 'no_supported_role_in_saved_source',
                                'scope': 'local_provisional_taxonomy'}
                               for family in ('business_products', 'people', 'operating_locations',
                                              'financials_history', 'website_owned_profiles', 'jobs_dated_activity')]
    return result


def worker(connection, job):
    """One CPU worker shares proof caches. The supervisor owns the wall deadline."""
    try:
        from .resources import worker_memory_limit
        worker_memory_limit()
        subjects = job['subjects']
        store = SnapshotStore(job['store'])
        checker = EvidenceChecker(store, subjects, job['deadline'])
        previous = job['previous']
        # Prior values become fallback support only after source verification.
        for subject, prior in previous.items():
            try:
                checker.verify_previous(prior, subject)
            except Exception as exc:
                connection.send(('invalid_previous', None, f'{type(exc).__name__}: {exc}'))
                return
            connection.send(('prior_verified', subject, prior))
        archive_error = None
        try:
            snapshot_ids = acquire_batch(job['registry'], load(job['registry_receipt']), subjects, store, job['deadline'])
        except Exception as exc:
            archive_error, snapshot_ids = f'{type(exc).__name__}: {exc}', {}
        sources = {item['organisation_number']: item for item in job['sources']}
        for subject in subjects:
            clock = time.monotonic()
            prior = previous.get(subject)
            attempts = []
            failure = None
            try:
                if time.monotonic() >= job['deadline']:
                    raise TimeoutError('Batch scheduling deadline reached')
                if archive_error or subject not in snapshot_ids:
                    raise ValueError(archive_error or 'Requested subject absent from frozen registry')
                decisions = [checker.check(candidate, subject) for candidate in extract(store, snapshot_ids[subject])]
                attempts.append({'source': 'frozen_registry', 'status': 'checked', 'snapshot_id': snapshot_ids[subject]})
                if 'brreg_roles_snapshot' in job['enabled_sources']:
                    try:
                        if subject not in sources:
                            raise ValueError('No saved role receipt for requested company')
                        sid = acquire_role(sources[subject], job['source_manifest'], store, job['max_response_bytes'])
                        proposals = propose_roles(store, sid)
                        counts = Counter(c.field for c in proposals)
                        for candidate in proposals:
                            if counts[candidate.field] > 1:
                                decisions.append({'accepted': False, 'field': candidate.field,
                                                  'reason': 'Ambiguous duplicate registered role identity'})
                            else:
                                decisions.append(checker.check(candidate, subject))
                        attempts.append({'source': 'brreg_roles_snapshot', 'status': 'checked', 'snapshot_id': sid,
                                         'candidate_count': len(proposals)})
                    except Exception as exc:
                        failure = f'Role source failure: {type(exc).__name__}: {exc}'
                        attempts.append({'source': 'brreg_roles_snapshot', 'status': 'failed', 'reason': failure})
                present = {d['field'] for d in decisions}
                # A changed/missing listing never proves that an old role ended.
                decisions.extend({'accepted': False, 'field': c['field'], 'reason': 'role_unobserved_in_current_snapshot'}
                                 for c in (prior or {}).get('claims', []) if c['field'] not in present)
                bad = [d for d in decisions if not d['accepted'] and d['reason'] not in
                       ('absent_in_frozen_row', 'role_unobserved_in_current_snapshot')]
                if bad and failure is None:
                    failure = 'One or more evidence decisions failed'
            except Exception as exc:
                failure = f'{type(exc).__name__}: {exc}'
                decisions = failure_decisions(prior, 'source_failure: ' + failure)
                attempts.append({'source': 'frozen_registry', 'status': 'failed', 'reason': failure})
            result = envelope(subject, job['run_id'], job['started_at'], decisions, prior, failure,
                              int((time.monotonic() - clock) * 1000))
            connection.send(('result', subject, {'envelope': result, 'decisions': decisions, 'attempts': attempts}))
        connection.send(('done', None, None))
    except BaseException as exc:
        connection.send(('fatal', None, f'{type(exc).__name__}: {exc}'))
    finally:
        connection.close()


def run_supervised(job, contract, target=worker):
    """Preserve input order regardless of checkpoint order; terminate blocked work."""
    context = multiprocessing.get_context('spawn')
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=target, args=(send, job), daemon=True)
    slots, priors, reports, terminals = {}, {}, {}, set()
    reason = 'Worker exited before completing the batch'
    complete = False
    invalid_previous = False
    accounting = {'requests': 0, 'response_bytes': 0, 'third_party_cost_usd': 0}
    process.start()
    send.close()
    try:
        while time.monotonic() < job['deadline']:
            remaining = job['deadline'] - time.monotonic()
            try:
                ready = receive.poll(min(0.05, max(0, remaining)))
            except (EOFError, OSError):
                break
            if not ready:
                if not process.is_alive():
                    break
                continue
            try:
                kind, subject, body = receive.recv()
            except (EOFError, OSError):
                break
            if kind == 'done':
                complete = True
                break
            if kind == 'fatal':
                reason = 'Worker failure: ' + body
                break
            if kind == 'invalid_previous':
                invalid_previous, reason = True, body
                break
            if kind == 'accounting':
                accounting = body
                continue
            if subject not in job['subjects']:
                reason = 'Worker emitted an unrequested identity'
                break
            if kind == 'prior_verified':
                priors[subject] = body
            elif kind in ('result', 'checkpoint'):
                if subject in terminals:
                    reason = 'Worker emitted a duplicate terminal result'
                    break
                errors = validate_envelopes([{'organisation_number': subject}], [body['envelope']], contract)
                if errors:
                    reason = 'Worker result failed contract: ' + '; '.join(errors)
                    break
                slots[subject], reports[subject] = body['envelope'], body
                if kind == 'result':
                    terminals.add(subject)
            else:
                reason = 'Unknown worker checkpoint'
                break
        else:
            reason = 'Wall-time scheduling budget exhausted'
    finally:
        if complete:
            process.join(timeout=min(1.0, max(0, job['deadline'] - time.monotonic())))
        if process.is_alive():
            process.terminate()
        process.join(timeout=0.2)
        if process.is_alive():
            process.kill()
            process.join(timeout=0.2)
        receive.close()
        exit_code = process.exitcode
        process.close()
    if complete and exit_code != 0:
        complete = False
        reason = f'Worker reported completion but exited with code {exit_code}'
    if complete and terminals != set(job['subjects']):
        complete = False
        reason = 'Worker reported completion without every terminal result'
    for subject in job['subjects']:
        if subject in slots and (not complete or subject not in terminals):
            slots[subject]['run']['terminal_status'] = 'failed'
            slots[subject]['errors'].append({'stage': 'supervisor', 'reason': reason})
        if subject not in slots:
            decisions = failure_decisions(priors.get(subject), 'source_failure: ' + reason)
            slots[subject] = envelope(subject, job['run_id'], job['started_at'], decisions,
                                      priors.get(subject), reason)
            reports[subject] = {'envelope': slots[subject], 'decisions': decisions,
                                'attempts': [{'source': 'batch_worker', 'status': 'failed', 'reason': reason}]}
    return [slots[s] for s in job['subjects']], [reports[s] for s in job['subjects']], {
        'worker_completed': complete, 'worker_exit_code': exit_code,
        'effective_workers': 1, 'unfinished_reason': None if complete else reason,
        'operations': accounting,
        'prior_verified_companies': len(priors), 'invalid_previous': invalid_previous}
