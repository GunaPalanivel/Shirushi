"""Read one exact legal subject from a hash-verified frozen JSONL archive."""
import gzip
import hashlib
import io
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .contracts import loads, timestamp, validate_inputs
from .snapshots import digest

MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_ROW_BYTES = 1024 * 1024


def check_receipt(receipt):
    if not isinstance(receipt, dict):
        raise ValueError('Registry receipt must be an object')
    if receipt.get('source_class') != 'frozen_registry':
        raise ValueError('Receipt must identify frozen_registry')
    if not isinstance(receipt.get('source_url'), str):
        raise ValueError('Registry receipt needs a source URL')
    url = urlsplit(receipt['source_url'])
    if url.scheme != 'https' or not url.hostname or url.username or url.password:
        raise ValueError('Registry source must be a credential-free HTTPS URL')
    if timestamp(receipt.get('retrieved_at')) > datetime.now(timezone.utc):
        raise ValueError('Acquisition timestamp is in the future')
    for key in ('sha256', 'uncompressed_sha256'):
        if not isinstance(receipt.get(key), str) or re.fullmatch(r'[0-9a-f]{64}', receipt[key]) is None:
            raise ValueError('Invalid registry receipt hash: ' + key)


def find_rows(data, receipt, subjects, compressed, deadline=None):
    """Verify the complete stream; retain the exact row, including framing bytes."""
    check_receipt(receipt)
    if len(data) > MAX_ARCHIVE_BYTES or digest(data) != receipt['sha256']:
        raise ValueError('Registry archive size or hash mismatch')
    stream = gzip.GzipFile(fileobj=io.BytesIO(data)) if compressed else io.BytesIO(data)
    found = {}
    wanted = set(subjects)
    total, hasher = 0, hashlib.sha256()
    with stream:
        index = 0
        while True:
            if deadline is not None and time.monotonic() > deadline:
                raise ValueError('Registry verification deadline exceeded')
            line = stream.readline(MAX_ROW_BYTES + 1)
            if not line:
                break
            index += 1
            total += len(line)
            if len(line) > MAX_ROW_BYTES or total > MAX_EXPANDED_BYTES:
                raise ValueError('Registry expansion exceeds local bound')
            hasher.update(line)
            if not line.strip():
                continue
            row = loads(line)
            errors, identities = validate_inputs([row])
            if errors:
                raise ValueError(f'Invalid registry identity at row {index}')
            if identities[0] in wanted:
                if identities[0] in found:
                    raise ValueError('Duplicate requested subject in registry')
                found[identities[0]] = (line, index)
    if hasher.hexdigest() != receipt['uncompressed_sha256']:
        raise ValueError('Expanded registry hash mismatch')
    return found


def find_row(data, receipt, organisation_number, compressed, deadline=None):
    found = find_rows(data, receipt, [organisation_number], compressed, deadline)
    if organisation_number not in found:
        raise ValueError('Requested subject absent from frozen registry')
    return found[organisation_number]


def acquire(path, receipt, organisation_number, store, deadline):
    results = acquire_batch(path, receipt, [organisation_number], store, deadline)
    if organisation_number not in results:
        raise ValueError('Requested subject absent from frozen registry')
    return results[organisation_number]


def acquire_batch(path, receipt, subjects, store, deadline):
    path = Path(path)
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError('Registry archive exceeds local bound')
    compressed = path.name.endswith('.gz')
    if not (path.name.endswith('.jsonl') or path.name.endswith('.jsonl.gz')):
        raise ValueError('Only JSONL and JSONL.GZ registry inputs are supported')
    data = path.read_bytes()
    rows = find_rows(data, receipt, subjects, compressed, deadline)
    parent = store.put('objects', data)
    results = {}
    for subject, (row, index) in rows.items():
        metadata = dict(receipt, parent_sha256=parent, row_number=index,
                        compressed=compressed, organisation_number=subject,
                        snapshot_kind='registry_jsonl')
        results[subject] = store.save(row, metadata)
    return results
