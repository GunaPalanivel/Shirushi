"""Immutable, content-addressed source bytes and acquisition receipts."""
import hashlib
import json
import re
import os
from pathlib import Path

from .contracts import loads
from .artifacts import publish_new


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


class SnapshotStore:
    def __init__(self, root):
        self.root = Path(root)
        setting = os.environ.get('SHIRUSHI_STORE_BYTE_LIMIT')
        self.byte_limit = int(setting) if setting is not None else None
        if self.byte_limit is not None and not 0 < self.byte_limit <= 9_000_000_000:
            raise ValueError('Snapshot byte limit must be positive and <= 9000000000')
        self.used = sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file()) if self.byte_limit is not None else 0
        if self.byte_limit is not None and self.used > self.byte_limit:
            raise ValueError('Existing snapshots exceed declared byte limit')

    def path(self, kind, identity):
        if not isinstance(identity, str) or re.fullmatch(r'[0-9a-f]{64}', identity) is None:
            raise ValueError('Invalid snapshot hash')
        return self.root / kind / (identity + ('.json' if kind == 'receipts' else '.bin'))

    def put(self, kind, data):
        identity = digest(data)
        path = self.path(kind, identity)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != data:
                raise ValueError('Existing snapshot has been corrupted')
            return identity
        if self.byte_limit is not None and not path.exists() and self.used + len(data) > self.byte_limit:
            raise ValueError('Snapshot byte limit exhausted')
        try:
            publish_new(path, data)
            if self.byte_limit is not None:
                self.used += len(data)
        except FileExistsError:
            if path.read_bytes() != data:
                raise ValueError('Existing snapshot has been corrupted')
        return identity

    def read(self, kind, identity):
        data = self.path(kind, identity).read_bytes()
        if digest(data) != identity:
            raise ValueError('Snapshot hash mismatch')
        return data

    def save(self, row, receipt):
        metadata = dict(receipt, content_sha256=self.put('objects', row))
        return self.put('receipts', canonical(metadata))

    def open(self, identity):
        receipt = loads(self.read('receipts', identity))
        if not isinstance(receipt, dict):
            raise ValueError('Snapshot receipt must be an object')
        return self.read('objects', receipt['content_sha256']), receipt
