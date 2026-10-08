"""Saved official roles: proposal generation and source-bound acceptance."""
import re
from datetime import datetime, timezone
from pathlib import Path

from .contracts import loads, timestamp
from .extraction import Candidate
from .json_spans import span
from .snapshots import canonical, digest

ROLE_CODES = {'DAGL', 'LEDE', 'MEDL', 'NEST', 'VARA'}


def role_field(value):
    return 'registered_role:' + digest(canonical([value['role_code'], value['person_name']]))[:24]


def acquire_role(entry, manifest_path, store, limit):
    subject = entry['organisation_number']
    expected = f'https://data.brreg.no/enhetsregisteret/api/enheter/{subject}/roller'
    if (entry.get('source_class') != 'brreg_roles_snapshot' or entry.get('source_url') != expected
            or entry.get('effective_url') != expected or entry.get('http_status') != 200
            or entry.get('access_policy') != 'brreg-open-data-nlod-2.0'):
        raise ValueError('Saved role source receipt does not match the permitted exact endpoint')
    if timestamp(entry.get('retrieved_at')) > datetime.now(timezone.utc):
        raise ValueError('Role acquisition timestamp is in the future')
    path = (Path(manifest_path).parent / entry['path']).resolve()
    if path.stat().st_size > limit:
        raise ValueError('Saved roles exceed byte limit')
    raw = path.read_bytes()
    if digest(raw) != entry.get('sha256'):
        raise ValueError('Saved role source hash mismatch')
    receipt = {k: v for k, v in entry.items() if k != 'path'}
    return store.save(raw, dict(receipt, snapshot_kind='brreg_roles_json'))


def propose_roles(store, snapshot_id):
    raw, receipt = store.open(snapshot_id)
    body = loads(raw)
    candidates = []
    for group_index, group in enumerate(body.get('rollegrupper', [])):
        for role_index, record in enumerate(group.get('roller', [])):
            role_type = record.get('type', {})
            if role_type.get('kode') not in ROLE_CODES or record.get('avregistrert') is not False:
                continue
            person = record.get('person', {})
            if person.get('erDoed') is not False:
                continue
            name = person.get('navn', {})
            full_name = ' '.join(name[k] for k in ('fornavn', 'mellomnavn', 'etternavn') if name.get(k))
            value = {'role_code': role_type['kode'], 'role_label': role_type['beskrivelse'], 'person_name': full_name}
            candidates.append(Candidate(receipt['organisation_number'], role_field(value), value, snapshot_id,
                                        {'group_index': group_index, 'role_index': role_index}))
    if len(candidates) > 100:
        raise ValueError('Role candidate count exceeds local bound')
    return candidates


def check_role(store, candidate, subject):
    audit = {'checker_version': 'brreg_role_evidence_v1', 'field': candidate.field,
             'candidate': {'organisation_number': candidate.organisation_number, 'value': candidate.value,
                           'snapshot_id': candidate.snapshot_id, 'locator': candidate.locator}}
    try:
        raw, receipt = store.open(candidate.snapshot_id)
        expected = f'https://data.brreg.no/enhetsregisteret/api/enheter/{subject}/roller'
        if (candidate.organisation_number != subject or receipt.get('organisation_number') != subject
                or receipt.get('snapshot_kind') != 'brreg_roles_json' or receipt.get('source_url') != expected
                or receipt.get('effective_url') != expected or receipt.get('http_status') != 200
                or receipt.get('source_class') != 'brreg_roles_snapshot'
                or receipt.get('access_policy') != 'brreg-open-data-nlod-2.0'
                or receipt.get('sha256') != digest(raw)):
            raise ValueError('Role subject, source or receipt mismatch')
        if timestamp(receipt.get('retrieved_at')) > datetime.now(timezone.utc):
            raise ValueError('Role acquisition time is in the future')
        body = loads(raw)
        if (body['_links']['self']['href'] != expected
                or body['_links']['enhet']['href'] != expected.removesuffix('/roller')):
            raise ValueError('Role response points to another legal subject')
        locator = candidate.locator
        group_index, role_index = locator['group_index'], locator['role_index']
        if any(type(i) is not int or i < 0 for i in (group_index, role_index)):
            raise ValueError('Invalid role locator')
        group = body['rollegrupper'][group_index]
        role = group['roller'][role_index]
        person, kind = role['person'], role['type']
        if role.get('avregistrert') is not False or person.get('erDoed') is not False:
            raise ValueError('Role is inactive or lacks an explicit active state')
        if kind['kode'] not in {'DAGL', 'LEDE', 'MEDL', 'NEST', 'VARA'}:
            raise ValueError('Unsupported registered role type')
        name = person['navn']
        for key in ('fornavn', 'etternavn'):
            if not isinstance(name.get(key), str) or not name[key].strip():
                raise ValueError('Incomplete person name')
        if name.get('mellomnavn') is not None and not isinstance(name['mellomnavn'], str):
            raise ValueError('Invalid middle name')
        value = {'role_code': kind['kode'], 'role_label': kind['beskrivelse'],
                 'person_name': ' '.join(name[k] for k in ('fornavn', 'mellomnavn', 'etternavn') if name.get(k))}
        if not isinstance(value['role_label'], str) or not value['role_label'].strip():
            raise ValueError('Missing role label')
        if value != candidate.value or candidate.field != role_field(value):
            raise ValueError('Role value or semantic identity does not match source')
        date = group.get('sistEndret')
        if not isinstance(date, str) or re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', date) is None:
            raise ValueError('Missing registered change date')
        datetime.fromisoformat(date)
        path = ['rollegrupper', group_index, 'roller', role_index]
        eid = candidate.snapshot_id + ':' + candidate.field
        evidence = {'id': eid, 'snapshot_id': candidate.snapshot_id, 'source_url': expected,
                    'source_class': 'brreg_roles_snapshot', 'retrieved_at': receipt['retrieved_at'],
                    'content_sha256': digest(raw), 'claim_span': span(raw, path + ['person', 'navn']),
                    'support_spans': {'type': span(raw, path + ['type']),
                                      'active': span(raw, path + ['avregistrert'])},
                    'extraction_method': 'brreg_registered_role_v1',
                    'locator': {'group_index': group_index, 'role_index': role_index}}
        claim = {'field': candidate.field, 'value': value, 'availability': 'available',
                 'scope': 'registered_role_snapshot', 'evidence_ids': [eid],
                 'source_registered_change_date': date, 'freshness': 'saved_source_snapshot'}
        return dict(audit, accepted=True, claim=claim, evidence=evidence)
    except (ValueError, OSError, KeyError, TypeError, IndexError, AttributeError) as exc:
        return dict(audit, accepted=False, reason=str(exc))
