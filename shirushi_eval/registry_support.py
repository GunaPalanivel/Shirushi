"""Independent archive membership and field audit; imports no application code."""
import csv
import gzip
import hashlib
import io
import json
import re

from .reference import strict_json

FIELDS = {
    'legal_name': ('name', 'navn'), 'legal_form': ('legal_form', 'organisasjonsform.kode'),
    'registered_employees': ('employees', 'antallAnsatte'),
    'registered_municipality': ('municipality', 'forretningsadresse.kommune'),
    'registered_municipality_number': ('municipality_number', 'forretningsadresse.kommunenummer'),
    'industry_code': ('industry_code', 'naeringskode1.kode'),
    'industry_label': ('industry_label', 'naeringskode1.beskrivelse'),
    'latest_submitted_accounts_year': ('latest_submitted_accounts', 'sisteInnsendteAarsregnskap'),
}


def registry_source(audit, receipt, raw, subject):
    from .support import check_time
    check_time(receipt['retrieved_at'])
    kind = receipt.get('dataset_format', 'jsonl')
    if (kind not in ('csv', 'jsonl') or receipt.get('snapshot_kind') != 'registry_' + kind
            or receipt.get('source_class') != 'frozen_registry' or receipt.get('organisation_number') != subject
            or type(receipt.get('compressed')) is not bool or receipt['sha256'] != receipt['parent_sha256']):
        raise ValueError('Audit frozen identity receipt mismatch')
    key = (receipt['parent_sha256'], receipt['uncompressed_sha256'], receipt['compressed'], kind)
    if key not in audit.archives or subject not in audit.archives[key]:
        parent = audit.read('objects', receipt['parent_sha256'])
        stream = gzip.GzipFile(fileobj=io.BytesIO(parent)) if receipt['compressed'] else io.BytesIO(parent)
        hasher, rows = hashlib.sha256(), {}
        total = 0
        def lines():
            nonlocal total
            while True:
                line = stream.readline(1024 * 1024 + 1)
                if not line:
                    break
                total += len(line)
                if len(line) > 1024 * 1024 or total > 2 * 1024 * 1024 * 1024:
                    raise ValueError('Audit registry expansion bound exceeded')
                hasher.update(line)
                yield line
        with stream:
            if kind == 'csv':
                iterator = lines()
                header = next(iterator).decode('utf-8-sig')
                dialect = csv.Sniffer().sniff(header, delimiters=',;\t')
                names = next(csv.reader([header], dialect))
                if len(set(names)) != len(names) or 'organisasjonsnummer' not in names:
                    raise ValueError('Audit CSV header mismatch')
                reader = csv.DictReader((line.decode('utf-8') for line in iterator), fieldnames=names,
                                        dialect=dialect, strict=True)
                for index, row in enumerate(reader, 1):
                    if None in row or any(v is None for v in row.values()):
                        raise ValueError('Audit CSV row shape mismatch')
                    org = row['organisasjonsnummer']
                    if re.fullmatch('[0-9]{9}', org) is None:
                        raise ValueError('Audit CSV subject invalid')
                    if org in audit.subjects | {subject}:
                        if org in rows:
                            raise ValueError('Duplicate audit registry subject')
                        encoded = json.dumps(row, ensure_ascii=False, sort_keys=True,
                                             separators=(',', ':'), allow_nan=False).encode()
                        rows[org] = (encoded, index)
            else:
                for index, line in enumerate(lines(), 1):
                    if not line.strip():
                        continue
                    row = strict_json(line)
                    org = row['organisation_number']
                    if org in audit.subjects | {subject}:
                        if org in rows:
                            raise ValueError('Duplicate audit registry subject')
                        rows[org] = (line, index)
        if hasher.hexdigest() != receipt['uncompressed_sha256']:
            raise ValueError('Audit expanded registry hash mismatch')
        audit.archives[key] = rows
    if audit.archives[key].get(subject) != (raw, receipt['row_number']):
        raise ValueError('Audit row membership failure')
    return strict_json(raw)


def audit_registry(audit, subject, claim, item, receipt, raw):
    row = registry_source(audit, receipt, raw, subject)
    csv_source = receipt['snapshot_kind'] == 'registry_csv'
    field = claim['field']
    column = FIELDS[field][int(csv_source)]
    source_value = row[column]
    value = source_value
    if csv_source and field == 'registered_employees':
        if 'harRegistrertAntallAnsatte' in row and row['harRegistrertAntallAnsatte'] != 'true':
            raise ValueError('Audit employee count is not explicitly registered')
        if not isinstance(value, str) or re.fullmatch('[0-9]+', value) is None:
            raise ValueError('Audit CSV employee value invalid')
        value = int(value)
    expected = int if field == 'registered_employees' else str
    if (type(value) is not expected or type(claim['value']) is not expected or value != claim['value']
            or (expected is str and not value.strip()) or (expected is int and value < 0)
            or claim.get('scope') != 'frozen_registry'
            or item['locator'] != {'row_number': receipt['row_number'], 'organisation_number': subject, 'field': column}
            or strict_json(item['claim_span']) != source_value
            or item['extraction_method'] != ('registry_csv_column_v1' if csv_source else 'registry_json_field_v1')):
        raise ValueError('Audit registry value, locator or scope mismatch')
    if field == 'latest_submitted_accounts_year' and re.fullmatch('[0-9]{4}', value) is None:
        raise ValueError('Audit filing year invalid')


def identity_anchor(audit, sid, subject):
    receipt = strict_json(audit.read('receipts', sid))
    raw = audit.read('objects', receipt['content_sha256'])
    if receipt.get('source_class') == 'frozen_registry':
        row = registry_source(audit, receipt, raw, subject)
        csv_source = receipt['snapshot_kind'] == 'registry_csv'
        name = row.get('navn' if csv_source else 'name')
        if not isinstance(name, str) or not name.strip():
            raise ValueError('Audit frozen legal name absent')
        return {'organisasjonsnummer': subject, 'navn': name,
                'hjemmeside': row.get('hjemmeside' if csv_source else 'website') or ''}
    row = strict_json(raw)
    if (receipt.get('source_class') != 'brreg_entity' or receipt.get('organisation_number') != subject
            or receipt.get('http_status') != 200 or receipt.get('sha256') != hashlib.sha256(raw).hexdigest()
            or receipt.get('source_url') != 'https://data.brreg.no/enhetsregisteret/api/enheter/' + subject
            or row.get('organisasjonsnummer') != subject or not isinstance(row.get('navn'), str) or not row['navn'].strip()):
        raise ValueError('Audit live identity anchor mismatch')
    return row
