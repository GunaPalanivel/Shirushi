"""Evidence-rich output must not inherit the identity-input size limit."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shirushi.run import MAX_INPUT_BYTES, read_envelopes, read_records


class ArtifactReadingTests(unittest.TestCase):
    def test_large_output_can_be_read_for_audit_and_refresh_without_relaxing_input_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'envelopes.jsonl'
            rows = [{'organisation_number': str(900000000 + i),
                     'claims': [{'field': 'business_description', 'value': 'x' * 300000}]}
                    for i in range(8)]
            path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
            self.assertGreater(path.stat().st_size, MAX_INPUT_BYTES)
            self.assertEqual(read_envelopes(path), rows)
            with self.assertRaises(ValueError):
                read_records(path)
            with patch('shirushi.run.MAX_STATE_BYTES', 1000):
                with self.assertRaises(ValueError):
                    read_envelopes(path)


if __name__ == '__main__':
    unittest.main()
