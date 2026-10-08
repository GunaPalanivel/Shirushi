"""Immutable, content-addressed source bytes and acquisition receipts."""
import hashlib
import json
import re
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

    def path(self, kind, identity):
        if not isinstance(identity, str) or re.fullmatch(r'[0-9a-f]{64}', identity) is None:
            raise ValueError('Invalid snapshot hash')
        return self.root / kind / (identity + ('.json' if kind == 'receipts' else '.bin'))

    def put(self, kind, data):
        identity = digest(data)
        path = self.path(kind, identity)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            publish_new(path, data)
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
