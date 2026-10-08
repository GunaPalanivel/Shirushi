"""Publish complete bytes atomically without overwriting an existing artifact."""
import os
import tempfile
from pathlib import Path


def publish_new(path, data):
    path = Path(path)
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
