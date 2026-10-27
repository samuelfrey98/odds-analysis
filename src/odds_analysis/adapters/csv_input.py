"""Strict CSV adapter. Row failures are reported without echoing raw values."""

import csv
from pathlib import Path

from ..models import Issue, LoadedQuotes, Quote

FIELDS = (
    "event_id", "event_start", "observed_at", "sport", "player", "market",
    "line", "side", "book", "american_odds",
)


def load_csv(path: str | Path) -> LoadedQuotes:
    quotes = []
    issues = []
    count = 0
    with Path(path).open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source, strict=True)
        header = reader.fieldnames or []
        if len(header) != len(FIELDS) or set(header) != set(FIELDS):
            raise ValueError("CSV header must contain exactly: " + ",".join(FIELDS))
        for record in reader:
            count += 1
            row = reader.line_num
            if None in record or any(value is None for value in record.values()):
                issues.append(Issue("invalid_row", "Incorrect number of CSV fields", row))
                continue
            try:
                quotes.append(Quote(**record, source_row=row))
            except ValueError as error:
                issues.append(Issue("invalid_row", str(error), row))
    return LoadedQuotes(tuple(quotes), tuple(issues), count)
