"""Lossless published-contract field aliases and derived kit blocks; never infer new facts."""
from copy import deepcopy

from .kitcompat import annotate, strip


def convert(envelopes, external=True, kit=True):
    result = deepcopy(envelopes)
    old, new = ('verified_website', 'official_website') if external else ('official_website', 'verified_website')
    for envelope in result:
        for section in ('claims', 'history', 'changes'):
            for item in envelope.get(section, []):
                if item.get('field') == old:
                    item['field'] = new
        # Kit blocks are a rebuildable view of the claims: drop any earlier copy
        # on the way in or out so the record is never layered twice.
        if external and kit:
            annotate(envelope)
        else:
            strip(envelope)
    # Canonical IDs stay stable across the serialization boundary. Recomputing
    # them would manufacture changes on refresh. Evidence bytes stay untouched.
    return result
