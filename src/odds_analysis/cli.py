"""Command-line entry point; no network or account configuration required."""

import argparse
import csv
from datetime import timedelta
from pathlib import Path
import sys

from . import __version__
from .adapters.csv_input import load_csv
from .comparison import analyze
from .models import utc_datetime
from .odds import _finite
from .reporting import render_json, render_markdown


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "import-snapshot":
        from .import_cli import main as import_main
        return import_main(arguments[1:])
    parser = argparse.ArgumentParser(
        description="Compare pregame odds snapshots from an offline CSV.",
        epilog="Import saved provider JSON with: odds-analysis import-snapshot --help",
    )
    parser.add_argument("input", type=Path, help="CSV using the documented quote schema")
    parser.add_argument("--as-of", required=True, help="Report time with UTC offset, e.g. 2024-01-25T12:05:00Z")
    parser.add_argument("--reference-book", default="Reference")
    parser.add_argument("--target-book", default="Target")
    parser.add_argument("--max-age-minutes", default="15")
    parser.add_argument("--min-gap-pp", default="2")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path, help="Write to a file; otherwise print to stdout")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(arguments)
    try:
        as_of = utc_datetime(args.as_of)
        age = _finite(args.max_age_minutes, "Maximum quote age")
        threshold = _finite(args.min_gap_pp, "Minimum gap")
        if args.output and args.output.resolve() == args.input.resolve():
            raise ValueError("Output must not overwrite the input CSV")
        report = analyze(
            load_csv(args.input), as_of=as_of,
            reference_book=args.reference_book, target_book=args.target_book,
            max_age=timedelta(minutes=age), min_gap_pp=threshold,
        )
        content = render_json(report) if args.format == "json" else render_markdown(report)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(content, encoding="utf-8")
        else:
            sys.stdout.write(content)
    except (OSError, ValueError, OverflowError, csv.Error) as error:
        print(f"odds-analysis: {error}", file=sys.stderr)
        return 2
    return 0
