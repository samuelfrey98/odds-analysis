"""Import local snapshots into CSV plus an audit manifest."""

import argparse
import csv
from io import StringIO
import json
from pathlib import Path
import sys

from .adapters.csv_input import FIELDS
from .adapters.odds_api import SnapshotImport, load_snapshot


def render_csv(result: SnapshotImport) -> str:
    stream = StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(FIELDS)
    for entry in result.entries:
        q = entry.quote
        writer.writerow((q.event_id, q.event_start.isoformat(), q.observed_at.isoformat(),
                         q.sport, q.player, q.market, str(q.line), q.side, q.book,
                         str(q.american_odds)))
    return stream.getvalue()


def write_import(result: SnapshotImport, output: Path) -> Path:
    """Exclusively create outputs; roll back files created by a failed write."""
    manifest = output.with_name(output.name + ".manifest.json")
    for path in (output, manifest):
        if path.exists() or path.is_symlink():
            raise ValueError("Import output or manifest already exists; choose a new output path")
    content = json.dumps(result.manifest(), indent=2, sort_keys=True, allow_nan=False) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        for path, text in ((output, render_csv(result)), (manifest, content)):
            with path.open("x", encoding="utf-8", newline="") as stream:
                created.append(path)
                stream.write(text)
    except OSError:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="odds-analysis import-snapshot",
        description="Import saved The Odds API v4 event-odds JSON; no network or credentials.",
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--mapping", type=Path, required=True, help="Explicit event/player/sport/book/market aliases")
    parser.add_argument("--captured-at", required=True, help="File capture time with an explicit UTC offset")
    parser.add_argument("--odds-format", choices=("american",), required=True, help="Declare the saved response's price format")
    parser.add_argument("--output", type=Path, required=True, help="New CSV path; a .manifest.json companion is also created")
    parser.add_argument("--allow-partial", action="store_true", help="Explicitly accept valid rows despite diagnostics")
    args = parser.parse_args(argv)
    try:
        manifest = args.output.with_name(args.output.name + ".manifest.json")
        inputs = {args.input.resolve(), args.mapping.resolve()}
        if args.output.resolve() in inputs or manifest.resolve() in inputs:
            raise ValueError("Import outputs must not overwrite either input file")
        result = load_snapshot(args.input, mapping_path=args.mapping,
                               captured_at=args.captured_at, odds_format=args.odds_format)
        if result.issues and not args.allow_partial:
            codes = ", ".join(sorted({issue.code for issue in result.issues}))
            details = "\n".join(f"{issue.code} at {issue.location}: {issue.message}"
                                for issue in result.issues[:10])
            raise ValueError(f"Import blocked by {len(result.issues)} diagnostics ({codes}); use --allow-partial to export accepted rows with full diagnostics\n{details}")
        if not result.entries:
            raise ValueError("No valid quotes to export")
        write_import(result, args.output)
        print(f"Imported {len(result.entries)} quotes; {len(result.issues)} diagnostics. Wrote CSV and companion manifest.")
    except (OSError, ValueError, OverflowError) as error:
        print(f"odds-analysis import-snapshot: {error}", file=sys.stderr)
        return 2
    return 0
