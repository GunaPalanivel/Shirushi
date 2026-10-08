import unittest

from shirushi_eval.paired_coverage import clopper_pearson, holm, mcnemar, paired


class PairedCoverageTests(unittest.TestCase):
    def test_five_gains_are_not_significant(self):
        self.assertEqual(mcnemar(5, 0), 0.0625)
        self.assertEqual(mcnemar(0, 5), 0.0625)
        self.assertEqual(mcnemar(0, 0), 1)
        self.assertEqual(mcnemar(5, 5), 1)

    def test_gains_losses_and_denominator_are_explicit(self):
        control = {str(i): i < 2 for i in range(100)}
        challenger = {str(i): 1 <= i < 8 for i in range(100)}
        result = paired(control, challenger)
        self.assertEqual(result['additional_covered_companies'], 6)
        self.assertEqual(result['lost_covered_companies'], 1)
        self.assertEqual(result['gain_percentage_points'], 5)
        self.assertIsNone(result['official_score'])
        self.assertLess(result['simultaneous_95_percent_gain_interval_pp'][0], 5)
        self.assertGreater(result['simultaneous_95_percent_gain_interval_pp'][1], 5)

    def test_exact_interval_extremes_and_multiple_testing(self):
        low, high = clopper_pearson(0, 10, 0.05)
        self.assertEqual(low, 0)
        self.assertAlmostEqual(high, 1 - 0.025 ** 0.1)
        low, high = clopper_pearson(10, 10, 0.05)
        self.assertEqual(high, 1)
        self.assertAlmostEqual(low, 0.025 ** 0.1)
        self.assertEqual(holm({'products': 0.01, 'activity': 0.04}), {'products': 0.02, 'activity': 0.04})

    def test_incomparable_and_unknown_outcomes_are_rejected(self):
        for control, challenger in [({}, {}), ({'a': True}, {'b': True}), ({'a': None}, {'a': False})]:
            with self.assertRaises(ValueError):
                paired(control, challenger)
