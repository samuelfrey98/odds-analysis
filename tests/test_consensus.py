from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta
from decimal import Decimal
from io import StringIO
import json
from pathlib import Path
import random
import unittest

from odds_analysis.adapters.csv_input import load_csv
from odds_analysis.cli import main
from odds_analysis.comparison import analyze
from odds_analysis.models import LoadedQuotes, Quote, utc_datetime
from odds_analysis.reporting import render_json, render_markdown

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "consensus_quotes.csv"
AS_OF = utc_datetime("2030-01-15T12:05:00Z")
OBSERVED = AS_OF - timedelta(minutes=5)
START = utc_datetime("2030-01-15T20:00:00Z")


def quote(book="Target", **changes):
    values = dict(event_id="event-001", event_start=START, observed_at=OBSERVED,
                  sport="nba", player="Alex Example", market="player_points",
                  line=Decimal("24.5"), side="over", book=book,
                  american_odds=120)
    values.update(changes)
    return Quote(**values)


def pair(book, over=-110, under=-110, **changes):
    return [quote(book, side="over", american_odds=over, **changes),
            quote(book, side="under", american_odds=under, **changes)]


def report(quotes, books=("A", "B", "C"), **options):
    return analyze(LoadedQuotes(tuple(quotes), (), len(quotes)), as_of=AS_OF,
                   reference_books=books, target_book="Target", **options)


class ConsensusTests(unittest.TestCase):
    def setUp(self):
        self.data = pair("A") + pair("B", -120, 100) + pair("C", 100, -120) + [quote()]

    def test_median_uses_each_books_margin_free_probability(self):
        result = report(self.data).comparisons[0]
        self.assertAlmostEqual(result.reference_probability, 0.5)
        self.assertAlmostEqual(result.reference_spread_pp, 100/23)
        self.assertEqual(result.reference_count, 3)
        self.assertEqual([c.book for c in result.reference_contributions], ["A", "B", "C"])
        self.assertAlmostEqual(result.reference_contributions[1].probability, 12/23)
        self.assertEqual(result.status, "gap")
        self.assertIsNone(result.reference_observed_at)

    def test_even_count_median_is_midpoint_in_probability_space(self):
        result = report(pair("A") + pair("B", -120, 100) + [quote()], books=("A", "B")).comparisons[0]
        self.assertAlmostEqual(result.reference_probability, (0.5 + 12/23)/2)

    def test_an_extreme_book_does_not_move_three_book_median(self):
        data = pair("A") + pair("B") + pair("C", -900, 900) + [quote()]
        result = report(data, max_disagreement_pp=100).comparisons[0]
        self.assertAlmostEqual(result.reference_probability, 0.5)
        self.assertEqual(result.reference_count, 3)
        self.assertEqual(result.status, "gap")

    def test_under_and_over_consensus_are_complementary_for_even_count(self):
        data = pair("A") + pair("B", -120, 100) + [quote(), quote(side="under")]
        results = report(data, books=("A", "B")).comparisons
        self.assertAlmostEqual(sum(c.reference_probability for c in results), 1)
        self.assertAlmostEqual(results[0].reference_spread_pp, results[1].reference_spread_pp)

    def test_many_snapshots_and_duplicate_rows_do_not_add_votes(self):
        data = self.data + pair("A", observed_at=OBSERVED - timedelta(minutes=1)) + pair("A")
        result = report(data).comparisons[0]
        self.assertEqual(result.reference_count, 3)
        self.assertAlmostEqual(result.reference_probability, 0.5)

    def test_multiple_configured_books_default_to_two_required(self):
        result = report(pair("A") + [quote()])
        comparison = result.comparisons[0]
        self.assertEqual(result.min_reference_books, 2)
        self.assertEqual(comparison.status, "insufficient_references")
        self.assertIsNone(comparison.reference_probability)
        self.assertIsNone(comparison.gap_pp)
        self.assertEqual(comparison.reference_count, 1)

    def test_explicit_one_book_minimum_allows_partial_coverage(self):
        result = report(pair("A") + [quote()], min_reference_books=1).comparisons[0]
        self.assertEqual(result.status, "gap")
        self.assertEqual(len(result.reference_exclusions), 2)

    def test_minimum_can_require_every_configured_book(self):
        result = report(pair("A") + pair("B") + [quote()], min_reference_books=3).comparisons[0]
        self.assertEqual(result.status, "insufficient_references")

    def test_disagreement_suppresses_gap_but_shows_median_and_all_books(self):
        data = pair("A") + pair("B", -200, 200) + pair("C", -300, 300) + [quote()]
        result = report(data).comparisons[0]
        self.assertEqual(result.status, "reference_disagreement")
        self.assertAlmostEqual(result.reference_probability, 2/3)
        self.assertAlmostEqual(result.reference_spread_pp, 25)
        self.assertIsNone(result.gap_pp)
        self.assertEqual(result.reference_count, 3)

    def test_disagreement_boundary_is_inclusive(self):
        data = pair("A") + pair("B", -150, 150) + [quote()]
        at_boundary = report(data, books=("A", "B"), max_disagreement_pp=10).comparisons[0]
        below_boundary = report(data, books=("A", "B"), max_disagreement_pp=9.99).comparisons[0]
        self.assertEqual(at_boundary.status, "gap")
        self.assertEqual(below_boundary.status, "reference_disagreement")

    def test_zero_range_limit_allows_identical_probabilities(self):
        result = report(pair("A") + pair("B") + [quote()], books=("A", "B"), max_disagreement_pp=0).comparisons[0]
        self.assertEqual(result.status, "gap")
        self.assertEqual(result.reference_spread_pp, 0)

    def test_stale_and_other_line_books_are_excluded_with_reasons(self):
        data = pair("A") + pair("B", observed_at=AS_OF-timedelta(hours=1)) + pair("C", line=Decimal("26.5")) + [quote()]
        result = report(data).comparisons[0]
        excluded = {c.book: c for c in result.reference_exclusions}
        self.assertEqual(excluded["B"].reasons, ("stale_quote",))
        self.assertEqual(excluded["C"].reasons, ("different_line",))
        self.assertEqual(excluded["C"].available_lines, ("26.5",))
        self.assertEqual(result.status, "insufficient_references")

    def test_incomplete_book_does_not_block_two_usable_books(self):
        data = pair("A") + pair("B") + [quote("C", american_odds=-110), quote()]
        result = report(data).comparisons[0]
        self.assertEqual(result.status, "gap")
        self.assertEqual(result.reference_count, 2)
        self.assertEqual(result.reference_exclusions[0].reasons, ("incomplete_reference",))

    def test_latest_incomplete_snapshot_does_not_reuse_older_pair(self):
        result = report(self.data + [quote("C", observed_at=OBSERVED+timedelta(minutes=1))]).comparisons[0]
        self.assertEqual(result.reference_count, 2)
        self.assertEqual(result.reference_exclusions[0].reasons, ("incomplete_reference",))

    def test_conflicting_reference_is_excluded_instead_of_getting_a_vote(self):
        result = report(self.data + [quote("C", american_odds=200)]).comparisons[0]
        self.assertEqual(result.reference_count, 2)
        self.assertEqual(result.reference_exclusions[0].reasons, ("conflicting_quote",))

    def test_future_and_missing_books_have_explicit_exclusions(self):
        data = pair("A") + pair("B", observed_at=AS_OF+timedelta(seconds=1)) + [quote()]
        excluded = {c.book: c.reasons for c in report(data).comparisons[0].reference_exclusions}
        self.assertEqual(excluded, {"B": ("future_quote",), "C": ("no_reference",)})

    def test_reference_outcomes_from_different_books_cannot_form_pair(self):
        data = [quote("A", american_odds=-110), quote("B", side="under", american_odds=-110), quote()]
        result = report(data, books=("A", "B")).comparisons[0]
        self.assertEqual(result.status, "no_reference")
        self.assertFalse(result.reference_contributions)

    def test_different_events_and_markets_cannot_contribute(self):
        data = pair("A") + pair("B", event_id="other") + pair("C", market="player_rebounds") + [quote()]
        result = report(data).comparisons[0]
        self.assertEqual(result.reference_count, 1)
        self.assertEqual(result.status, "insufficient_references")

    def test_each_books_timestamp_and_prices_are_preserved(self):
        later = OBSERVED + timedelta(minutes=2)
        data = pair("A") + pair("B", -120, 100, observed_at=later) + [quote()]
        result = report(data, books=("A", "B")).comparisons[0]
        self.assertEqual(result.reference_contributions[1].observed_at, later.isoformat())
        self.assertEqual(result.reference_contributions[1].over_odds, -120)
        self.assertEqual(result.reference_contributions[1].under_odds, 100)

    def test_single_book_api_is_compatible_and_annotated(self):
        loaded = LoadedQuotes(tuple(pair("A") + [quote()]), (), 3)
        result = analyze(loaded, as_of=AS_OF, reference_book="A", target_book="Target")
        self.assertEqual(result.min_reference_books, 1)
        self.assertEqual(result.comparisons[0].reference_observed_at, OBSERVED.isoformat())
        self.assertEqual(result.comparisons[0].status, "gap")

    def test_configuration_rejects_duplicate_target_empty_or_invalid_books(self):
        for books in [("A", " A "), ("A", "Target"), (), ("",), (1,), "A"]:
            with self.subTest(books=books):
                with self.assertRaises(ValueError):
                    report(self.data, books=books)

    def test_invalid_minimum_and_dispersion_policies_are_rejected(self):
        for options in [dict(min_reference_books=0), dict(min_reference_books=4),
                        dict(min_reference_books=True), dict(min_reference_books=1.5),
                        dict(max_disagreement_pp=-1), dict(max_disagreement_pp=101),
                        dict(max_disagreement_pp=float("nan"))]:
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    report(self.data, **options)

    def test_ambiguous_old_and_new_reference_api_arguments_are_rejected(self):
        with self.assertRaises(ValueError):
            report(self.data, reference_book="A")

    def test_report_is_invariant_to_book_selection_and_input_order(self):
        data = self.data.copy()
        random.Random(14).shuffle(data)
        self.assertEqual(render_json(report(self.data)), render_json(report(data, books=("C", "B", "A"))))

    def test_fixture_covers_agreement_disagreement_quorum_and_exclusions(self):
        result = analyze(load_csv(FIXTURE), as_of=AS_OF,
                         reference_books=["Reference A", "Reference B", "Reference C"], target_book="Target")
        self.assertEqual(result.input_rows, 28)
        self.assertEqual([c.status for c in result.comparisons],
                         ["gap", "within_threshold", "reference_disagreement", "insufficient_references", "gap"])
        payload = json.loads(render_json(result))
        self.assertEqual(payload["schema_version"], 2)
        self.assertEqual(payload["consensus_method"], "median")
        self.assertIn("reference_contributions", payload["comparisons"][0])
        self.assertIn("reference_exclusions", payload["comparisons"][3])

    def test_markdown_example_is_reproducible_and_shows_evidence(self):
        result = analyze(load_csv(FIXTURE), as_of=AS_OF,
                         reference_books=["Reference A", "Reference B", "Reference C"], target_book="Target")
        content = render_markdown(result)
        self.assertIn("## Reference evidence", content)
        self.assertIn("stale_quote", content)
        self.assertIn("incomplete_reference", content)
        self.assertEqual((ROOT / "examples" / "consensus-report.md").read_text(), content)

    def test_cli_repeated_reference_options_and_json_contract(self):
        output = StringIO()
        args = [str(FIXTURE), "--as-of", AS_OF.isoformat(), "--format", "json"]
        for book in ("Reference A", "Reference B", "Reference C"):
            args.extend(["--reference-book", book])
        with redirect_stdout(output):
            self.assertEqual(main(args), 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["reference_books"], ["Reference A", "Reference B", "Reference C"])
        self.assertEqual(payload["min_reference_books"], 2)

    def test_cli_rejects_invalid_consensus_options_without_traceback(self):
        for options in [["--reference-book", "Target"], ["--min-reference-books", "2"],
                        ["--max-disagreement-pp", "nan"], ["--max-disagreement-pp", "101"]]:
            with self.subTest(options=options), redirect_stderr(StringIO()) as error:
                self.assertEqual(main([str(FIXTURE), "--as-of", AS_OF.isoformat()] + options), 2)
                self.assertNotIn("Traceback", error.getvalue())
