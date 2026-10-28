"""One manual acquisition, then the existing offline import and analysis path."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from . import __version__
from .adapters.csv_input import load_csv
from .adapters.live_odds_api import CaptureError, Client, MARKET, SPORT
from .adapters.odds_api import load_snapshot
from .comparison import analyze
from .import_cli import write_import
from .models import LoadedQuotes, utc_datetime
from .reporting import render_json, render_markdown

DEFAULT_REFERENCES = ("draftkings", "betmgm", "betrivers")


def _write(path: Path, content: str | bytes):
    data = content.encode("utf-8") if isinstance(content, str) else content
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
        stream.write(data)


def _json(data) -> str:
    return json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _private_output(output: Path | None) -> Path:
    root = Path.cwd() / "private"
    output = output or root / ("capture-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    if root.is_symlink() or not output.resolve().is_relative_to(root.resolve()) or output.resolve() == root.resolve():
        raise CaptureError("Capture output must be a new directory inside ./private/; symlinks are not supported")
    if output.exists() or output.is_symlink():
        raise CaptureError("Capture output already exists; choose a new directory")
    for ancestor in (output, *output.parents):
        if ancestor == root.parent:
            break
        if ancestor.is_symlink():
            raise CaptureError("Capture output ancestors must not be symlinks")
    root.mkdir(mode=0o700, exist_ok=True)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    _write(output / ".gitignore", "*\n!.gitignore\n")
    return output


def select_event(events, now: datetime, event_id: str | None):
    if not isinstance(events, list):
        raise CaptureError("Provider event list has an invalid structure")
    upcoming = []
    for event in events:
        try:
            if not isinstance(event, dict) or event.get("sport_key") != SPORT:
                continue
            identifier = event.get("id")
            if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identifier):
                continue
            start = utc_datetime(event.get("commence_time"))
            if start > now and (event_id is None or identifier == event_id):
                upcoming.append((start, identifier))
        except ValueError:
            continue
    if not upcoming:
        raise CaptureError("No matching upcoming NBA event; no odds request was made")
    return min(upcoming)[1]


def identity_mapping(data, event_id: str) -> dict:
    """Preserve exact names/keys from this one provider, without fuzzy aliases."""
    if not isinstance(data, dict) or data.get("id") != event_id or data.get("sport_key") != SPORT:
        raise CaptureError("Odds response did not match the requested event and sport")
    if not isinstance(data.get("bookmakers"), list):
        raise CaptureError("Odds response bookmakers must be an array")
    books, players = {}, {}
    for book in data["bookmakers"]:
        if not isinstance(book, dict):
            continue
        key = book.get("key")
        if isinstance(key, str) and key.strip():
            books[key] = key
        markets = book.get("markets")
        if not isinstance(markets, list):
            continue
        for market in markets:
            if not isinstance(market, dict) or market.get("key") != MARKET:
                continue
            outcomes = market.get("outcomes")
            if not isinstance(outcomes, list):
                continue
            for outcome in outcomes:
                if isinstance(outcome, dict):
                    name = outcome.get("description")
                    if isinstance(name, str) and name.strip():
                        players[name] = name
    return {"events": {event_id: event_id}, "players": {event_id: players},
            "sports": {SPORT: "nba"}, "books": books, "markets": {MARKET: MARKET}}


def capture(*, output: Path | None = None, event_id: str | None = None,
            reference_books=DEFAULT_REFERENCES, target_book="fanduel", allow_partial=False) -> tuple[dict, Path]:
    # Validate configuration before allocating files or making requests.
    if event_id is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", event_id):
        raise CaptureError("Invalid event ID")
    names = (*reference_books, target_book)
    if not all(isinstance(name, str) and re.fullmatch(r"[a-z0-9_]{1,80}", name) for name in names):
        raise CaptureError("Book names must be provider keys containing lowercase letters, digits, or underscores")
    analyze(LoadedQuotes((), (), 0), as_of=datetime.now(timezone.utc),
            reference_books=reference_books, target_book=target_book)
    client = Client(os.environ.get("ODDS_API_KEY", ""))
    output = _private_output(output)
    audit = {"schema_version": 1, "package_version": __version__, "provider": "the-odds-api-v4", "sport": SPORT, "market": MARKET,
             "region": "us", "odds_format": "american", "planned_max_credits": 1,
             "reference_books": list(reference_books), "target_book": target_book,
             "allow_partial": allow_partial, "requests": client.requests, "status": "failed"}
    try:
        events, _, listed_at = client.get("events")
        # Fail closed when quota cannot be checked before the paid call.
        preflight = client.requests[-1]["quota"]
        if preflight.get("last") != 0 or preflight.get("remaining") is None or preflight["remaining"] < 1:
            raise CaptureError("Preflight quota is unavailable, exhausted, or unexpected; no odds request was made")
        selected = select_event(events, listed_at, event_id)
        audit["event_id"] = selected
        data, raw, captured_at = client.get("odds", selected)
        _write(output / "snapshot.json", raw)
        audit.update(captured_at=captured_at.isoformat(), source_sha256=hashlib.sha256(raw).hexdigest())
        mapping = identity_mapping(data, selected)
        if utc_datetime(data.get("commence_time")) <= captured_at:
            raise CaptureError("Event has started; saved the response but did not analyze it")
        _write(output / "mapping.json", _json(mapping))
        imported = load_snapshot(output / "snapshot.json", mapping_path=output / "mapping.json",
                                 captured_at=captured_at, odds_format="american")
        audit.update(imported_rows=len(imported.entries), import_issue_count=len(imported.issues))
        _write(output / "import-diagnostics.json", _json(imported.manifest()))
        charged = client.requests[-1]["quota"].get("last")
        if charged not in (0, 1):
            raise CaptureError("Provider charge was unavailable or exceeded the planned one-credit limit; inspect capture.json")
        if not imported.entries or (imported.issues and not allow_partial):
            audit["status"] = "import_blocked"
        else:
            write_import(imported, output / "quotes.csv")
            # write_import creates its files normally; restrict permissions within the private bundle too.
            for name in ("quotes.csv", "quotes.csv.manifest.json"):
                (output / name).chmod(0o600)
            report = analyze(load_csv(output / "quotes.csv"), as_of=captured_at,
                             reference_books=reference_books, target_book=target_book)
            _write(output / "report.md", render_markdown(report))
            _write(output / "report.json", render_json(report))
            audit.update(status="analyzed" if report.comparisons else "no_target_comparisons",
                         comparisons=len(report.comparisons), analysis_issue_count=len(report.issues))
    except CaptureError as error:
        audit["error"] = str(error)
    except (OSError, ValueError, OverflowError):
        audit["error"] = "Capture processing or file write failed; inspect any saved files"
    finally:
        _write(output / "capture.json", _json(audit))
    return audit, output
