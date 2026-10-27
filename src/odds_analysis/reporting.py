"""Deterministic Markdown and JSON reports."""

from collections import Counter
import json

from .comparison import AnalysisReport


def render_json(report: AnalysisReport) -> str:
    return json.dumps(report.to_dict(), indent=2, allow_nan=False, sort_keys=True) + "\n"


def _cell(value: object) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("|", "&#124;").replace("\n", " ").replace("\r", " ").replace("`", "&#96;")


def render_markdown(report: AnalysisReport) -> str:
    counts = Counter(c.status for c in report.comparisons)
    multiple = len(report.reference_books) > 1
    reference_label = "References" if multiple else "Reference"
    lines = [
        "# Odds comparison report", "",
        f"As of **{report.as_of}**. {reference_label}: **{_cell(report.reference_book)}**. Target: **{_cell(report.target_book)}**.", "",
        f"Maximum quote age: {report.max_age_seconds / 60:g} minutes. Flag threshold: {report.min_gap_pp:g} percentage points.", "",
        f"Input rows: {report.input_rows}; parsed: {report.parsed_rows}; eligible after exclusions/deduplication: {report.eligible_rows}.",
        f"Target comparisons: {len(report.comparisons)}; positive gaps meeting threshold: {counts['gap']}; diagnostics: {len(report.issues)}.", "",
    ]
    if multiple:
        lines.extend([
            f"Consensus: median of per-book margin-free probabilities. Minimum usable books: {report.min_reference_books}. Maximum probability range: {report.max_disagreement_pp:g} percentage points.", "",
            "Each book contributes one complete pair at the target threshold. A missing quorum or excessive disagreement suppresses the probability gap. The range describes these books, not statistical confidence or model accuracy.", "",
        ])
    else:
        lines.extend(["Reference probabilities use proportional margin removal on paired prices at the same threshold and timestamp. A gap is a market comparison under that assumption, not a validated edge or a bet recommendation.", ""])
    header = "| Event / player | Market | Target side / line | Price | Reference lines | Reference p | Target implied p | Gap (pp) | Status |"
    separator = "| --- | --- | --- | ---: | --- | ---: | ---: | ---: | --- |"
    if multiple:
        header += " Books | Range (pp) |"
        separator += " ---: | ---: |"
    lines.extend([header, separator])
    for c in report.comparisons:
        probability = "—" if c.reference_probability is None else f"{100*c.reference_probability:.2f}%"
        gap = "—" if c.gap_pp is None else f"{c.gap_pp:+.2f}"
        values = [f"{c.event_id} / {c.player}", c.market, f"{c.side} {c.line}",
                  f"{c.target_odds:+g}", ", ".join(c.reference_lines) or "—",
                  probability, f"{100*c.target_implied_probability:.2f}%", gap, c.status]
        if multiple:
            values.extend([f"{c.reference_count}/{len(report.reference_books)}",
                           "—" if c.reference_spread_pp is None else f"{c.reference_spread_pp:.2f}"])
        lines.append("| " + " | ".join(_cell(v) for v in values) + " |")
    if not report.comparisons:
        lines.extend(["", "No eligible target quotes to compare."])
    if multiple and report.comparisons:
        lines.extend(["", "## Reference evidence", ""])
        for c in report.comparisons:
            label = f"{c.event_id} / {c.player} / {c.market} / {c.side} {c.line}"
            lines.extend([f"### {_cell(label)}", "", _cell(c.explanation), ""])
            if c.reference_contributions:
                lines.extend(["| Book | Source update (UTC) | Over price | Under price | Probability for target side |",
                              "| --- | --- | ---: | ---: | ---: |"])
                for detail in c.reference_contributions:
                    cells = [detail.book, detail.observed_at, f"{detail.over_odds:+g}",
                             f"{detail.under_odds:+g}", f"{100*detail.probability:.2f}%"]
                    lines.append("| " + " | ".join(_cell(value) for value in cells) + " |")
                lines.append("")
            for exclusion in c.reference_exclusions:
                available = ", ".join(exclusion.available_lines) or "none"
                lines.append(f"- Excluded **{_cell(exclusion.book)}**: {_cell(', '.join(exclusion.reasons))}. Complete eligible lines: {_cell(available)}.")
            if c.reference_exclusions:
                lines.append("")
    lines.extend(["", "## Diagnostics", ""])
    for issue in report.issues:
        location = "Dataset" if issue.row is None else f"CSV line {issue.row}"
        lines.append(f"- {location}: **{issue.code}** — {_cell(issue.message)}")
    if not report.issues:
        lines.append("No exclusions or data issues detected.")
    lines.extend(["", "## Interpretation", "",
        "- `gap`: a positive probability gap meets the configured threshold.",
        "- `within_threshold`: a matched market has no qualifying positive gap.",
        "- `different_line`: reference thresholds differ; probabilities are not compared across lines.",
        "- `no_reference`: no complete eligible reference pair is available."])
    if multiple:
        lines.extend(["- `insufficient_references`: matching pairs exist, but fewer than the required book count; no probability or gap is assigned.",
                      "- `reference_disagreement`: the median is shown, but the probability range exceeds the configured limit; no gap is assigned."])
    lines.extend(["", "Only pregame, positive half-integer player-prop lines are supported. Missing or invalid values are excluded, never replaced with zero. This report does not establish execution or profitability.", ""])
    return "\n".join(lines)
