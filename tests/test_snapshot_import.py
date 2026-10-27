from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import timedelta
import hashlib
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from odds_analysis.adapters.csv_input import load_csv
from odds_analysis.adapters.odds_api import load_snapshot
from odds_analysis.cli import main
from odds_analysis.comparison import analyze
from odds_analysis.import_cli import render_csv, write_import
from odds_analysis.models import LoadedQuotes, utc_datetime

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples" / "saved_event_odds.json"
MAPPING = ROOT / "examples" / "snapshot_mapping.json"
CAPTURED = "2030-01-15T12:05:00Z"


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "source.json"
        self.mapping_path = Path(self.folder.name) / "mapping.json"
        self.data = json.loads(SOURCE.read_text())
        self.mapping = json.loads(MAPPING.read_text())

    def load(self, data=None, mapping=None, **kwargs):
        self.path.write_text(json.dumps(self.data if data is None else data), encoding="utf-8")
        self.mapping_path.write_text(json.dumps(self.mapping if mapping is None else mapping), encoding="utf-8")
        return load_snapshot(self.path, mapping_path=self.mapping_path,
                             captured_at=kwargs.get("captured_at", CAPTURED),
                             odds_format=kwargs.get("odds_format", "american"))

    def market(self):
        return self.data[0]["bookmakers"][0]["markets"][0]

    def test_synthetic_snapshot_normalizes_aliases_and_market_times(self):
        result = self.load()
        self.assertEqual(len(result.entries), 8)
        self.assertFalse(result.issues)
        self.assertEqual({e.quote.player for e in result.entries}, {"Alex Example", "Blair Example"})
        self.assertEqual({e.quote.event_id for e in result.entries}, {"demo-001", "demo-002"})
        self.assertEqual(result.entries[0].quote.observed_at, utc_datetime("2030-01-15T12:00:00Z"))
        self.assertNotEqual(result.entries[0].quote.observed_at, result.captured_at)

    def test_single_event_response_is_supported(self):
        result = self.load(data=self.data[0])
        self.assertEqual(result.event_count, 1)
        self.assertEqual(len(result.entries), 4)
        self.assertTrue(result.entries[0].location.startswith("$.bookmakers"))

    def test_round_trip_through_csv_preserves_analysis(self):
        result = self.load()
        path = Path(self.folder.name) / "quotes.csv"
        write_import(result, path)
        direct = LoadedQuotes(tuple(e.quote for e in result.entries), (), 8)
        kwargs = dict(as_of=utc_datetime(CAPTURED), reference_book="Reference", target_book="Target")
        direct_report = analyze(direct, **kwargs)
        csv_report = analyze(load_csv(path), **kwargs)
        self.assertEqual(direct_report.comparisons, csv_report.comparisons)
        self.assertEqual([c.status for c in csv_report.comparisons],
                         ["gap", "within_threshold", "different_line", "different_line"])

    def test_market_update_is_required_without_book_or_capture_fallback(self):
        del self.market()["last_update"]
        self.data[0]["bookmakers"][0]["last_update"] = CAPTURED
        result = self.load()
        self.assertEqual(len(result.entries), 6)
        self.assertEqual(result.issues[0].code, "invalid_update_time")

    def test_future_or_naive_update_is_rejected(self):
        for time in ["2030-01-15T12:06:00Z", "2030-01-15T12:00:00", 123, None]:
            with self.subTest(time=time):
                self.market()["last_update"] = time
                self.assertEqual(self.load().issues[0].code, "invalid_update_time")

    def test_recent_capture_does_not_refresh_stale_prices(self):
        result = self.load(captured_at="2030-01-15T13:00:00Z")
        loaded = LoadedQuotes(tuple(e.quote for e in result.entries), (), 8)
        report = analyze(loaded, as_of=result.captured_at, reference_book="Reference", target_book="Target")
        self.assertFalse(report.comparisons)
        self.assertEqual(sum(i.code == "stale_quote" for i in report.issues), 8)

    def test_unmapped_player_is_not_guessed_and_diagnostics_do_not_echo_it(self):
        self.market()["outcomes"][0]["description"] = "private-alias-do-not-echo"
        result = self.load()
        self.assertEqual(len(result.entries), 7)
        self.assertEqual(result.issues[0].code, "unmapped_identity")
        self.assertIn("outcomes[0].description", result.issues[0].location)
        self.assertNotIn("private-alias-do-not-echo", json.dumps(result.manifest()))

    def test_player_alias_is_scoped_by_event(self):
        self.data[1]["bookmakers"][0]["markets"][0]["outcomes"][0]["description"] = "A. Example"
        result = self.load()
        self.assertEqual(len(result.entries), 7)
        self.assertEqual(result.issues[0].code, "unmapped_identity")

    def test_unmapped_container_identities_are_reported(self):
        for section in ("events", "sports", "books", "markets"):
            with self.subTest(section=section):
                mapping = deepcopy(self.mapping)
                mapping[section].clear()
                result = self.load(mapping=mapping)
                self.assertFalse(result.entries)
                self.assertTrue(result.issues)
                self.assertEqual({i.code for i in result.issues}, {"unmapped_identity"})

    def test_missing_decimal_boolean_or_invalid_price_is_not_zero_filled(self):
        for value in (None, 0, 1.91, True, "do-not-echo"):
            with self.subTest(value=value):
                self.market()["outcomes"][0]["price"] = value
                result = self.load()
                self.assertEqual(len(result.entries), 7)
                self.assertEqual(result.issues[0].code, "invalid_outcome")
                self.assertNotIn("do-not-echo", repr(result.issues))

    def test_integer_line_and_missing_description_are_rejected(self):
        self.market()["outcomes"][0]["point"] = 24
        del self.market()["outcomes"][1]["description"]
        result = self.load()
        self.assertEqual(len(result.entries), 6)
        self.assertEqual({i.code for i in result.issues}, {"invalid_outcome", "unmapped_identity"})

    def test_malformed_nested_containers_do_not_crash_or_import(self):
        mutations = [
            lambda data: data.__setitem__(0, None),
            lambda data: data[0].__setitem__("bookmakers", {}),
            lambda data: data[0]["bookmakers"].__setitem__(0, None),
            lambda data: data[0]["bookmakers"][0].__setitem__("markets", {}),
            lambda data: data[0]["bookmakers"][0]["markets"].__setitem__(0, None),
            lambda data: data[0]["bookmakers"][0]["markets"][0].__setitem__("outcomes", {}),
            lambda data: data[0]["bookmakers"][0]["markets"][0]["outcomes"].__setitem__(0, None),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                data = deepcopy(self.data)
                mutation(data)
                result = self.load(data=data)
                self.assertTrue(result.issues)

    def test_error_envelopes_and_historical_wrappers_are_not_treated_as_events(self):
        for data in ({"message": "private-token-do-not-echo"}, {"data": self.data[0]}, "invalid"):
            with self.subTest(data=data):
                with self.assertRaises(ValueError) as error:
                    self.load(data=data)
                self.assertNotIn("private-token-do-not-echo", str(error.exception))

    def test_mapping_shape_and_colliding_book_aliases_are_rejected(self):
        bad = deepcopy(self.mapping)
        bad["books"]["fanduel"] = " Reference "
        for mapping in [bad, {}, dict(self.mapping, unknown="private"), dict(self.mapping, players={"source-event-001": "Alex"})]:
            with self.subTest(mapping=mapping):
                with self.assertRaises(ValueError):
                    self.load(mapping=mapping)

    def test_duplicate_json_keys_and_nonfinite_values_fail_explicitly(self):
        self.load()
        for text in ('{"id":"a","id":"b","bookmakers":[]}', '[NaN]', '[Infinity]'):
            with self.subTest(text=text):
                self.path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_snapshot(self.path, mapping_path=self.mapping_path, captured_at=CAPTURED, odds_format="american")

    def test_format_and_capture_time_must_be_explicit_and_valid(self):
        for kwargs in (dict(odds_format="decimal"), dict(captured_at="2030-01-15T12:05:00")):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    self.load(**kwargs)

    def test_manifest_is_deterministic_and_tracks_hashes_and_json_locations(self):
        result = self.load()
        self.assertEqual(result.manifest(), self.load().manifest())
        manifest = result.manifest()
        self.assertEqual(manifest["source_sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(manifest["mapping_sha256"], hashlib.sha256(self.mapping_path.read_bytes()).hexdigest())
        self.assertEqual(manifest["rows"][0]["csv_line"], 2)
        self.assertEqual(manifest["rows"][0]["source_location"], "$[0].bookmakers[0].markets[0].outcomes[0]")

    def test_unrecognized_source_metadata_does_not_enter_outputs(self):
        self.data[0]["request_url"] = "https://example.invalid/?apiKey=do-not-export-this"
        self.data[0]["bookmakers"][0]["title"] = "do-not-export-this"
        result = self.load()
        self.assertNotIn("do-not-export-this", render_csv(result) + json.dumps(result.manifest()))

    def test_export_does_not_overwrite_existing_outputs(self):
        result = self.load()
        path = Path(self.folder.name) / "quotes.csv"
        write_import(result, path)
        original = path.read_bytes()
        with self.assertRaises(ValueError):
            write_import(result, path)
        self.assertEqual(path.read_bytes(), original)

    def test_failed_manifest_write_rolls_back_new_csv(self):
        result = self.load()
        path = Path(self.folder.name) / "quotes.csv"
        original = Path.open

        def fail_manifest(candidate, *args, **kwargs):
            if str(candidate).endswith(".manifest.json"):
                raise OSError("simulated write failure")
            return original(candidate, *args, **kwargs)

        with patch.object(Path, "open", fail_manifest):
            with self.assertRaises(OSError):
                write_import(result, path)
        self.assertFalse(path.exists())

    def command(self, output, *extra):
        return ["import-snapshot", str(self.path), "--mapping", str(self.mapping_path),
                "--captured-at", CAPTURED, "--odds-format", "american", "--output", str(output), *extra]

    def test_cli_import_then_existing_analysis_command(self):
        self.load()
        path = Path(self.folder.name) / "nested" / "quotes.csv"
        with redirect_stdout(StringIO()):
            self.assertEqual(main(self.command(path)), 0)
        stdout = StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main([str(path), "--as-of", CAPTURED, "--format", "json"]), 0)
        self.assertEqual(len(json.loads(stdout.getvalue())["comparisons"]), 4)
        self.assertTrue(path.with_name(path.name + ".manifest.json").exists())

    def test_cli_partial_import_requires_explicit_opt_in_and_manifest(self):
        self.market()["outcomes"][0]["price"] = None
        self.load()
        path = Path(self.folder.name) / "quotes.csv"
        with redirect_stderr(StringIO()) as error:
            self.assertEqual(main(self.command(path)), 2)
        self.assertIn("--allow-partial", error.getvalue())
        self.assertFalse(path.exists())
        with redirect_stdout(StringIO()):
            self.assertEqual(main(self.command(path, "--allow-partial")), 0)
        manifest = json.loads(path.with_name(path.name + ".manifest.json").read_text())
        self.assertEqual(manifest["imported_rows"], 7)
        self.assertEqual(manifest["issue_count"], 1)

    def test_cli_cannot_overwrite_inputs_even_with_partial_flag(self):
        self.load()
        original = self.path.read_bytes()
        with redirect_stderr(StringIO()):
            self.assertEqual(main(self.command(self.path, "--allow-partial")), 2)
        self.assertEqual(self.path.read_bytes(), original)

    def test_cli_rejects_zero_valid_quotes_and_invalid_json(self):
        self.load(data=[])
        path = Path(self.folder.name) / "quotes.csv"
        with redirect_stderr(StringIO()):
            self.assertEqual(main(self.command(path, "--allow-partial")), 2)
        self.path.write_text("{broken", encoding="utf-8")
        with redirect_stderr(StringIO()) as error:
            self.assertEqual(main(self.command(path)), 2)
        self.assertNotIn("Traceback", error.getvalue())
        self.assertFalse(path.exists())
