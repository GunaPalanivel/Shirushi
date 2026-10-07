"""Compare supported semantic values; acquisition failure never proves removal."""
from copy import deepcopy

from .contracts import timestamp


def merge(previous, decisions, observed_at):
    previous = previous or {'claims': [], 'evidence': [], 'history': []}
    old = {c['field']: deepcopy(c) for c in previous['claims']}
    evidence = {e['id']: deepcopy(e) for e in previous['evidence']}
    history = deepcopy(previous.get('history', []))
    claims, changes = [], []
    for decision in decisions:
        field = decision['field']
        prior = old.pop(field, None)
        if not decision['accepted']:
            if prior and prior['availability'] == 'available':
                prior['freshness'] = 'stale_after_failed_observation'
                prior['current_attempt_reason'] = decision['reason']
                claims.append(prior)
            else:
                claims.append({'field': field, 'value': None, 'availability': 'not_available'
                               if decision['reason'] == 'absent_in_frozen_row' else 'failed',
                               'reason': decision['reason'], 'evidence_ids': []})
            continue
        new = deepcopy(decision['claim'])
        item = decision['evidence']
        if prior and prior['availability'] == 'available':
            latest = max(timestamp(evidence[e]['retrieved_at']) for e in prior['evidence_ids'])
            if timestamp(item['retrieved_at']) < latest:
                prior['current_attempt_reason'] = 'older_source_cannot_replace_newer_support'
                claims.append(prior)
                continue
            same = type(prior['value']) is type(new['value']) and prior['value'] == new['value']
            if same:
                new['evidence_ids'] = list(dict.fromkeys(prior['evidence_ids'] + new['evidence_ids']))
                new['first_observed_at'] = prior['first_observed_at']
            else:
                history.append(prior)
                changes.append({'field': field, 'kind': 'value_changed', 'old_value': prior['value'],
                                'new_value': new['value'], 'old_evidence_ids': prior['evidence_ids'],
                                'new_evidence_ids': new['evidence_ids'], 'observed_at': observed_at})
        new.setdefault('first_observed_at', observed_at)
        new['last_observed_at'] = observed_at
        evidence[item['id']] = item
        claims.append(new)
    # Unknown old fields are not silently removed (previous checker rejects unsupported fields).
    claims.extend(old.values())
    return {'claims': claims, 'evidence': list(evidence.values()), 'history': history, 'changes': changes}
