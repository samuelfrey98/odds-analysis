"""Replay saved snapshots and evaluate authored behavior expectations."""

from collections import Counter
from datetime import timedelta
import hashlib
import json
import math
from pathlib import Path

from .adapters.csv_input import load_csv
from .comparison import analyze
from .models import utc_datetime
from .reporting import render_json, render_markdown, _cell

IDENTITY_FIELDS = ("event_id", "player", "market", "line", "side")
STATUSES = {"gap", "within_threshold", "insufficient_references", "reference_disagreement",
            "different_line", "no_reference"}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate replay manifest keys are not allowed")
        result[key] = value
    return result


def _read_manifest(bundle: Path) -> dict:
    try:
        manifest = json.loads((bundle / "simulation.json").read_text(encoding="utf-8"),
                              object_pairs_hook=_unique_object)
        if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
            raise ValueError
        if not isinstance(manifest["seed"], int) or isinstance(manifest["seed"], bool):
            raise ValueError
        books = manifest["reference_books"]
        if not isinstance(books, list) or not books or not all(isinstance(b, str) and b.strip() for b in books):
            raise ValueError
        if not isinstance(manifest["target_book"], str) or not manifest["target_book"].strip():
            raise ValueError
        policy = manifest["policy"]
        if not isinstance(policy, dict) or set(policy) != {"max_age_seconds", "min_gap_pp", "min_reference_books", "max_disagreement_pp"}:
            raise ValueError
        for value in policy.values():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError
        frames = manifest["frames"]
        if not isinstance(frames, list) or not frames:
            raise ValueError
        times = []
        for frame in frames:
            if not all(isinstance(frame[key], str) and frame[key].strip()
                       for key in ("scenario", "description", "csv", "as_of")):
                raise ValueError
            times.append(utc_datetime(frame["as_of"]))
            expected = frame["expected"]
            if not isinstance(expected, list) or not expected:
                raise ValueError
            identities = []
            for item in expected:
                if set(item) != {*IDENTITY_FIELDS, "status"} or item["status"] not in STATUSES:
                    raise ValueError
                if not all(isinstance(item[key], str) and item[key].strip() for key in IDENTITY_FIELDS):
                    raise ValueError
                identities.append(tuple(item[key] for key in IDENTITY_FIELDS))
            if len(set(identities)) != len(identities):
                raise ValueError
            if not isinstance(frame["expected_issue_codes"], list) or not all(
                    isinstance(code, str) and code for code in frame["expected_issue_codes"]):
                raise ValueError
        if any(later <= earlier for earlier, later in zip(times, times[1:])):
            raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValueError("Invalid replay manifest: check schema, policy, expectations, and increasing frame times") from None
    return manifest


def replay(bundle: str | Path) -> tuple[dict, tuple]:
    """Analyze each frame independently, using its explicit as-of time.

    Full snapshots define currently visible state. Earlier frames are not
    accumulated, so vanished quotes are not carried forward and future frames
    cannot affect an earlier report. Expectations are checked, not enforced.
    """
    bundle = Path(bundle).resolve()
    manifest = _read_manifest(bundle)
    reports = []
    results = []
    for frame in manifest["frames"]:
        source = (bundle / frame["csv"]).resolve()
        if Path(frame["csv"]).is_absolute() or not source.is_relative_to(bundle) or source.suffix != ".csv":
            raise ValueError("Snapshot paths must resolve to CSV files inside the bundle")
        raw = source.read_bytes()
        policy = manifest["policy"]
        report = analyze(load_csv(source), as_of=utc_datetime(frame["as_of"]),
                         reference_books=manifest["reference_books"], target_book=manifest["target_book"],
                         max_age=timedelta(seconds=policy["max_age_seconds"]),
                         min_gap_pp=policy["min_gap_pp"],
                         min_reference_books=policy["min_reference_books"],
                         max_disagreement_pp=policy["max_disagreement_pp"])
        actual = {tuple(getattr(c, key) for key in IDENTITY_FIELDS): c.status for c in report.comparisons}
        expected = {tuple(item[key] for key in IDENTITY_FIELDS): item["status"] for item in frame["expected"]}
        checks = []
        for identity in sorted(expected.keys() | actual.keys()):
            checks.append({**dict(zip(IDENTITY_FIELDS, identity)),
                           "expected": expected.get(identity), "actual": actual.get(identity),
                           "passed": identity in expected and expected[identity] == actual.get(identity)})
        issue_codes = sorted({issue.code for issue in report.issues})
        expected_issues = sorted(set(frame["expected_issue_codes"]))
        results.append({"scenario": frame["scenario"], "description": frame["description"],
                        "as_of": report.as_of, "snapshot": frame["csv"],
                        "snapshot_sha256": hashlib.sha256(raw).hexdigest(),
                        "checks": checks, "expected_issue_codes": expected_issues,
                        "actual_issue_codes": issue_codes, "diagnostics_passed": issue_codes == expected_issues,
                        "statuses": dict(sorted(Counter(c.status for c in report.comparisons).items()))})
        reports.append(report)
    count = sum(len(frame["checks"]) for frame in results)
    matched = sum(check["passed"] for frame in results for check in frame["checks"])
    diagnostics_matched = sum(frame["diagnostics_passed"] for frame in results)
    summary = {"schema_version": 1, "seed": manifest["seed"],
               "manifest_sha256": hashlib.sha256((bundle / "simulation.json").read_bytes()).hexdigest(),
               "frame_count": len(results), "comparison_checks": count, "comparison_checks_passed": matched,
               "diagnostic_checks": len(results), "diagnostic_checks_passed": diagnostics_matched,
               "passed": matched == count and diagnostics_matched == len(results), "frames": results}
    return summary, tuple(reports)


def render_replay(summary: dict, *, detail_links: bool = True) -> str:
    result = "PASS" if summary["passed"] else "FAIL"
    lines = ["# Simulation replay", "",
             f"**{result}** · Seed: **{summary['seed']}** · Frames: **{summary['frame_count']}**", "",
             f"Comparison checks: **{summary['comparison_checks_passed']}/{summary['comparison_checks']}**. "
             f"Diagnostic checks: **{summary['diagnostic_checks_passed']}/{summary['diagnostic_checks']}**.", "",
             "This is a seeded, scripted demonstration using invented quotes. A passing replay verifies the authored software scenarios; it does not establish predictive accuracy, arbitrage profitability, or real-world returns.", "",
             "| Step | Time (UTC) | Scenario | Comparison checks | Diagnostics | Result |",
             "| ---: | --- | --- | ---: | --- | --- |"]
    for index, frame in enumerate(summary["frames"]):
        matched = sum(check["passed"] for check in frame["checks"])
        passed = matched == len(frame["checks"]) and frame["diagnostics_passed"]
        issues = ", ".join(frame["actual_issue_codes"]) or "none"
        values = [index, frame["as_of"], frame["scenario"], f"{matched}/{len(frame['checks'])}",
                  issues, "PASS" if passed else "FAIL"]
        lines.append("| " + " | ".join(_cell(value) for value in values) + " |")
    lines.extend(["", "## Expected versus observed", ""])
    for index, frame in enumerate(summary["frames"]):
        lines.extend([f"### {index}. {_cell(frame['scenario'])}", "", _cell(frame["description"]), "",
                      "| Player / side / line | Expected | Observed | Result |",
                      "| --- | --- | --- | --- |"])
        for check in frame["checks"]:
            values = [f"{check['player']} / {check['side']} {check['line']}",
                      check["expected"] or "not expected", check["actual"] or "missing",
                      "PASS" if check["passed"] else "FAIL"]
            lines.append("| " + " | ".join(_cell(value) for value in values) + " |")
        expected = ", ".join(frame["expected_issue_codes"]) or "none"
        actual = ", ".join(frame["actual_issue_codes"]) or "none"
        lines.extend(["", f"Expected diagnostics: {_cell(expected)}. Observed diagnostics: {_cell(actual)}."])
        if detail_links:
            lines.append(f"[Detailed market report](frames/{index:02}.md)")
        lines.append("")
    return "\n".join(lines)


def write_replay(summary: dict, reports: tuple, output: str | Path) -> Path:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "frames").mkdir()
    for index, report in enumerate(reports):
        (output / "frames" / f"{index:02}.md").write_text(render_markdown(report), encoding="utf-8")
        (output / "frames" / f"{index:02}.json").write_text(render_json(report), encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "summary.md").write_text(render_replay(summary), encoding="utf-8")
    return output
