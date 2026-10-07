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


@dataclass(frozen=True)
class Candidate:
    organisation_number: str
    field: str
    value: object
    snapshot_id: str


def extract(store, snapshot_id):
    raw, receipt = store.open(snapshot_id)
    row = loads(raw)
    return [Candidate(receipt['organisation_number'], field, row.get(key), snapshot_id)
            for field, key in PROJECTIONS.items()]
