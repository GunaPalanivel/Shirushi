"""Independent retained-source audit; imports no maker extraction or checker."""
import gzip
import hashlib
import io
import json
import re
from pathlib import Path
from datetime import datetime

from .reference import normalized_role, strict_json

IDENTITY_FIELDS = {'legal_name': 'name', 'legal_form': 'legal_form', 'registered_employees': 'employees',
                   'registered_municipality': 'municipality', 'registered_municipality_number': 'municipality_number',
                   'industry_code': 'industry_code', 'industry_label': 'industry_label',
                   'latest_submitted_accounts_year': 'latest_submitted_accounts'}


def check_time(value):
    if (not isinstance(value, str) or re.fullmatch(
            r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})', value) is None
            or value.endswith('-00:00')):
        raise ValueError('Invalid audit timestamp')
    if not value.endswith('Z') and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
        raise ValueError('Invalid audit timestamp offset')
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


class SourceAudit:
    def __init__(self, store, subjects):
        self.store, self.subjects = Path(store), set(subjects)
        self.archives = {}

    def read(self, kind, identifier):
        if not isinstance(identifier, str) or re.fullmatch('[0-9a-f]{64}', identifier) is None:
            raise ValueError('Invalid audit snapshot identity')
        suffix = '.json' if kind == 'receipts' else '.bin'
        data = (self.store / kind / (identifier + suffix)).read_bytes()
        if hashlib.sha256(data).hexdigest() != identifier:
            raise ValueError('Audit source hash mismatch')
        return data

    def claim(self, subject, claim, evidence):
        if claim['availability'] not in ('available', 'not_available', 'blocked', 'not_applicable', 'ambiguous', 'failed'):
            raise ValueError('Unknown availability state')
        if claim['availability'] != 'available':
            if claim['value'] is not None or not claim.get('reason'):
                raise ValueError('Unavailable claim must contain null and reason')
            return
        if not claim['evidence_ids']:
            raise ValueError('Published claim lacks evidence')
        for ref in claim['evidence_ids']:
            item = evidence[ref]
            receipt = strict_json(self.read('receipts', item['snapshot_id']))
            check_time(receipt['retrieved_at'])
            raw = self.read('objects', receipt['content_sha256'])
            if (item['content_sha256'] != receipt['content_sha256'] or item['source_url'] != receipt['source_url']
                    or item['retrieved_at'] != receipt['retrieved_at'] or item['source_class'] != receipt['source_class']
                    or receipt['organisation_number'] != subject):
                raise ValueError('Evidence origin differs from its source receipt')
            if item['claim_span'].encode('utf-8') not in raw:
                raise ValueError('Evidence span is not in source bytes')
            if receipt['source_class'] in ('brreg_entity', 'brreg_accounts', 'brreg_subunits', 'company_owned'):
                from .live_support import audit_api, audit_web
                if receipt['source_class'] == 'company_owned':
                    anchor_receipt = strict_json(self.read('receipts', receipt['ownership_anchor_snapshot_id']))
                    anchor = strict_json(self.read('objects', anchor_receipt['content_sha256']))
                    from urllib.parse import urlsplit
                    if receipt.get('robots_snapshot_id'):
                        from urllib.robotparser import RobotFileParser
                        robots_receipt = strict_json(self.read('receipts', receipt['robots_snapshot_id']))
                        robots_raw = self.read('objects', robots_receipt['content_sha256'])
                        robots_url = 'https://' + receipt['declared_host'] + '/robots.txt'
                        if (robots_receipt.get('source_class') != 'robots_policy'
                                or robots_receipt.get('source_url') != robots_url
                                or robots_receipt.get('http_status') not in (200, 404)):
                            raise ValueError('Audit robots policy receipt mismatch')
                        parser = RobotFileParser(robots_url)
                        parser.parse(robots_raw.decode('utf-8').splitlines() if robots_receipt['http_status'] == 200 else [])
                        if not parser.can_fetch('Shirushi/0.1', receipt['effective_url']):
                            raise ValueError('Audit robots denies published page')
                    website = anchor.get('hjemmeside', '')
                    host = urlsplit(website if '://' in website else 'https://' + website).hostname
                    identity_url = 'https://data.brreg.no/enhetsregisteret/api/enheter/' + subject
                    if (anchor.get('organisasjonsnummer') != subject
                            or anchor_receipt.get('source_class') != 'brreg_entity'
                            or anchor_receipt.get('organisation_number') != subject
                            or anchor_receipt.get('http_status') != 200
                            or anchor_receipt.get('source_url') != identity_url):
                        raise ValueError('Audit website identity anchor mismatch')
                    ownership_id = receipt.get('operator_snapshot_id', item['snapshot_id'])
                    ownership_receipt = strict_json(self.read('receipts', ownership_id))
                    ownership_raw = self.read('objects', ownership_receipt['content_sha256'])
                    from .html_support import legal_operator, audit_html
                    proof = legal_operator(ownership_raw, subject, anchor.get('navn', ''))
                    if proof and (ownership_receipt.get('organisation_number') != subject
                            or ownership_receipt.get('source_class') != 'company_owned'
                            or ownership_receipt.get('http_status') != 200
                            or ownership_receipt.get('robots_checked') is not True
                            or ownership_receipt.get('ownership_anchor_snapshot_id') != receipt['ownership_anchor_snapshot_id']
                            or urlsplit(ownership_receipt['effective_url']).hostname != receipt['declared_host']):
                        raise ValueError('Audit operator source chain mismatch')
                    aliases = {host, host[4:] if host and host.startswith('www.') else 'www.' + host if host else None}
                    if receipt['declared_host'] not in aliases and not proof:
                        raise ValueError('Audit website discovery anchor mismatch')
                    if item['extraction_method'] == 'explicit_subject_html_v1':
                        audit_html(subject, claim, item, receipt, raw, anchor.get('navn', ''), ownership_raw)
                        continue
                (audit_web if receipt['source_class'] == 'company_owned' else audit_api)(subject, claim, item, receipt, raw)
                continue
            source = strict_json(raw)
            if claim['field'] in IDENTITY_FIELDS:
                if (claim.get('scope') != 'frozen_registry' or receipt['snapshot_kind'] != 'registry_jsonl'
                        or receipt.get('source_class') != 'frozen_registry'):
                    raise ValueError('Frozen identity scope mismatch')
                parent_key = receipt['parent_sha256']
                parent = self.read('objects', parent_key)
                key = (parent_key, receipt['uncompressed_sha256'], receipt['compressed'])
                if receipt['sha256'] != parent_key:
                    raise ValueError('Archive receipt mismatch')
                if key not in self.archives:
                    digest = hashlib.sha256()
                    rows = {}
                    stream = gzip.GzipFile(fileobj=io.BytesIO(parent)) if receipt['compressed'] else io.BytesIO(parent)
                    with stream:
                        for index, line in enumerate(stream, 1):
                            digest.update(line)
                            row = strict_json(line)
                            if row['organisation_number'] in self.subjects:
                                if row['organisation_number'] in rows:
                                    raise ValueError('Duplicate audit registry subject')
                                rows[row['organisation_number']] = (line, index)
                    if digest.hexdigest() != receipt['uncompressed_sha256']:
                        raise ValueError('Audit expanded archive hash mismatch')
                    self.archives[key] = rows
                if self.archives[key].get(subject) != (raw, receipt['row_number']):
                    raise ValueError('Audit row membership failure')
                value = source[IDENTITY_FIELDS[claim['field']]]
                expected_type = int if claim['field'] == 'registered_employees' else str
                if type(value) is not expected_type or (expected_type is str and not value.strip()):
                    raise ValueError('Audit registry field type mismatch')
                if claim['field'] == 'registered_employees' and value < 0:
                    raise ValueError('Negative registry employee count')
                if type(value) is not type(claim['value']) or value != claim['value']:
                    raise ValueError('Audit identity value mismatch')
                if source['organisation_number'] != subject:
                    raise ValueError('Audit identity subject mismatch')
                if item['locator'] != {'row_number': receipt['row_number'], 'organisation_number': subject,
                                       'field': IDENTITY_FIELDS[claim['field']]}:
                    raise ValueError('Audit identity locator mismatch')
                if strict_json(item['claim_span']) != value:
                    raise ValueError('Audit identity span supports a different value')
            elif claim['field'].startswith('registered_role:'):
                url = f'https://data.brreg.no/enhetsregisteret/api/enheter/{subject}/roller'
                if (claim.get('scope') != 'registered_role_snapshot' or receipt['snapshot_kind'] != 'brreg_roles_json'
                        or receipt.get('source_class') != 'brreg_roles_snapshot'
                        or receipt['source_url'] != url or receipt.get('effective_url') != url
                        or receipt.get('http_status') != 200 or receipt.get('access_policy') != 'brreg-open-data-nlod-2.0'
                        or source['_links']['self']['href'] != url or source['_links']['enhet']['href'] != url[:-7]):
                    raise ValueError('Audit role attribution failure')
                group_index, role_index = item['locator']['group_index'], item['locator']['role_index']
                if type(group_index) is not int or type(role_index) is not int or min(group_index, role_index) < 0:
                    raise ValueError('Invalid audit role locator')
                group = source['rollegrupper'][group_index]
                role = group['roller'][role_index]
                if normalized_role(role) != claim['value'] or claim.get('source_registered_change_date') != group['sistEndret']:
                    raise ValueError('Audit registered role value mismatch')
                if strict_json(item['claim_span']) != role['person']['navn']:
                    raise ValueError('Audit role name span mismatch')
                for field, source_key in [('type', 'type'), ('active', 'avregistrert')]:
                    text = item['support_spans'][field]
                    if text.encode('utf-8') not in raw or strict_json(text) != role[source_key]:
                        raise ValueError('Audit role supporting span mismatch')
                canonical = json.dumps([claim['value']['role_code'], claim['value']['person_name']],
                                       ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
                if claim['field'] != 'registered_role:' + hashlib.sha256(canonical).hexdigest()[:24]:
                    raise ValueError('Audit role semantic key mismatch')
            else:
                raise ValueError('No independent support audit for published field')
