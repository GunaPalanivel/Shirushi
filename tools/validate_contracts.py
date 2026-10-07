"""CLI wrapper for shared configuration and envelope validation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shirushi.contracts import (ROOT, load, main, timestamp, validate_config,
                               validate_envelopes, validate_inputs)  # noqa: E402,F401

if __name__ == '__main__':
    raise SystemExit(main())
