"""Lossless published-contract field aliases; never infer new facts."""
from copy import deepcopy


def convert(envelopes, external=True):
    result = deepcopy(envelopes)
    old, new = ('verified_website', 'official_website') if external else ('official_website', 'verified_website')
    for envelope in result:
        for section in ('claims', 'history', 'changes'):
            for item in envelope.get(section, []):
                if item.get('field') == old:
                    item['field'] = new
    # Canonical IDs stay stable across the serialization boundary. Recomputing
    # them would manufacture changes on refresh. Evidence bytes stay untouched.
    return result
