"""Validate configuration and envelope boundaries, not source truth."""
import argparse
import json
import math
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def loads(text):
    def reject_constant(value):
        raise ValueError(f'Non-finite JSON number: {value}')

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f'JSON number exceeds supported finite range: {value}')
        return number
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate JSON key: {key}')
            result[key] = value
        return result
    return json.loads(text, parse_constant=reject_constant,
                      parse_float=finite_float, object_pairs_hook=unique_pairs)


def load(path):
    return loads(Path(path).read_text(encoding='utf-8'))


def validate_config(config, policy):
    if not isinstance(config, dict):
        return ['Configuration must be an object']
    errors = []
    required = {'contract_version', 'mode', 'sample_size', 'wall_time_seconds', 'request_budget',
                'third_party_cost_usd', 'workers', 'per_host_concurrency', 'request_timeout_seconds',
                'max_retries', 'finalization_reserve_fraction', 'max_response_bytes', 'max_pdf_bytes',
                'network_enabled', 'enabled_sources', 'settings_origin'}
    official_fields = {'organizer_settings_receipt', 'cpu_limit', 'memory_limit_bytes', 'cutoff', 'wire_schema_confirmed'}
    missing = required - config.keys()
    errors.extend(f'Missing setting: {key}' for key in sorted(missing))
    allowed = required | (official_fields if config.get('mode') == 'official' else set())
    errors.extend(f'Unknown setting: {key}' for key in sorted(config.keys() - allowed))
    if config.get('contract_version') != 'shirushi-local-v1':
        errors.append('Unknown contract version')
    if config.get('mode') not in ('local', 'official'):
        errors.append('Mode must be local or official')
    for key in ('sample_size', 'wall_time_seconds', 'request_budget', 'workers', 'per_host_concurrency',
                'request_timeout_seconds', 'max_response_bytes', 'max_pdf_bytes', 'max_retries'):
        value = config.get(key)
        minimum = 0 if key == 'max_retries' else 1
        if type(value) is not int or value < minimum:
            errors.append(f'{key} must be an integer >= {minimum}')
    for key, low, high in [('third_party_cost_usd', 0, None), ('finalization_reserve_fraction', 0, 1)]:
        value = config.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value < low or (high is not None and not 0 < value < high):
            errors.append(f'Invalid finite numeric setting: {key}')
    if type(config.get('network_enabled')) is not bool:
        errors.append('network_enabled must be boolean')
    sources = config.get('enabled_sources')
    if not isinstance(sources, list) or not sources or any(not isinstance(s, str) for s in sources):
        errors.append('enabled_sources must be a nonempty list of source IDs')
    else:
        if len(sources) != len(set(sources)):
            errors.append('Duplicate enabled source')
        register = {s['id']: s for s in policy['sources']}
        for source in sources:
            entry = register.get(source)
            if not entry or entry['status'] != 'enabled':
                errors.append(f'Source not activated: {source}')
            elif entry['network'] and config.get('network_enabled') is not True:
                errors.append(f'Network disabled for source: {source}')
    if type(config.get('workers')) is int and type(config.get('per_host_concurrency')) is int:
        if config['per_host_concurrency'] > config['workers']:
            errors.append('Host concurrency exceeds worker count')
    if not isinstance(config.get('settings_origin'), str) or not config['settings_origin'].strip():
        errors.append('settings_origin must identify the budget authority')
    if config.get('mode') == 'official':
        if config.get('wire_schema_confirmed') is not True:
            errors.append('Official wire schema not confirmed')
        for key in ('organizer_settings_receipt', 'cutoff'):
            if not isinstance(config.get(key), str) or not config[key].strip():
                errors.append(f'Official setting unconfirmed: {key}')
        for key in ('cpu_limit', 'memory_limit_bytes'):
            if type(config.get(key)) not in (int, float) or not math.isfinite(config[key]) or config[key] <= 0:
                errors.append(f'Official setting unconfirmed: {key}')
    return errors


def validate_inputs(records):
    errors, identities = [], []
    if not isinstance(records, list) or not records:
        return ['Input must be a nonempty batch'], []
    for index, record in enumerate(records):
        identity = record.get('organisation_number') if isinstance(record, dict) else None
        if not isinstance(identity, str) or re.fullmatch(r'[0-9]{9}', identity) is None:
            errors.append(f'Invalid organisation_number at input {index}')
        else:
            identities.append(identity)
    if len(identities) != len(set(identities)):
        errors.append('Duplicate input identity')
    return errors, identities


def timestamp(value):
    """Parse our RFC 3339 profile: known offset, uppercase T/Z, microseconds."""
    pattern = (r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}'
               r'(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})')
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise ValueError('Timestamp must match the documented RFC 3339 profile')
    if value.endswith('-00:00'):
        raise ValueError('Acquisition timestamp cannot have an unknown local offset')
    if not value.endswith('Z') and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
        raise ValueError('Timestamp offset exceeds RFC 3339 component ranges')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.utcoffset() is None:
        raise ValueError('Timestamp must include timezone')
    return parsed


def validate_envelopes(records, envelopes, contract):
    errors, identities = validate_inputs(records)
    if not isinstance(envelopes, list):
        return errors + ['Output must be a list of envelopes']
    observed = [e.get('organisation_number') if isinstance(e, dict) else None for e in envelopes]
    if observed != identities:
        errors.append('Output identities must exactly match input order and membership')
    for index, envelope in enumerate(envelopes):
        prefix = f'envelope {index}: '
        if not isinstance(envelope, dict):
            errors.append(prefix + 'must be object')
            continue
        missing = set(contract['envelope_required']) - envelope.keys()
        errors.extend(prefix + 'missing ' + key for key in sorted(missing))
        run = envelope.get('run')
        if not isinstance(run, dict):
            errors.append(prefix + 'invalid run')
        else:
            if run.get('terminal_status') not in contract['run_terminal_states'] or not isinstance(run.get('run_id'), str) or not run['run_id'].strip():
                errors.append(prefix + 'invalid run identity or terminal state')
            try:
                if timestamp(run.get('completed_at')) < timestamp(run.get('started_at')):
                    errors.append(prefix + 'completion precedes start')
            except (ValueError, TypeError):
                errors.append(prefix + 'invalid run timestamps')
        evidence = envelope.get('evidence')
        evidence_ids = set()
        if not isinstance(evidence, list):
            errors.append(prefix + 'evidence must be list')
        else:
            for item in evidence:
                if not isinstance(item, dict):
                    errors.append(prefix + 'invalid evidence record')
                    continue
                if set(contract['evidence_required']) - item.keys():
                    errors.append(prefix + 'incomplete evidence record')
                eid = item.get('id')
                if not isinstance(eid, str) or not eid or eid in evidence_ids:
                    errors.append(prefix + 'missing or duplicate evidence ID')
                else:
                    evidence_ids.add(eid)
                if not isinstance(item.get('content_sha256'), str) or re.fullmatch(r'[0-9a-f]{64}', item['content_sha256']) is None:
                    errors.append(prefix + 'invalid content hash')
                for key in ('source_url', 'source_class', 'claim_span', 'extraction_method'):
                    if not isinstance(item.get(key), str) or not item[key].strip():
                        errors.append(prefix + 'invalid evidence ' + key)
                if not isinstance(item.get('locator'), dict) or not item['locator']:
                    errors.append(prefix + 'missing evidence locator')
                try:
                    timestamp(item.get('retrieved_at'))
                except (ValueError, TypeError):
                    errors.append(prefix + 'invalid retrieval time')
        claims = envelope.get('claims')
        if not isinstance(claims, list):
            errors.append(prefix + 'claims must be list')
        else:
            for claim in claims:
                if not isinstance(claim, dict):
                    errors.append(prefix + 'invalid claim')
                    continue
                if set(contract['claim_required']) - claim.keys():
                    errors.append(prefix + 'incomplete claim')
                if not isinstance(claim.get('field'), str) or not claim['field'].strip():
                    errors.append(prefix + 'missing claim field')
                state = claim.get('availability')
                if state not in contract['availability_states']:
                    errors.append(prefix + 'invalid availability')
                refs = claim.get('evidence_ids')
                if not isinstance(refs, list) or any(not isinstance(r, str) for r in refs):
                    errors.append(prefix + 'invalid evidence references')
                    refs = []
                if any(ref not in evidence_ids for ref in refs):
                    errors.append(prefix + 'dangling evidence reference')
                if state == 'available':
                    if claim.get('value') is None or not refs:
                        errors.append(prefix + 'available claim lacks value or evidence')
                elif claim.get('value') is not None or not isinstance(claim.get('reason'), str) or not claim['reason'].strip():
                    errors.append(prefix + 'missing/uncertain claim requires null and reason')
        for key in ('changes', 'errors'):
            if not isinstance(envelope.get(key), list):
                errors.append(prefix + key + ' must be list')
        operations = envelope.get('operations')
        if not isinstance(operations, dict):
            errors.append(prefix + 'invalid operations')
        else:
            for key in ('requests', 'runtime_ms', 'third_party_cost_usd'):
                value = operations.get(key)
                integer_only = key in ('requests', 'runtime_ms')
                if type(value) not in (int, float) or (integer_only and type(value) is not int) or not math.isfinite(value) or value < 0:
                    errors.append(prefix + 'invalid operations ' + key)
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    args = parser.parse_args()
    policy = load(ROOT / 'configs/source-policy.json')
    paths = [args.config] if args.config else sorted((ROOT / 'configs').glob('local-*.json'))
    errors = []
    for path in paths:
        try:
            errors.extend(f'{path.name}: {e}' for e in validate_config(load(path), policy))
        except (ValueError, OSError) as exc:
            errors.append(f'{path.name}: {exc}')
    print(json.dumps({'status': 'FAIL' if errors else 'PASS', 'checked_configs': len(paths), 'errors': errors}, indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
