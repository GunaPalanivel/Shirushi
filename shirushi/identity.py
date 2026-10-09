"""Source-checked legal identity for external routes, including frozen anchors."""
from .contracts import loads
from .evidence import EvidenceChecker
from .snapshots import digest


def legal_anchor(store, snapshot_id, subject, checker=None):
    raw, receipt = store.open(snapshot_id)
    if receipt.get('source_class') == 'frozen_registry':
        checker = checker or EvidenceChecker(store, [subject])
        _, _, row = checker.verify_source(snapshot_id, subject)
        csv = receipt['snapshot_kind'] == 'registry_csv'
        name = row.get('navn' if csv else 'name')
        website = row.get('hjemmeside' if csv else 'website')
        if not isinstance(name, str) or not name.strip():
            raise ValueError('Frozen legal identity requires a nonblank name')
        return {'organisasjonsnummer': subject, 'navn': name,
                'hjemmeside': website if isinstance(website, str) else '',
                'epostadresse': row.get('epostadresse') if csv else row.get('email')}
    row = loads(raw)
    url = 'https://data.brreg.no/enhetsregisteret/api/enheter/' + subject
    if (receipt.get('source_class') != 'brreg_entity' or receipt.get('organisation_number') != subject
            or receipt.get('http_status') != 200 or receipt.get('source_url') != url
            or receipt.get('sha256') != digest(raw) or row.get('organisasjonsnummer') != subject
            or not isinstance(row.get('navn'), str) or not row['navn'].strip()):
        raise ValueError('Legal identity anchor mismatch')
    return row
