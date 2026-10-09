"""Propose frozen-row values. Proposals are never published directly."""
from dataclasses import dataclass

from .contracts import loads

# This is the maker's projection; the checker has its own acceptance specification.
PROJECTIONS = {
    'legal_name': 'name', 'legal_form': 'legal_form',
    'registered_employees': 'employees', 'registered_municipality': 'municipality',
    'registered_municipality_number': 'municipality_number',
    'industry_code': 'industry_code', 'industry_label': 'industry_label',
    'latest_submitted_accounts_year': 'latest_submitted_accounts',
}

CSV_PROJECTIONS = {
    'legal_name': 'navn', 'legal_form': 'organisasjonsform.kode',
    'registered_employees': 'antallAnsatte', 'registered_municipality': 'forretningsadresse.kommune',
    'registered_municipality_number': 'forretningsadresse.kommunenummer',
    'industry_code': 'naeringskode1.kode', 'industry_label': 'naeringskode1.beskrivelse',
    'latest_submitted_accounts_year': 'sisteInnsendteAarsregnskap',
}


@dataclass(frozen=True)
class Candidate:
    organisation_number: str
    field: str
    value: object
    snapshot_id: str
    locator: dict | None = None


def extract(store, snapshot_id):
    raw, receipt = store.open(snapshot_id)
    row = loads(raw)
    projection = CSV_PROJECTIONS if receipt.get('snapshot_kind') == 'registry_csv' else PROJECTIONS
    candidates = []
    for field, key in projection.items():
        value = row.get(key)
        if field == 'registered_employees' and receipt.get('snapshot_kind') == 'registry_csv':
            try:
                value = int(value) if value else None
            except ValueError:
                pass  # Checker rejects malformed numeric source text.
        candidates.append(Candidate(receipt['organisation_number'], field, value, snapshot_id))
    return candidates
