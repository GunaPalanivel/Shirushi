"""Saved official roles: proposal generation and source-bound acceptance."""
import re
from datetime import datetime, timezone
from pathlib import Path

from .contracts import loads, timestamp
from .extraction import Candidate
from .json_spans import span
from .snapshots import canonical, digest

def entity_holder(entity):
    """Brreg writes an entity role name as a string or as a one-item list."""
    holder = entity.get('navn')
    if isinstance(holder, list):
        if len(holder) == 1 and isinstance(holder[0], str) and holder[0].strip():
            return holder[0].strip(), ['enhet', 'navn', 0]
        return None, None
    if isinstance(holder, str) and holder.strip():
        return holder.strip(), ['enhet', 'navn']
    return None, None


def role_identity(value):
    parts = [value['role_code'], value['person_name']]
    number = value.get('organisation_number')
    if number:
        parts.append(number)
    return parts


def role_field(value):
    return 'registered_role:' + digest(canonical(role_identity(value)))[:24]


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
            code, label = role_type.get('kode'), role_type.get('beskrivelse')
            if (not isinstance(code, str) or not code.strip() or not isinstance(label, str) or not label.strip()
                    or record.get('avregistrert') is not False or record.get('fratraadt') is True):
                continue
            person = record.get('person') if isinstance(record.get('person'), dict) else None
            entity = record.get('enhet') if isinstance(record.get('enhet'), dict) else None
            if person is not None:
                if person.get('erDoed') is not False:
                    continue
                name = person.get('navn', {})
                full_name = ' '.join(name[k] for k in ('fornavn', 'mellomnavn', 'etternavn') if name.get(k))
                if not full_name.strip():
                    continue
                value = {'role_code': code, 'role_label': label, 'person_name': full_name}
            elif entity is not None:
                org = entity.get('organisasjonsnummer')
                holder, _ = entity_holder(entity)
                if entity.get('erSlettet') is True or holder is None or not isinstance(org, str) or re.fullmatch(r'[0-9]{9}', org) is None:
                    continue
                value = {'role_code': code, 'role_label': label, 'person_name': holder,
                         'organisation_number': org}
            else:
                continue
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
        path = ['rollegrupper', group_index, 'roller', role_index]
        kind = role['type']
        if (role.get('avregistrert') is not False or role.get('fratraadt') is True
                or not isinstance(kind.get('kode'), str) or not kind['kode'].strip()
                or not isinstance(kind.get('beskrivelse'), str) or not kind['beskrivelse'].strip()):
            raise ValueError('Role is inactive or lacks a registered type')
        person = role.get('person') if isinstance(role.get('person'), dict) else None
        entity = role.get('enhet') if isinstance(role.get('enhet'), dict) else None
        if person is not None:
            if person.get('erDoed') is not False:
                raise ValueError('Role is inactive or lacks an explicit active state')
            name = person['navn']
            for key in ('fornavn', 'etternavn'):
                if not isinstance(name.get(key), str) or not name[key].strip():
                    raise ValueError('Incomplete person name')
            if name.get('mellomnavn') is not None and not isinstance(name['mellomnavn'], str):
                raise ValueError('Invalid middle name')
            value = {'role_code': kind['kode'], 'role_label': kind['beskrivelse'],
                     'person_name': ' '.join(name[k] for k in ('fornavn', 'mellomnavn', 'etternavn') if name.get(k))}
            span_path = path + ['person', 'navn']
        elif entity is not None:
            org = entity.get('organisasjonsnummer')
            holder, name_path = entity_holder(entity)
            if (entity.get('erSlettet') is True or holder is None
                    or not isinstance(org, str) or re.fullmatch(r'[0-9]{9}', org) is None):
                raise ValueError('Entity role holder is missing or deregistered')
            value = {'role_code': kind['kode'], 'role_label': kind['beskrivelse'],
                     'person_name': holder, 'organisation_number': org}
            span_path = path + name_path
        else:
            raise ValueError('Role has neither a person nor an entity holder')
        if value != candidate.value or candidate.field != role_field(value):
            raise ValueError('Role value or semantic identity does not match source')
        date = group.get('sistEndret')
        if not isinstance(date, str) or re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', date) is None:
            raise ValueError('Missing registered change date')
        datetime.fromisoformat(date)
        eid = candidate.snapshot_id + ':' + candidate.field
        evidence = {'id': eid, 'snapshot_id': candidate.snapshot_id, 'source_url': expected,
                    'source_class': 'brreg_roles_snapshot', 'retrieved_at': receipt['retrieved_at'],
                    'content_sha256': digest(raw), 'claim_span': span(raw, span_path),
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
