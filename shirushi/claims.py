"""Stable fact slots; asserted values do not participate in slot identity."""
from .snapshots import canonical, digest


def claim_id(subject, field, scope, item_key=None, period=None):
    return digest(canonical([subject, field, scope, item_key, period]))


def slot(claim):
    return claim.get('claim_id', claim['field'])
