"""Accept proposals only after independently checking their retained source."""
import json
import re

from .contracts import loads, timestamp
from .registry import find_row

SPECIFICATIONS = {
    'legal_name': ('name', str), 'legal_form': ('legal_form', str),
    'registered_employees': ('employees', int),
    'registered_municipality': ('municipality', str),
    'registered_municipality_number': ('municipality_number', str),
    'industry_code': ('industry_code', str), 'industry_label': ('industry_label', str),
    'latest_submitted_accounts_year': ('latest_submitted_accounts', str),
}


def value_span(raw, target):
    """Locate a top-level JSON value token without substring or regex attribution."""
    text = raw.decode('utf-8')
    decoder = json.JSONDecoder()
    position = text.index('{') + 1
    while True:
        while text[position].isspace() or text[position] == ',':
            position += 1
        if text[position] == '}':
            raise ValueError('Field absent from source')
        key, position = decoder.raw_decode(text, position)
        while text[position].isspace():
            position += 1
        if text[position] != ':':
            raise ValueError('Invalid object framing')
        position += 1
        while text[position].isspace():
            position += 1
        start = position
        _, position = decoder.raw_decode(text, position)
        if key == target:
            return text[start:position]


class EvidenceChecker:
    def __init__(self, store):
        self.store = store
        self.proofs = {}

    def verify_source(self, snapshot_id, subject):
        raw, receipt = self.store.open(snapshot_id)
        if receipt.get('snapshot_kind') != 'registry_jsonl' or receipt.get('organisation_number') != subject:
            raise ValueError('Snapshot subject or kind mismatch')
        if type(receipt.get('compressed')) is not bool:
            raise ValueError('Invalid archive encoding declaration')
        # Re-read hashes even when membership proof is cached within this checker.
        parent = self.store.read('objects', receipt['parent_sha256'])
        if receipt['sha256'] != receipt['parent_sha256']:
            raise ValueError('Receipt archive identity mismatch')
        cache_key = (snapshot_id, subject)
        if cache_key not in self.proofs:
            line, index = find_row(parent, receipt, subject, receipt['compressed'])
            if line != raw or index != receipt.get('row_number'):
                raise ValueError('Selected bytes are not the declared registry row')
            self.proofs[cache_key] = True
        row = loads(raw)
        if row.get('organisation_number') != subject:
            raise ValueError('Source subject mismatch')
        return raw, receipt, row

    def check(self, candidate, subject):
        audit = {'checker_version': 'registry_evidence_v1', 'field': candidate.field,
                 'candidate': {'organisation_number': candidate.organisation_number,
                               'field': candidate.field, 'value': candidate.value,
                               'snapshot_id': candidate.snapshot_id}}
        try:
            if candidate.organisation_number != subject:
                raise ValueError('Candidate subject mismatch')
            if candidate.field not in SPECIFICATIONS:
                raise ValueError('Unsupported field')
            raw, receipt, row = self.verify_source(candidate.snapshot_id, subject)
            key, expected_type = SPECIFICATIONS[candidate.field]
            value = row.get(key)
            if value is None or value == '':
                return dict(audit, accepted=False, reason='absent_in_frozen_row')
            if type(value) is not expected_type or type(candidate.value) is not expected_type or candidate.value != value:
                raise ValueError('Proposed value or type does not match source')
            if expected_type is str and not value.strip():
                raise ValueError('Blank registry value')
            if candidate.field == 'registered_employees' and value < 0:
                raise ValueError('Negative registered employee count')
            if candidate.field == 'latest_submitted_accounts_year' and re.fullmatch(r'[0-9]{4}', value) is None:
                raise ValueError('Invalid filing metadata year')
            evidence_id = candidate.snapshot_id + ':' + candidate.field
            claim = {'field': candidate.field, 'value': value, 'availability': 'available',
                     'evidence_ids': [evidence_id], 'scope': 'frozen_registry',
                     'freshness': 'frozen_snapshot'}
            evidence = {'id': evidence_id, 'snapshot_id': candidate.snapshot_id,
                        'source_url': receipt['source_url'], 'source_class': 'frozen_registry',
                        'retrieved_at': receipt['retrieved_at'], 'content_sha256': receipt['content_sha256'],
                        'claim_span': value_span(raw, key), 'extraction_method': 'registry_json_field_v1',
                        'locator': {'row_number': receipt['row_number'], 'organisation_number': subject, 'field': key}}
            return dict(audit, accepted=True, claim=claim, evidence=evidence)
        except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
            return dict(audit, accepted=False, reason=str(exc))

    def verify_previous(self, envelope, subject):
        from .extraction import Candidate
        evidence = {e['id']: e for e in envelope['evidence']}
        history = envelope.get('history', [])
        if not isinstance(history, list) or any(not isinstance(c, dict) for c in history):
            raise ValueError('Previous history must be a list of claims')
        fields = set()
        for claim in envelope['claims'] + history:
            if claim.get('field') not in SPECIFICATIONS:
                raise ValueError('Unsupported previous field')
            if claim in envelope['claims']:
                if claim['field'] in fields:
                    raise ValueError('Duplicate previous active field')
                fields.add(claim['field'])
            if claim.get('availability') != 'available':
                continue
            if claim.get('scope') != 'frozen_registry':
                raise ValueError('Previous claim scope mismatch')
            if not isinstance(claim.get('evidence_ids'), list) or not claim['evidence_ids']:
                raise ValueError('Previous supported claim lacks evidence')
            if timestamp(claim.get('first_observed_at')) > timestamp(claim.get('last_observed_at')):
                raise ValueError('Previous observation timestamps are reversed')
            for identity in claim['evidence_ids']:
                item = evidence[identity]
                decision = self.check(Candidate(subject, claim['field'], claim['value'], item.get('snapshot_id')), subject)
                if not decision['accepted'] or decision['evidence'] != item:
                    raise ValueError('Previous claim or evidence failed source verification')
