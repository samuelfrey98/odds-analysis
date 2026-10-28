"""Offline simulation/replay commands, including a one-command portfolio demo."""

import argparse
import csv
from pathlib import Path
import sys

from .replay import replay, write_replay
from .simulation import DEFAULT_START, generate, write_simulation


def main(command: str, argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=f"odds-analysis {command}",
                                     description="Reproducible offline market scenarios; no API key or network.")
    if command == "replay":
        parser.add_argument("bundle", type=Path, help="Directory containing simulation.json and snapshots/")
        parser.add_argument("--output", type=Path, help="New report directory (default: BUNDLE/replay)")
    else:
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--start", default=DEFAULT_START, help="Simulation start with UTC offset; never defaults to the current clock")
        parser.add_argument("--output", type=Path, default=Path("reports/demo" if command == "demo" else "reports/simulation"),
                            help="New bundle directory; existing paths are never overwritten")
    args = parser.parse_args(argv)
    try:
        if command in ("demo", "simulate"):
            simulation = generate(args.seed, args.start)
            bundle = write_simulation(simulation, args.output)
            if command == "simulate":
                print(f"Generated {len(simulation.frames)} snapshots with seed {simulation.seed}.")
                return 0
            output = bundle / "replay"
        else:
            bundle = args.bundle
            output = args.output or bundle / "replay"
        summary, reports = replay(bundle)
        write_replay(summary, reports, output)
        state = "PASS" if summary["passed"] else "FAIL"
        print(f"{state}: {summary['frame_count']} frames; "
              f"{summary['comparison_checks_passed']}/{summary['comparison_checks']} comparison checks; "
              f"{summary['diagnostic_checks_passed']}/{summary['diagnostic_checks']} diagnostic checks.")
        for index, frame in enumerate(summary["frames"]):
            passed = frame["diagnostics_passed"] and all(check["passed"] for check in frame["checks"])
            print(f"  {index}: {frame['scenario']}: {'PASS' if passed else 'FAIL'}")
        print(f"Report: {output / 'summary.md'}")
        return 0 if summary["passed"] else 1
    except (OSError, ValueError, OverflowError, csv.Error) as error:
        print(f"odds-analysis {command}: {error}", file=sys.stderr)
        return 2
