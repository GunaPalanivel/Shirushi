"""Reference labels from original sources, without importing maker code."""
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path

FAMILIES = ('business_products', 'people', 'operating_locations', 'financials_history',
            'website_owned_profiles', 'jobs_dated_activity')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result

    def number(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('Nonfinite JSON value')
        return result

    def constant(value):
        raise ValueError('Nonfinite JSON constant: ' + value)

    return json.loads(text, object_pairs_hook=pairs, parse_float=number, parse_constant=constant)


def normalized_role(role):
    if role.get('avregistrert') is not False:
        return None
    person = role.get('person')
    if not isinstance(person, dict) or person.get('erDoed') is not False:
        return None
    kind = role.get('type', {})
    if kind.get('kode') not in ('DAGL', 'LEDE', 'MEDL', 'NEST', 'VARA'):
        return None
    names = person.get('navn', {})
    if not all(isinstance(names.get(k), str) and names[k].strip() for k in ('fornavn', 'etternavn')):
        return None
    parts = [names['fornavn']]
    if names.get('mellomnavn'):
        parts.append(names['mellomnavn'])
    parts.append(names['etternavn'])
    return {'role_code': kind['kode'], 'role_label': kind['beskrivelse'], 'person_name': ' '.join(parts)}


def build_reference(subjects, registry_rows, receipts, source_directory):
    records = {s: {'organisation_number': s, 'identity_labels': registry_rows[s], 'claims': [],
                   'opportunities': {f: 'unknown' for f in FAMILIES}, 'review_protocol':
                   'separate-source-parser-v1; registered active person roles and entity annual revenue only',
                   'independent_human_review': False, 'source_receipts': []} for s in subjects}
    for receipt in receipts:
        subject = receipt['organisation_number']
        record = records[subject]
        record['source_receipts'].append(receipt)
        if receipt['status'] != 'captured':
            continue
        raw = (Path(source_directory) / receipt['path']).read_bytes()
        if sha(raw) != receipt['sha256'] or receipt.get('http_status') != 200:
            raise ValueError('Reference source receipt mismatch')
        body = strict_json(raw)
        kind = receipt['source_class']
        if kind == 'brreg_roles_snapshot':
            url = f'https://data.brreg.no/enhetsregisteret/api/enheter/{subject}/roller'
            if (receipt['source_url'] != url or body['_links']['self']['href'] != url
                    or body['_links']['enhet']['href'] != url[:-7]):
                raise ValueError('Reference roles belong to another subject')
            seen = set()
            for group_index, group in enumerate(body['rollegrupper']):
                for role_index, role in enumerate(group['roller']):
                    value = normalized_role(role)
                    if value is None:
                        continue
                    canonical = json.dumps([value['role_code'], value['person_name']], ensure_ascii=False, separators=(',', ':'))
                    if canonical in seen:
                        raise ValueError('Reference role identity requires adjudication')
                    seen.add(canonical)
                    record['claims'].append({'canonical_id': subject + ':role:' + sha(canonical.encode()),
                                             'family': 'people', 'value': value, 'scope': 'registered_role_snapshot',
                                             'source_sha256': receipt['sha256'], 'source_url': receipt['source_url'],
                                             'source_path': receipt['path'], 'retrieved_at': receipt['retrieved_at'],
                                             'locator': [group_index, role_index]})
            record['opportunities']['people'] = 'positive' if seen else 'checked_absent'
        elif kind == 'brreg_accounts_reference':
            if receipt['source_url'] != f'https://data.brreg.no/regnskapsregisteret/regnskap/{subject}':
                raise ValueError('Wrong accounts reference endpoint')
            positive = False
            for index, item in enumerate(body):
                if item['virksomhet']['organisasjonsnummer'] != subject:
                    raise ValueError('Accounts reference belongs to another subject')
                if item.get('regnskapstype') != 'SELSKAP':
                    continue
                amount = item.get('resultatregnskapResultat', {}).get('driftsresultat', {}).get('driftsinntekter', {}).get('sumDriftsinntekter')
                if type(amount) not in (int, float) or not math.isfinite(amount):
                    continue
                if not item.get('valuta') or not item.get('regnskapsperiode'):
                    continue
                value = {'amount': amount, 'currency': item['valuta'], 'period': item['regnskapsperiode'],
                         'account_scope': 'entity', 'normalization': 'raw_source_currency_units'}
                record['claims'].append({'canonical_id': subject + ':annual_revenue:' + str(item['id']),
                                         'field': 'annual_revenue', 'family': 'financials_history', 'value': value,
                                         'scope': 'entity_accounts', 'source_sha256': receipt['sha256'],
                                         'source_url': receipt['source_url'], 'source_path': receipt['path'],
                                         'retrieved_at': receipt['retrieved_at'], 'locator': index})
                positive = True
            record['opportunities']['financials_history'] = 'positive' if positive else 'unknown'
    return [records[s] for s in subjects]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--organisations', type=Path, required=True)
    parser.add_argument('--registry', type=Path, required=True)
    parser.add_argument('--acquisition-manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    subjects = [strict_json(line)['organisation_number'] for line in args.organisations.read_text(encoding='utf-8').splitlines() if line.strip()]
    rows = {}
    with gzip.open(args.registry, 'rb') as stream:
        for line in stream:
            row = strict_json(line)
            if row['organisation_number'] in subjects:
                rows[row['organisation_number']] = row
    receipts = strict_json(args.acquisition_manifest.read_bytes())
    reference = build_reference(subjects, rows, receipts, args.acquisition_manifest.parent)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='\n') as stream:
        for record in reference:
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n')
    print(json.dumps({'status': 'reference_prepared', 'companies': len(reference),
                      'pool_sha256': sha(args.output.read_bytes()), 'independent_human_review': False}))


if __name__ == '__main__':
    main()
