"""Manual live capture CLI. Only this explicit command reads ODDS_API_KEY."""

import argparse
from pathlib import Path
import sys

from .capture import capture, DEFAULT_REFERENCES


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="odds-analysis capture",
        description="Fetch one upcoming NBA player-points market in the US region, then analyze it. Reads ODDS_API_KEY from the environment. At most one credit-bearing odds request; no retries.")
    parser.add_argument("--event-id", help="Upcoming event ID; default: earliest upcoming NBA event")
    parser.add_argument("--output", type=Path, help="New directory inside ./private/ (default: timestamped directory)")
    parser.add_argument("--reference-book", action="append", help="Provider book key; repeat (default: draftkings, betmgm, betrivers)")
    parser.add_argument("--target-book", default="fanduel")
    parser.add_argument("--allow-partial", action="store_true", help="Analyze accepted quotes even when the importer reports diagnostics")
    args = parser.parse_args(argv)
    try:
        audit, output = capture(output=args.output, event_id=args.event_id,
                                reference_books=args.reference_book or DEFAULT_REFERENCES,
                                target_book=args.target_book, allow_partial=args.allow_partial)
    except (OSError, ValueError, OverflowError):
        print("odds-analysis capture: invalid configuration, missing ODDS_API_KEY, or unavailable private output; use --help", file=sys.stderr)
        return 2
    print(f"Capture: {audit['status']}. Files: {output}")
    for request in audit["requests"]:
        q = request["quota"]
        print(f"  {request['operation']}: status={request['status']}; credits: last={q.get('last')}, remaining={q.get('remaining')}, used={q.get('used')}")
    if "error" in audit:
        print(audit["error"], file=sys.stderr)
        return 2
    if audit["status"] != "analyzed":
        print("Capture needs inspection; see capture.json and import-diagnostics.json when present.")
        return 1
    print(f"Comparisons: {audit['comparisons']}. Report: {output / 'report.md'}")
    return 0
