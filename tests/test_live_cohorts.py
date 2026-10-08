"""Prevent a repeated cohort or damaged summary from posing as validation."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shirushi.snapshots import digest
from tools.validate_live_cohorts import validate


class CohortTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def save(self, name, subject):
        directory = self.root / name
        directory.mkdir()
        raw = (json.dumps({'organisation_number': subject}) + '\n').encode()
        (directory / 'input.jsonl').write_bytes(raw)
        (directory / 'config.json').write_bytes(b'{}')
        result = {'status': 'PASS', 'input_count': 1, 'output_count': 1,
                  'artifact_binding': {'input_sha256': digest(raw), 'config_sha256': digest(b'{}'),
                                       'code_sha256': 'a' * 64},
                  'financial_comparison': {'missing_source_facts': 0, 'unsupported_publications': 0,
                                           'additional_facts': 1,
                                           'reference_diagnostics': {'invalid_records': 0, 'conflicting_slots': 0, 'invalid_amounts': 0}}}
        (directory / 'validation.json').write_text(json.dumps(result))
        return directory

    def test_distinct_successful_cohorts_pass_and_overlap_fails(self):
        first = self.save('first', '923609016')
        second = self.save('second', '989061593')
        with patch('builtins.print'):
            validate([first, second])
        overlap = self.save('overlap', '923609016')
        with self.assertRaisesRegex(ValueError, 'overlap'):
            validate([first, overlap])

    def test_changed_manifest_invalidates_the_summary(self):
        first = self.save('first', '923609016')
        second = self.save('second', '989061593')
        (second / 'input.jsonl').write_text(json.dumps({'organisation_number': '999999999'}) + '\n')
        with self.assertRaisesRegex(ValueError, 'binding'):
            validate([first, second])

    def test_no_gain_unsupported_claim_or_different_code_cannot_pass_promotion(self):
        first = self.save('first', '923609016')
        second = self.save('second', '989061593')
        path = second / 'validation.json'
        original = path.read_text()
        for section, field, value in [('financial_comparison', 'additional_facts', 0),
                                       ('financial_comparison', 'unsupported_publications', 1),
                                       ('artifact_binding', 'code_sha256', 'b' * 64)]:
            result = json.loads(original)
            result[section][field] = value
            path.write_text(json.dumps(result))
            with self.assertRaises(ValueError):
                validate([first, second])


if __name__ == '__main__':
    unittest.main()
