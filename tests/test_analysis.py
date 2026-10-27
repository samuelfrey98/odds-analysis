from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import random
import unittest

from odds_analysis.adapters.csv_input import load_csv
from odds_analysis.comparison import analyze
from odds_analysis.models import LoadedQuotes, Quote, utc_datetime
from odds_analysis.reporting import render_json

AS_OF = utc_datetime("2030-01-15T12:05:00Z")
START = utc_datetime("2030-01-15T20:00:00Z")
OBSERVED = utc_datetime("2030-01-15T12:00:00Z")
FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "synthetic_quotes.csv"


def quote(**changes):
    values = dict(event_id="demo-001", event_start=START, observed_at=OBSERVED,
                  sport="nba", player="Alex Example", market="player_points",
                  line=Decimal("24.5"), side="over", book="Reference",
                  american_odds=-110, source_row=2)
    values.update(changes)
    return Quote(**values)


def report_for(quotes, **options):
    return analyze(LoadedQuotes(tuple(quotes), (), len(quotes)), as_of=AS_OF,
                   reference_book="Reference", target_book="Target", **options)


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.base = [quote(), quote(side="under", source_row=3),
                     quote(book="Target", american_odds=120, source_row=4)]

    def test_same_line_uses_margin_removed_probabilities(self):
        result = report_for(self.base).comparisons[0]
        self.assertEqual(result.status, "gap")
        self.assertAlmostEqual(result.reference_probability, 0.5)
        self.assertAlmostEqual(result.gap_pp, 100*(0.5 - 5/11))
        self.assertEqual(result.reference_observed_at, OBSERVED.isoformat())

    def test_threshold_and_nonpositive_gaps(self):
        self.assertEqual(report_for(self.base, min_gap_pp=5).comparisons[0].status, "within_threshold")
        zero_gap = self.base[:2] + [replace(self.base[2], american_odds=100)]
        self.assertEqual(report_for(zero_gap, min_gap_pp=0).comparisons[0].status, "within_threshold")

    def test_different_thresholds_never_get_probability_gaps(self):
        data = self.base[:2] + [replace(self.base[2], line=Decimal("22.5"))]
        result = report_for(data).comparisons[0]
        self.assertEqual(result.status, "different_line")
        self.assertIsNone(result.gap_pp)
        self.assertIsNone(result.reference_probability)

    def test_incomplete_reference_never_uses_single_side(self):
        result = report_for([self.base[0], self.base[2]])
        self.assertEqual(result.comparisons[0].status, "no_reference")
        self.assertIn("incomplete_reference", [i.code for i in result.issues])

    def test_new_incomplete_reference_does_not_reuse_old_complete_pair(self):
        newer = replace(self.base[0], observed_at=OBSERVED + timedelta(minutes=1))
        result = report_for(self.base + [newer])
        self.assertEqual(result.comparisons[0].status, "no_reference")

    def test_two_reference_sides_must_share_timestamp(self):
        data = [self.base[0], replace(self.base[1], observed_at=OBSERVED + timedelta(seconds=1)), self.base[2]]
        self.assertEqual(report_for(data).comparisons[0].status, "no_reference")

    def test_same_name_in_different_events_never_matches(self):
        data = self.base[:2] + [replace(self.base[2], event_id="other-event")]
        self.assertEqual(report_for(data).comparisons[0].status, "no_reference")

    def test_duplicate_and_superseded_quotes_do_not_create_extra_comparisons(self):
        old = replace(self.base[2], observed_at=OBSERVED - timedelta(minutes=1), american_odds=-110)
        repeated = replace(self.base[2], source_row=5)
        result = report_for(self.base + [old, repeated])
        self.assertEqual(len(result.comparisons), 1)
        self.assertEqual(result.comparisons[0].target_odds, 120)
        self.assertEqual([i.code for i in result.issues], ["duplicate_row"])

    def test_conflicting_price_does_not_fall_back_to_old_target(self):
        old = replace(self.base[2], observed_at=OBSERVED - timedelta(minutes=1))
        conflicting = replace(self.base[2], american_odds=150, source_row=5)
        result = report_for(self.base + [old, conflicting])
        self.assertEqual(result.comparisons, ())
        self.assertEqual(sum(i.code == "conflicting_quote" for i in result.issues), 2)

    def test_reference_conflict_blocks_comparison(self):
        conflicting = replace(self.base[0], american_odds=-120, source_row=5)
        self.assertEqual(report_for(self.base + [conflicting]).comparisons[0].status, "no_reference")

    def test_stale_future_and_started_records_are_excluded(self):
        cases = [
            (dict(observed_at=AS_OF - timedelta(minutes=16)), "stale_quote"),
            (dict(observed_at=AS_OF + timedelta(seconds=1)), "future_quote"),
            (dict(event_start=AS_OF), "event_started"),
        ]
        for changes, code in cases:
            with self.subTest(code=code):
                result = report_for([replace(self.base[2], **changes)])
                self.assertFalse(result.comparisons)
                self.assertEqual(result.issues[0].code, code)

    def test_age_boundary_is_inclusive(self):
        target = replace(self.base[2], observed_at=AS_OF - timedelta(minutes=15))
        result = report_for(self.base[:2] + [target])
        self.assertEqual(len(result.comparisons), 1)

    def test_event_start_conflict_excludes_all_records_for_event(self):
        target = replace(self.base[2], event_start=START + timedelta(hours=1))
        result = report_for(self.base[:2] + [target])
        self.assertFalse(result.comparisons)
        self.assertEqual(sum(i.code == "event_conflict" for i in result.issues), 3)

    def test_synthetic_fixture_demonstrates_expected_outcomes(self):
        loaded = load_csv(FIXTURE)
        result = analyze(loaded, as_of=AS_OF, reference_book="Reference", target_book="Target")
        self.assertEqual(loaded.input_rows, 19)
        self.assertEqual(len(loaded.quotes), 18)
        self.assertEqual([c.status for c in result.comparisons], ["gap", "within_threshold", "different_line", "no_reference"])
        codes = [i.code for i in result.issues]
        for code in ("invalid_row", "duplicate_row", "stale_quote", "future_quote", "event_started", "incomplete_reference"):
            self.assertIn(code, codes)

    def test_report_is_deterministic_for_input_order(self):
        loaded = load_csv(FIXTURE)
        shuffled = list(loaded.quotes)
        random.Random(42).shuffle(shuffled)
        first = analyze(loaded, as_of=AS_OF, reference_book="Reference", target_book="Target")
        second = analyze(replace(loaded, quotes=tuple(shuffled)), as_of=AS_OF, reference_book="Reference", target_book="Target")
        self.assertEqual(render_json(first), render_json(second))

    def test_invalid_policy_is_rejected(self):
        for options in [dict(max_age=timedelta(0)), dict(min_gap_pp=-1), dict(min_gap_pp=float("nan"))]:
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    report_for(self.base, **options)


class ModelTests(unittest.TestCase):
    def test_invalid_values_and_push_lines_are_rejected(self):
        for changes in [dict(line="24"), dict(line="-0.5"), dict(line="NaN"), dict(side="either"), dict(player=" "), dict(american_odds=""), dict(observed_at="2030-01-15T12:00:00")]:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    quote(**changes)

    def test_timezones_and_whitespace_normalize(self):
        result = quote(observed_at="2030-01-15T07:00:00-05:00", player=" Alex   Example ", sport=" NBA ")
        self.assertEqual(result.observed_at, OBSERVED)
        self.assertEqual(result.player, "Alex Example")
        self.assertEqual(result.sport, "nba")
