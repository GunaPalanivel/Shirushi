"""Independent audit rejects false support rather than rewarding maker output."""
import copy
import unittest
from unittest.mock import patch

import test_batch_runner as fixtures
from shirushi.contracts import load
from shirushi.run import read_records
from shirushi_eval.reference import FAMILIES
from shirushi_eval.score import evaluate


class PilotEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = fixtures.BatchRunnerTests()
        cls.fixture.setUp()
        cls.addClassCleanup(cls.fixture.doCleanups)
        code, output, report = cls.fixture.cli('audit-fixture')
        if code:
            raise RuntimeError('Synthetic audit fixture failed')
        cls.original = read_records(output)
        cls.report = load(report)
        # Expected values come from fixture input rows, never extracted output.
        cls.reference = [{'organisation_number': r['organisation_number'],
                          'opportunities': {f: 'unknown' for f in FAMILIES},
                          'claims': [{'canonical_id': r['organisation_number'] + ':fixture:employees',
                                      'family': 'business_products', 'scope': 'frozen_registry',
                                      'value': r['employees']}]} for r in cls.fixture.rows]
        for row in cls.reference:
            row['opportunities']['business_products'] = 'positive'

    def setUp(self):
        self.envelopes = copy.deepcopy(self.original)
        self.gold = copy.deepcopy(self.reference)

    def audit(self, report=None):
        return evaluate(self.fixture.subjects, self.envelopes, self.gold,
                        self.report if report is None else report, self.fixture.store.root)

    def employee(self):
        return next(c for c in self.envelopes[0]['claims'] if c['field'] == 'registered_employees')

    def test_independent_audit_never_calls_maker_checker(self):
        with patch('shirushi.evidence.EvidenceChecker.check', side_effect=AssertionError('maker checker used')):
            result = self.audit()
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['audited_supported_claims_including_history'], 160)
        self.assertIsNone(result['official_score'])

    def test_unsupported_value_is_rejected_and_not_counted_as_recall(self):
        self.employee()['value'] = 999
        self.gold[0]['claims'][0]['value'] = 999
        result = self.audit()
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual(result['families']['business_products']['matched_claims'], 19)

    def test_span_for_different_value_is_rejected(self):
        evidence_id = self.employee()['evidence_ids'][0]
        next(e for e in self.envelopes[0]['evidence'] if e['id'] == evidence_id)['claim_span'] = '1'
        self.assertEqual(self.audit()['status'], 'FAIL')

    def test_subject_attribution_is_checked_against_source(self):
        evidence_id = self.employee()['evidence_ids'][0]
        item = next(e for e in self.envelopes[0]['evidence'] if e['id'] == evidence_id)
        item['locator']['organisation_number'] = self.fixture.subjects[1]
        self.assertEqual(self.audit()['status'], 'FAIL')

    def test_orphan_output_is_not_complete_artifact(self):
        report = dict(self.report, artifact_complete=False)
        with self.assertRaisesRegex(ValueError, 'complete batch artifact'):
            self.audit(report)

    def test_duplicate_gold_cannot_inflate_denominator(self):
        self.gold[0]['claims'].append(copy.deepcopy(self.gold[0]['claims'][0]))
        with self.assertRaisesRegex(ValueError, 'Duplicate reference'):
            self.audit()


if __name__ == '__main__':
    unittest.main()
