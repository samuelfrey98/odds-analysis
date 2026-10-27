from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from odds_analysis.adapters.csv_input import FIELDS, load_csv
from odds_analysis.cli import main
from odds_analysis.comparison import analyze
from odds_analysis.models import utc_datetime
from odds_analysis.reporting import render_markdown

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "synthetic_quotes.csv"
AS_OF = "2030-01-15T12:05:00Z"


class InputTests(unittest.TestCase):
    def test_header_errors_reject_ambiguous_or_private_columns(self):
        for fields in [FIELDS[:-1], FIELDS + ("password",), FIELDS[:-1] + ("book",)]:
            with self.subTest(fields=fields), TemporaryDirectory() as folder:
                path = Path(folder) / "input.csv"
                path.write_text(",".join(fields) + "\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_csv(path)

    def test_incorrect_row_width_is_diagnostic(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "input.csv"
            path.write_text(",".join(FIELDS) + "\na,b\n", encoding="utf-8")
            loaded = load_csv(path)
            self.assertFalse(loaded.quotes)
            self.assertEqual(loaded.issues[0].row, 2)

    def test_invalid_values_do_not_leak_into_diagnostics(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "input.csv"
            content = FIXTURE.read_text().splitlines()[:2]
            content[1] = content[1].rsplit(",", 1)[0] + ",do-not-echo-this-value"
            path.write_text("\n".join(content) + "\n", encoding="utf-8")
            loaded = load_csv(path)
            self.assertNotIn("do-not-echo-this-value", repr(loaded.issues))


class CliTests(unittest.TestCase):
    def test_json_cli_and_fixed_example(self):
        stdout = StringIO()
        with redirect_stdout(stdout):
            status = main([str(FIXTURE), "--as-of", AS_OF, "--format", "json"])
        self.assertEqual(status, 0)
        data = json.loads(stdout.getvalue())
        self.assertEqual(data["input_rows"], 19)
        self.assertEqual(len(data["comparisons"]), 4)

    def test_file_output_is_repeatable(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "nested" / "report.md"
            args = [str(FIXTURE), "--as-of", AS_OF, "--output", str(path)]
            self.assertEqual(main(args), 0)
            first = path.read_bytes()
            self.assertEqual(main(args), 0)
            self.assertEqual(path.read_bytes(), first)
            self.assertIn(b"different_line", first)

    def test_cli_errors_have_nonzero_status_without_traceback(self):
        cases = [["--as-of", "no-time"], ["--as-of", AS_OF, "--max-age-minutes", "nan"],
                 ["--as-of", AS_OF, "--max-age-minutes", "-1"],
                 ["--as-of", AS_OF, "--reference-book", "Target"]]
        for options in cases:
            with self.subTest(options=options), redirect_stderr(StringIO()) as stderr:
                self.assertEqual(main([str(FIXTURE)] + options), 2)
                self.assertNotIn("Traceback", stderr.getvalue())

    def test_input_cannot_be_overwritten(self):
        with redirect_stderr(StringIO()):
            self.assertEqual(main([str(FIXTURE), "--as-of", AS_OF, "--output", str(FIXTURE)]), 2)

    def test_imports_are_quiet_and_do_not_load_gui_or_network_modules(self):
        code = "import odds_analysis.cli, sys; assert not any(x in sys.modules for x in ('socket', 'tkinter', 'selenium', 'pyautogui'))"
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_example_markdown_matches_renderer(self):
        loaded = load_csv(FIXTURE)
        report = analyze(loaded, as_of=utc_datetime(AS_OF), reference_book="Reference", target_book="Target")
        self.assertEqual((ROOT / "examples" / "report.md").read_text(), render_markdown(report))
