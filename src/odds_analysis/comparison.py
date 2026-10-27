"""Pregame quote selection and comparisons, independent of file formats."""

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import math

from .models import Issue, LoadedQuotes, Quote, utc_datetime
from .odds import american_to_probability, proportional_devig


@dataclass(frozen=True)
class Comparison:
    event_id: str
    event_start: str
    sport: str
    player: str
    market: str
    line: str
    side: str
    target_book: str
    target_odds: float
    target_observed_at: str
    reference_book: str
    reference_lines: tuple[str, ...]
    reference_observed_at: str | None
    reference_probability: float | None
    target_implied_probability: float
    gap_pp: float | None
    status: str
    explanation: str


@dataclass(frozen=True)
class AnalysisReport:
    as_of: str
    reference_book: str
    target_book: str
    max_age_seconds: float
    min_gap_pp: float
    input_rows: int
    parsed_rows: int
    eligible_rows: int
    comparisons: tuple[Comparison, ...]
    issues: tuple[Issue, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def analyze(
    loaded: LoadedQuotes,
    *,
    as_of: datetime,
    reference_book: str,
    target_book: str,
    max_age: timedelta = timedelta(minutes=15),
    min_gap_pp: float = 2,
) -> AnalysisReport:
    """Compare one reference book with one target, with explicit exclusions.

    A reference pair must share an exact market, line, and observation time.
    Only the latest reference snapshot at each line is considered. A newer
    incomplete snapshot invalidates that line instead of reusing an older pair.
    """
    as_of = utc_datetime(as_of)
    reference_book = " ".join(reference_book.split())
    target_book = " ".join(target_book.split())
    if not reference_book or not target_book or reference_book == target_book:
        raise ValueError("Reference and target books must be distinct, nonempty names")
    if not math.isfinite(max_age.total_seconds()) or max_age.total_seconds() <= 0:
        raise ValueError("Maximum quote age must be positive")
    if not math.isfinite(min_gap_pp) or not 0 <= min_gap_pp <= 100:
        raise ValueError("Minimum gap must be between 0 and 100 percentage points")

    issues = list(loaded.issues)
    relevant = [q for q in loaded.quotes if q.book in (reference_book, target_book)]
    starts = defaultdict(set)
    for quote in relevant:
        starts[(quote.sport, quote.event_id)].add(quote.event_start)
    eligible = []
    for quote in relevant:
        if len(starts[(quote.sport, quote.event_id)]) > 1:
            issue = ("event_conflict", "Conflicting start times for the same event; excluded")
        elif quote.observed_at > as_of:
            issue = ("future_quote", "Observation is later than the report time; excluded")
        elif quote.event_start <= as_of:
            issue = ("event_started", "Event has started; pregame analysis only")
        elif as_of - quote.observed_at > max_age:
            issue = ("stale_quote", "Observation exceeds the maximum quote age; excluded")
        else:
            eligible.append(quote)
            continue
        issues.append(Issue(*issue, quote.source_row))

    # Resolve duplicates within an exact observation, before selecting snapshots.
    observations = defaultdict(list)
    for quote in eligible:
        observations[(quote.identity, quote.observed_at)].append(quote)
    clean = []
    blocked = set()
    for key, group in observations.items():
        group.sort(key=lambda q: q.source_row)
        if len({q.american_odds for q in group}) > 1:
            blocked.add(key[0])
            for quote in group:
                issues.append(Issue("conflicting_quote", "Conflicting prices at one timestamp; quote identity excluded", quote.source_row))
            continue
        clean.append(group[0])
        for quote in group[1:]:
            issues.append(Issue("duplicate_row", "Repeated observation removed", quote.source_row))
    # Do not fall back to an older price after an ambiguous observation.
    clean = [q for q in clean if q.identity not in blocked]

    reference_groups = defaultdict(list)
    target_groups = defaultdict(list)
    for quote in clean:
        if quote.book == reference_book:
            reference_groups[(quote.market_key, quote.line)].append(quote)
        else:
            target_groups[quote.identity].append(quote)
    pairs = {}
    reference_lines = defaultdict(list)
    for key, group in reference_groups.items():
        latest = max(q.observed_at for q in group)
        snapshot = {q.side: q for q in group if q.observed_at == latest}
        if set(snapshot) != {"over", "under"}:
            issues.append(Issue("incomplete_reference", "Latest reference snapshot needs both sides at the same time and line", min(q.source_row for q in snapshot.values())))
            continue
        over, under = snapshot["over"], snapshot["under"]
        probabilities = proportional_devig(over.american_odds, under.american_odds)
        pairs[key] = (dict(zip(("over", "under"), probabilities)), latest)
        reference_lines[key[0]].append(key[1])

    comparisons = []
    for group in target_groups.values():
        target = max(group, key=lambda q: q.observed_at)
        lines = tuple(str(line) for line in sorted(reference_lines[target.market_key]))
        pair = pairs.get((target.market_key, target.line))
        implied = american_to_probability(target.american_odds)
        probability = gap = observed = None
        if pair is None:
            status = "different_line" if lines else "no_reference"
            explanation = (
                "Thresholds differ; no probability gap calculated"
                if lines else "No complete eligible reference pair for this market"
            )
        else:
            probabilities, reference_time = pair
            probability = probabilities[target.side]
            observed = reference_time.isoformat()
            gap = 100 * (probability - implied)
            status = "gap" if gap > 0 and gap >= min_gap_pp else "within_threshold"
            explanation = "Reference probability minus target implied probability; proportional margin removal on reference pair"
        comparisons.append(Comparison(
            event_id=target.event_id, event_start=target.event_start.isoformat(),
            sport=target.sport, player=target.player, market=target.market,
            line=str(target.line), side=target.side, target_book=target_book,
            target_odds=target.american_odds, target_observed_at=target.observed_at.isoformat(),
            reference_book=reference_book, reference_lines=lines,
            reference_observed_at=observed, reference_probability=probability,
            target_implied_probability=implied, gap_pp=gap, status=status,
            explanation=explanation,
        ))
    comparisons.sort(key=lambda c: (c.event_start, c.event_id, c.sport, c.player, c.market, float(c.line), c.side))
    issues.sort(key=lambda i: (i.row if i.row is not None else -1, i.code, i.message))
    return AnalysisReport(
        as_of.isoformat(), reference_book, target_book, max_age.total_seconds(),
        min_gap_pp, loaded.input_rows, len(loaded.quotes), len(clean),
        tuple(comparisons), tuple(issues),
    )
