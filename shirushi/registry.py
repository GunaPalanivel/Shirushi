"""Select exact subjects from hash-verified frozen JSONL or BRREG CSV."""
import csv
import gzip
import hashlib
import io
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .contracts import loads, timestamp, validate_inputs
from .snapshots import canonical, digest

MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_EXPANDED_BYTES = 2 * 1024 * 1024 * 1024
MAX_ROW_BYTES = 1024 * 1024


def check_receipt(receipt):
    if not isinstance(receipt, dict):
        raise ValueError('Registry receipt must be an object')
    if receipt.get('source_class') != 'frozen_registry':
        raise ValueError('Receipt must identify frozen_registry')
    if receipt.get('dataset_format', 'jsonl') not in ('jsonl', 'csv'):
        raise ValueError('Registry format must be jsonl or csv')
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
    if receipt.get('dataset_format') == 'csv':
        def lines():
            nonlocal total
            while True:
                if deadline is not None and time.monotonic() > deadline:
                    raise ValueError('Registry verification deadline exceeded')
                line = stream.readline(MAX_ROW_BYTES + 1)
                if not line:
                    break
                total += len(line)
                if len(line) > MAX_ROW_BYTES or total > MAX_EXPANDED_BYTES:
                    raise ValueError('Registry expansion exceeds declared bound')
                hasher.update(line)
                yield line.decode('utf-8-sig' if total == len(line) else 'utf-8')
        with stream:
            source = lines()
            header = next(source, '')
            dialect = csv.Sniffer().sniff(header, delimiters=';,\t')
            fields = next(csv.reader([header], dialect=dialect))
            if len(fields) != len(set(fields)) or 'organisasjonsnummer' not in fields:
                raise ValueError('CSV needs unique BRREG column names')
            # Header-only sniffing identifies the separator but cannot observe
            # escaped quotes in later values. BRREG uses doubled CSV quotes.
            reader = csv.DictReader(source, fieldnames=fields, dialect=dialect, doublequote=True, strict=True)
            for index, row in enumerate(reader, 1):
                if None in row or any(v is None for v in row.values()):
                    raise ValueError('CSV row width differs from header')
                subject = row['organisasjonsnummer']
                if re.fullmatch('[0-9]{9}', subject) is None:
                    raise ValueError('Invalid CSV organisation number')
                if subject in wanted:
                    if subject in found:
                        raise ValueError('Duplicate requested subject in registry')
                    # Retain every parsed column, not a maker projection. The
                    # checker reselects it from the complete original archive.
                    found[subject] = (canonical(row), index)
        if hasher.hexdigest() != receipt['uncompressed_sha256']:
            raise ValueError('Expanded registry hash mismatch')
        return found
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
    expected = 'csv' if path.name.endswith(('.csv', '.csv.gz')) else 'jsonl'
    if not path.name.endswith(('.jsonl', '.jsonl.gz', '.csv', '.csv.gz')):
        raise ValueError('Registry must be JSONL or CSV, optionally gzip compressed')
    if receipt.get('dataset_format', 'jsonl') != expected:
        raise ValueError('Registry suffix and receipt format differ')
    data = path.read_bytes()
    rows = find_rows(data, receipt, subjects, compressed, deadline)
    parent = store.put('objects', data)
    results = {}
    for subject, (row, index) in rows.items():
        metadata = dict(receipt, parent_sha256=parent, row_number=index,
                        compressed=compressed, organisation_number=subject,
                        snapshot_kind='registry_' + expected)
        results[subject] = store.save(row, metadata)
    return results
