"""Publish complete bytes atomically without overwriting an existing artifact."""
import os
import json
import tempfile
from pathlib import Path


def publish_new(path, data):
    path = Path(path)
    roots = os.environ.get('SHIRUSHI_ARTIFACT_ROOTS')
    store = os.environ.get('SHIRUSHI_QUOTA_STORE')
    if roots and store:
        store = Path(store).resolve()
        if store != path.resolve() and store not in path.resolve().parents:
            used = 0
            for root in map(Path, json.loads(roots)):
                if root.is_file():
                    used += root.stat().st_size
                elif root.is_dir():
                    for folder, directories, files in os.walk(root):
                        directories[:] = [name for name in directories if (Path(folder) / name).resolve() != store]
                        used += sum((Path(folder) / name).stat().st_size for name in files)
            if used + len(data) > 500_000_000:
                raise ValueError('Non-snapshot artifact byte limit exhausted')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.pending-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # A same-directory hard link makes the entire file visible at once and
        # fails if the destination exists, on NTFS and normal Linux filesystems.
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
