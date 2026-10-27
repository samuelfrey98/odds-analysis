"""Validated quote records and diagnostics shared by input adapters."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re

from .odds import american_to_probability


def utc_datetime(value: str | datetime) -> datetime:
    try:
        result = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(result, datetime) or result.utcoffset() is None:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("Timestamps must be ISO 8601 with an explicit UTC offset") from None
    return result.astimezone(timezone.utc)


@dataclass(frozen=True)
class Quote:
    event_id: str
    event_start: datetime
    observed_at: datetime
    sport: str
    player: str
    market: str
    line: Decimal
    side: str
    book: str
    american_odds: float
    source_row: int = 0

    def __post_init__(self) -> None:
        for name in ("event_id", "sport", "player", "market", "side", "book"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be nonempty text")
            value = " ".join(value.split())
            if name in ("sport", "market", "side"):
                value = value.lower()
            if len(value) > 160:
                raise ValueError(f"{name} exceeds 160 characters")
            object.__setattr__(self, name, value)
        for name in ("sport", "market"):
            if not re.fullmatch(r"[a-z][a-z0-9_]*", getattr(self, name)):
                raise ValueError(f"{name} must be a lowercase identifier, e.g. player_points")
        if self.side not in ("over", "under"):
            raise ValueError("side must be over or under")
        try:
            line = Decimal(str(self.line))
            valid_line = line.is_finite() and 0 < line < 1_000_000 and line % 1 == Decimal("0.5")
        except InvalidOperation:
            valid_line = False
        if not valid_line:
            raise ValueError("line must be a positive half-integer below 1000000; integer/push markets are unsupported")
        object.__setattr__(self, "line", line)
        american_to_probability(self.american_odds)
        object.__setattr__(self, "american_odds", float(self.american_odds))
        object.__setattr__(self, "event_start", utc_datetime(self.event_start))
        object.__setattr__(self, "observed_at", utc_datetime(self.observed_at))

    @property
    def market_key(self) -> tuple:
        return self.event_id, self.sport, self.player, self.market, self.event_start

    @property
    def identity(self) -> tuple:
        return self.market_key, self.book, self.line, self.side


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    row: int | None = None


@dataclass(frozen=True)
class LoadedQuotes:
    quotes: tuple[Quote, ...]
    issues: tuple[Issue, ...]
    input_rows: int
