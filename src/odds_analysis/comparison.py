"""Pregame quote selection and comparisons, independent of file formats."""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import math
from statistics import median

from .models import Issue, LoadedQuotes, Quote, utc_datetime
from .odds import american_to_probability, proportional_devig


@dataclass(frozen=True)
class ReferenceContribution:
    book: str
    observed_at: str
    over_odds: float
    under_odds: float
    probability: float


@dataclass(frozen=True)
class ReferenceExclusion:
    book: str
    reasons: tuple[str, ...]
    available_lines: tuple[str, ...]


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
    reference_contributions: tuple[ReferenceContribution, ...] = ()
    reference_exclusions: tuple[ReferenceExclusion, ...] = ()
    reference_count: int = 0
    reference_spread_pp: float | None = None


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
    reference_books: tuple[str, ...]
    min_reference_books: int
    max_disagreement_pp: float
    consensus_method: str = "median"
    schema_version: int = 2

    def to_dict(self) -> dict:
        return asdict(self)


def analyze(
    loaded: LoadedQuotes,
    *,
    as_of: datetime,
    reference_book: str | None = None,
    reference_books: Sequence[str] | None = None,
    target_book: str,
    max_age: timedelta = timedelta(minutes=15),
    min_gap_pp: float = 2,
    min_reference_books: int | None = None,
    max_disagreement_pp: float = 10,
) -> AnalysisReport:
    """Compare a median reference consensus with one target, with provenance.

    A reference pair must share an exact market, line, and observation time.
    Only the latest reference snapshot at each line is considered. A newer
    incomplete snapshot invalidates that line instead of reusing an older pair.
    Each distinct book gets one vote. Multiple configured books require at least
    two usable pairs by default. Excessive dispersion suppresses a gap signal.
    """
    as_of = utc_datetime(as_of)
    if reference_book is not None and reference_books is not None:
        raise ValueError("Supply reference_book or reference_books, not both")
    if reference_books is None:
        reference_books = [reference_book] if reference_book is not None else ["Reference"]
    if isinstance(reference_books, (str, bytes)) or not isinstance(reference_books, Sequence):
        raise ValueError("reference_books must be a sequence of book names")
    if not reference_books or not all(isinstance(book, str) and book.strip() for book in reference_books):
        raise ValueError("Reference books must have nonempty names")
    books = tuple(sorted(" ".join(book.split()) for book in reference_books))
    if len(set(books)) != len(books):
        raise ValueError("Reference book names must be unique after whitespace normalization")
    if not isinstance(target_book, str) or not target_book.strip():
        raise ValueError("Target book must have a nonempty name")
    target_book = " ".join(target_book.split())
    if target_book in books:
        raise ValueError("Target book cannot also be a reference book")
    if min_reference_books is None:
        min_reference_books = min(2, len(books))
    if isinstance(min_reference_books, bool) or not isinstance(min_reference_books, int) or not 1 <= min_reference_books <= len(books):
        raise ValueError("Minimum reference books must be an integer between 1 and the configured book count")
    if not math.isfinite(max_age.total_seconds()) or max_age.total_seconds() <= 0:
        raise ValueError("Maximum quote age must be positive")
    if not math.isfinite(min_gap_pp) or not 0 <= min_gap_pp <= 100:
        raise ValueError("Minimum gap must be between 0 and 100 percentage points")
    if not math.isfinite(max_disagreement_pp) or not 0 <= max_disagreement_pp <= 100:
        raise ValueError("Maximum disagreement must be between 0 and 100 percentage points")

    issues = list(loaded.issues)
    relevant = [q for q in loaded.quotes if q.book in (*books, target_book)]
    exclusion_codes = defaultdict(set)
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
        exclusion_codes[(quote.market_key, quote.line, quote.book)].add(issue[0])

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
    conflicting_pairs = {(identity[0], identity[2], identity[1]) for identity in blocked}

    reference_groups = defaultdict(list)
    target_groups = defaultdict(list)
    for quote in clean:
        if quote.book in books:
            reference_groups[(quote.market_key, quote.line, quote.book)].append(quote)
        else:
            target_groups[quote.identity].append(quote)
    pairs = {}
    reference_lines = defaultdict(set)
    book_lines = defaultdict(set)
    incomplete_pairs = set()
    for key, group in reference_groups.items():
        latest = max(q.observed_at for q in group)
        snapshot = {q.side: q for q in group if q.observed_at == latest}
        if set(snapshot) != {"over", "under"}:
            incomplete_pairs.add(key)
            issues.append(Issue("incomplete_reference", "Latest reference snapshot needs both sides at the same time and line", min(q.source_row for q in snapshot.values())))
            continue
        over, under = snapshot["over"], snapshot["under"]
        probabilities = proportional_devig(over.american_odds, under.american_odds)
        pairs[key] = (dict(zip(("over", "under"), probabilities)), latest, over, under)
        reference_lines[key[0]].add(key[1])
        book_lines[(key[0], key[2])].add(key[1])

    comparisons = []
    for group in target_groups.values():
        target = max(group, key=lambda q: q.observed_at)
        lines = tuple(str(line) for line in sorted(reference_lines[target.market_key]))
        implied = american_to_probability(target.american_odds)
        probability = gap = observed = None
        contributions = []
        exclusions = []
        for book in books:
            key = (target.market_key, target.line, book)
            pair = pairs.get(key)
            if pair is not None:
                probabilities, reference_time, over, under = pair
                contributions.append(ReferenceContribution(book, reference_time.isoformat(),
                                                           over.american_odds, under.american_odds,
                                                           probabilities[target.side]))
                continue
            available = tuple(str(line) for line in sorted(book_lines[(target.market_key, book)]))
            if key in conflicting_pairs:
                reasons = ("conflicting_quote",)
            elif key in incomplete_pairs:
                reasons = ("incomplete_reference",)
            elif exclusion_codes[key]:
                reasons = tuple(sorted(exclusion_codes[key]))
            else:
                reasons = ("different_line",) if available else ("no_reference",)
            exclusions.append(ReferenceExclusion(book, reasons, available))
        values = [contribution.probability for contribution in contributions]
        spread = 100 * (max(values) - min(values)) if values else None
        if not contributions:
            status = "different_line" if lines else "no_reference"
            explanation = (
                "Thresholds differ; no probability gap calculated"
                if lines else "No complete eligible reference pair for this market"
            )
        elif len(contributions) < min_reference_books:
            status = "insufficient_references"
            explanation = f"Matching reference books: {len(contributions)}; {min_reference_books} required; no probability gap calculated"
        else:
            # Taking the median on the over side and complementing for under
            # keeps paired consensus outcomes complementary, including even N.
            over_values = [pairs[(target.market_key, target.line, c.book)][0]["over"]
                           for c in contributions]
            over_median = median(over_values)
            probability = over_median if target.side == "over" else 1 - over_median
            if spread > max_disagreement_pp and not math.isclose(spread, max_disagreement_pp, abs_tol=1e-10, rel_tol=0):
                status = "reference_disagreement"
                explanation = f"Reference probability range exceeds {max_disagreement_pp:g} percentage points; median shown but probability gap suppressed"
            else:
                gap = 100 * (probability - implied)
                status = "gap" if gap > 0 and gap >= min_gap_pp else "within_threshold"
                explanation = "Median of per-book margin-free probabilities minus target implied probability; each matching book contributes once"
        if len(contributions) == 1:
            observed = contributions[0].observed_at
        comparisons.append(Comparison(
            event_id=target.event_id, event_start=target.event_start.isoformat(),
            sport=target.sport, player=target.player, market=target.market,
            line=str(target.line), side=target.side, target_book=target_book,
            target_odds=target.american_odds, target_observed_at=target.observed_at.isoformat(),
            reference_book=", ".join(books), reference_lines=lines,
            reference_observed_at=observed, reference_probability=probability,
            target_implied_probability=implied, gap_pp=gap, status=status,
            explanation=explanation,
            reference_contributions=tuple(contributions), reference_exclusions=tuple(exclusions),
            reference_count=len(contributions), reference_spread_pp=spread,
        ))
    comparisons.sort(key=lambda c: (c.event_start, c.event_id, c.sport, c.player, c.market, float(c.line), c.side))
    issues.sort(key=lambda i: (i.row if i.row is not None else -1, i.code, i.message))
    return AnalysisReport(
        as_of.isoformat(), ", ".join(books), target_book, max_age.total_seconds(),
        min_gap_pp, loaded.input_rows, len(loaded.quotes), len(clean),
        tuple(comparisons), tuple(issues),
        books, min_reference_books, max_disagreement_pp,
    )
