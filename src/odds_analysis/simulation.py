"""Seeded, scripted market scenarios. No real players, outcomes, or network."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import csv
import json
from pathlib import Path
import random

from .adapters.csv_input import FIELDS
from .models import Quote, utc_datetime
from .odds import probability_to_american

BOOKS = ("Reference A", "Reference B", "Reference C")
TARGET = "Target"
DEFAULT_START = "2030-01-15T12:00:00Z"
POLICY = {"max_age_seconds": 45, "min_gap_pp": 2,
          "min_reference_books": 2, "max_disagreement_pp": 10}
SCENARIOS = (
    ("normal", "Books have similar estimates; the target has no qualifying gap.", "within_threshold", ()),
    ("target_lag", "References move while the target still shows its initial price.", "gap", ()),
    ("stale_references", "Two references still show their initial, now-stale observations.", "insufficient_references", ("stale_quote",)),
    ("reference_recovery", "Reference updates arrive while the target price still lags.", "gap", ()),
    ("line_mismatch", "References quote a different threshold from the target.", "different_line", ()),
    ("missing_sides", "Two references each omit one side; neither forms a complete pair.", "insufficient_references", ("incomplete_reference",)),
    ("reference_disagreement", "Fresh, complete references disagree beyond the range limit.", "reference_disagreement", ()),
    ("target_converges", "The target price adjusts and the qualifying gap disappears.", "within_threshold", ()),
)


@dataclass(frozen=True)
class ExpectedComparison:
    event_id: str
    player: str
    market: str
    line: str
    side: str
    status: str

    def to_dict(self) -> dict:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class SimulationFrame:
    scenario: str
    description: str
    as_of: datetime
    quotes: tuple[Quote, ...]
    expected: tuple[ExpectedComparison, ...]
    expected_issue_codes: tuple[str, ...]


@dataclass(frozen=True)
class Simulation:
    seed: int
    start: datetime
    frames: tuple[SimulationFrame, ...]

    def manifest(self) -> dict:
        return {
            "schema_version": 1, "generator_version": 1,
            "seed": self.seed, "start": self.start.isoformat(),
            "reference_books": list(BOOKS), "target_book": TARGET,
            "policy": dict(POLICY),
            "frames": [
                {"scenario": frame.scenario, "description": frame.description,
                 "as_of": frame.as_of.isoformat(), "csv": f"snapshots/{index:02}.csv",
                 "expected": [item.to_dict() for item in frame.expected],
                 "expected_issue_codes": list(frame.expected_issue_codes)}
                for index, frame in enumerate(self.frames)
            ],
        }


def generate(seed: int = 42, start: str | datetime = DEFAULT_START) -> Simulation:
    """Generate eight current-state snapshots with seeded price perturbations.

    The scenario expectations are authored independently of analyzer results.
    The invented probabilities are input controls, not estimated real-world odds.
    """
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**32:
        raise ValueError("Seed must be an integer from 0 to 4294967295")
    start = utc_datetime(start)
    rng = random.Random(seed)
    event_start = start + timedelta(hours=8)

    def quote(player, line, side, book, price, observed):
        return Quote("simulation-001", event_start, observed, "nba", player,
                     "player_points", Decimal(line), side, book, price)

    def pair(player, line, book, probability, observed):
        # A symmetric 4% proportional overround, followed by integer price rounding.
        return [quote(player, line, side, book,
                      round(probability_to_american(p * 1.04)), observed)
                for side, p in (("over", probability), ("under", 1 - probability))]

    def perturbed(center):
        return center + rng.randint(-3, 3) / 1000

    initial_refs = {book: pair("Alex Example", "24.5", book, perturbed(0.5), start)
                    for book in BOOKS}
    initial_target = quote("Alex Example", "24.5", "over", TARGET,
                           round(probability_to_american(0.55)), start)
    frames = []
    for index, (scenario, description, expected_status, issue_codes) in enumerate(SCENARIOS):
        as_of = start + timedelta(seconds=30 * index)
        quotes = []
        for book_index, book in enumerate(BOOKS):
            if index == 0 or (index == 2 and book_index > 0):
                rows = initial_refs[book]
            else:
                center = (0.35, 0.55, 0.75)[book_index] if index == 6 else 0.60
                line = "26.5" if index == 4 else "24.5"
                rows = pair("Alex Example", line, book, perturbed(center), as_of)
            if index == 5 and book_index == 1:
                rows = rows[:1]
            elif index == 5 and book_index == 2:
                rows = rows[1:]
            quotes.extend(rows)
        if index <= 1:
            quotes.append(initial_target)
        else:
            target_p = 0.65 if index == 7 else 0.55
            quotes.append(quote("Alex Example", "24.5", "over", TARGET,
                                round(probability_to_american(target_p)), as_of))
        expectations = [ExpectedComparison("simulation-001", "Alex Example", "player_points",
                                            "24.5", "over", expected_status)]
        # Background markets change slightly but keep an intentionally nonqualifying target.
        for player, line, center in (("Blair Example", "18.5", 0.40),
                                     ("Casey Example", "32.5", 0.45)):
            moving_center = perturbed(center)
            for book in BOOKS:
                quotes.extend(pair(player, line, book, perturbed(moving_center), as_of))
            quotes.append(quote(player, line, "over", TARGET,
                                round(probability_to_american(moving_center + 0.05)), as_of))
            expectations.append(ExpectedComparison("simulation-001", player, "player_points",
                                                    line, "over", "within_threshold"))
        frames.append(SimulationFrame(scenario, description, as_of, tuple(quotes),
                                      tuple(expectations), issue_codes))
    return Simulation(seed, start, tuple(frames))


def write_simulation(simulation: Simulation, output: str | Path) -> Path:
    """Create a new bundle directory; existing paths are never overwritten."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    snapshots = output / "snapshots"
    snapshots.mkdir()
    for index, frame in enumerate(simulation.frames):
        with (snapshots / f"{index:02}.csv").open("x", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(FIELDS)
            for q in frame.quotes:
                writer.writerow((q.event_id, q.event_start.isoformat(), q.observed_at.isoformat(),
                                 q.sport, q.player, q.market, str(q.line), q.side, q.book,
                                 str(q.american_odds)))
    (output / "simulation.json").write_text(
        json.dumps(simulation.manifest(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output
