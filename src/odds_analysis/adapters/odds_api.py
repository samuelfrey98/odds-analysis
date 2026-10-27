"""Normalize saved The Odds API v4 event-odds JSON without network access."""

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from ..models import Quote, utc_datetime


@dataclass(frozen=True)
class ImportIssue:
    code: str
    location: str
    message: str


@dataclass(frozen=True)
class ImportedQuote:
    quote: Quote
    location: str


@dataclass(frozen=True)
class SnapshotImport:
    entries: tuple[ImportedQuote, ...]
    issues: tuple[ImportIssue, ...]
    captured_at: datetime
    source_sha256: str
    mapping_sha256: str
    event_count: int

    def manifest(self) -> dict:
        return {
            "schema_version": 1,
            "source_format": "the-odds-api-v4-event-odds",
            "odds_format": "american",
            "captured_at": self.captured_at.isoformat(),
            "source_sha256": self.source_sha256,
            "mapping_sha256": self.mapping_sha256,
            "input_events": self.event_count,
            "imported_rows": len(self.entries),
            "issue_count": len(self.issues),
            "issues": [asdict(issue) for issue in self.issues],
            "rows": [
                {"csv_line": index + 2, "source_location": entry.location,
                 "source_updated_at": entry.quote.observed_at.isoformat()}
                for index, entry in enumerate(self.entries)
            ],
        }


def _unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object keys are not allowed")
        result[key] = value
    return result


def _read_json(path: str | Path) -> tuple[object, str]:
    raw = Path(path).read_bytes()
    try:
        data = json.loads(raw.decode("utf-8-sig"), parse_float=Decimal,
                          parse_constant=lambda _: _reject_constant(),
                          object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("Snapshot and mapping files must contain valid UTF-8 JSON") from None
    return data, hashlib.sha256(raw).hexdigest()


def _reject_constant():
    raise ValueError("Non-finite JSON numbers are not allowed")


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected nonempty text")
    return value


def _validate_mapping(data: object) -> dict:
    fields = {"events", "players", "sports", "books", "markets"}
    if not isinstance(data, dict) or set(data) != fields:
        raise ValueError("Mapping must contain exactly events, players, sports, books, markets")
    for name in fields:
        section = data[name]
        if not isinstance(section, dict):
            raise ValueError("Mapping sections must be JSON objects")
        for key, value in section.items():
            _text(key)
            aliases = value if name == "players" else {key: value}
            if not isinstance(aliases, dict):
                raise ValueError("Player mappings must be objects scoped by source event ID")
            for alias, canonical in aliases.items():
                _text(alias)
                _text(canonical)
                if len(" ".join(canonical.split())) > 160:
                    raise ValueError("Canonical mapping values must not exceed 160 characters")
    # Distinct books must remain distinct sources, including after whitespace cleanup.
    books = [" ".join(value.split()) for value in data["books"].values()]
    if len(books) != len(set(books)):
        raise ValueError("Distinct source books must map to distinct canonical books")
    return data


def load_snapshot(
    path: str | Path,
    *,
    mapping_path: str | Path,
    captured_at: str | datetime,
    odds_format: str,
) -> SnapshotImport:
    """Read a single event object or a list of event objects with explicit aliases.

    Prices must have been saved with oddsFormat=american. Unknown identities and
    malformed containers are excluded with JSON-path diagnostics. No timestamp
    is inferred from a filename, file modification time, or current clock.
    """
    if odds_format != "american":
        raise ValueError("Only explicitly declared American odds snapshots are supported")
    captured = utc_datetime(captured_at)
    data, source_hash = _read_json(path)
    mapping_data, mapping_hash = _read_json(mapping_path)
    mapping = _validate_mapping(mapping_data)
    if isinstance(data, dict) and "id" in data and "bookmakers" in data:
        events = [("$", data)]
    elif isinstance(data, list):
        events = [(f"$[{index}]", event) for index, event in enumerate(data)]
    else:
        raise ValueError("Expected an event-odds object or a list of event-odds objects")

    issues = []
    entries = []

    def issue(code, location, message):
        issues.append(ImportIssue(code, location, message))

    def mapped(section, value, location):
        if not isinstance(value, str) or value not in section:
            issue("unmapped_identity", location, "No explicit mapping for this source identity")
            return None
        return section[value]

    for event_path, event in events:
        if not isinstance(event, dict):
            issue("invalid_event", event_path, "Event must be a JSON object")
            continue
        event_id = mapped(mapping["events"], event.get("id"), event_path + ".id")
        sport = mapped(mapping["sports"], event.get("sport_key"), event_path + ".sport_key")
        if event_id is None or sport is None:
            continue
        try:
            start = utc_datetime(event.get("commence_time"))
        except ValueError:
            issue("invalid_event", event_path + ".commence_time", "Event start requires an explicit UTC offset")
            continue
        books = event.get("bookmakers")
        if not isinstance(books, list):
            issue("invalid_container", event_path + ".bookmakers", "Bookmakers must be a JSON array")
            continue
        players = mapping["players"].get(event["id"], {})
        for book_index, book in enumerate(books):
            book_path = f"{event_path}.bookmakers[{book_index}]"
            if not isinstance(book, dict):
                issue("invalid_container", book_path, "Bookmaker must be a JSON object")
                continue
            book_name = mapped(mapping["books"], book.get("key"), book_path + ".key")
            if book_name is None:
                continue
            markets = book.get("markets")
            if not isinstance(markets, list):
                issue("invalid_container", book_path + ".markets", "Markets must be a JSON array")
                continue
            for market_index, market in enumerate(markets):
                market_path = f"{book_path}.markets[{market_index}]"
                if not isinstance(market, dict):
                    issue("invalid_container", market_path, "Market must be a JSON object")
                    continue
                market_name = mapped(mapping["markets"], market.get("key"), market_path + ".key")
                if market_name is None:
                    continue
                try:
                    updated = utc_datetime(market.get("last_update"))
                    if updated > captured:
                        raise ValueError
                except ValueError:
                    issue("invalid_update_time", market_path + ".last_update",
                          "Market update needs a UTC offset and must not be after capture time")
                    continue
                outcomes = market.get("outcomes")
                if not isinstance(outcomes, list):
                    issue("invalid_container", market_path + ".outcomes", "Outcomes must be a JSON array")
                    continue
                for outcome_index, outcome in enumerate(outcomes):
                    outcome_path = f"{market_path}.outcomes[{outcome_index}]"
                    if not isinstance(outcome, dict):
                        issue("invalid_outcome", outcome_path, "Outcome must be a JSON object")
                        continue
                    player = mapped(players, outcome.get("description"), outcome_path + ".description")
                    if player is None:
                        continue
                    try:
                        quote = Quote(
                            event_id=event_id, event_start=start, observed_at=updated,
                            sport=sport, player=player, market=market_name,
                            line=outcome.get("point"), side=outcome.get("name"),
                            book=book_name, american_odds=outcome.get("price"),
                        )
                    except ValueError as error:
                        issue("invalid_outcome", outcome_path, str(error))
                        continue
                    entries.append(ImportedQuote(quote, outcome_path))
    return SnapshotImport(tuple(entries), tuple(issues), captured, source_hash, mapping_hash, len(events))
