import math
import unittest

from odds_analysis.odds import (
    american_to_probability, expected_return, probability_to_american,
    proportional_devig,
)


class OddsTests(unittest.TestCase):
    def test_known_probabilities_and_round_trips(self):
        for odds, expected in [(-200, 2/3), (-110, 11/21), (100, 0.5), (150, 0.4)]:
            with self.subTest(odds=odds):
                self.assertAlmostEqual(american_to_probability(odds), expected)
                self.assertAlmostEqual(probability_to_american(expected), odds)
        self.assertEqual(probability_to_american(0.5), 100)

    def test_invalid_odds_are_rejected(self):
        for value in (0, 50, -99, math.nan, math.inf, -math.inf, True, None, "private-value"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    american_to_probability(value)

    def test_invalid_probabilities_are_rejected(self):
        for value in (0, 1, -0.01, 1.01, math.nan, math.inf, True, None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    probability_to_american(value)

    def test_devig_known_two_sided_markets(self):
        self.assertEqual(proportional_devig(-110, -110), (0.5, 0.5))
        over, under = proportional_devig(-120, 100)
        self.assertAlmostEqual(over, 12/23)
        self.assertAlmostEqual(under, 11/23)
        self.assertAlmostEqual(over + under, 1)

    def test_expected_return_is_conditional_on_probability(self):
        self.assertEqual(expected_return(0.5, 100), 0)
        self.assertAlmostEqual(expected_return(0.5, 120), 0.1)
        self.assertEqual(expected_return(0, -110), -1)
        self.assertAlmostEqual(expected_return(1, -200), 0.5)
        with self.assertRaises(ValueError):
            expected_return(1.1, 100)
