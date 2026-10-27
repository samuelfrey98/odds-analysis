"""Basic odds math; fair probabilities are assumptions, not predictions."""

import math


def _finite(value: float, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{name} must be a finite number") from None
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def american_to_probability(odds: float) -> float:
    """Convert conventional American odds (absolute value >= 100)."""
    odds = _finite(odds, "American odds")
    if abs(odds) < 100:
        raise ValueError("American odds must be <= -100 or >= +100")
    if odds < 0:
        probability = 1 / (1 + 100 / abs(odds))
    else:
        probability = 1 / (1 + odds / 100)
    if not 0 < probability < 1:
        raise ValueError("American odds exceed supported numeric precision")
    return probability


def probability_to_american(probability: float) -> float:
    """Convert an interior probability; 50% is represented as +100."""
    probability = _finite(probability, "Probability")
    if not 0 < probability < 1:
        raise ValueError("Probability must be strictly between 0 and 1")
    if probability <= 0.5:
        odds = 100 * ((1 - probability) / probability)
    else:
        odds = -100 * (probability / (1 - probability))
    if not math.isfinite(odds):
        raise ValueError("Probability exceeds supported numeric precision")
    return odds


def proportional_devig(over_odds: float, under_odds: float) -> tuple[float, float]:
    """Normalize a complete two-outcome market using proportional margin removal.

    Both prices must describe the same line, event, and snapshot. This assumes
    two mutually exclusive, exhaustive outcomes without a push.
    """
    over = american_to_probability(over_odds)
    under = american_to_probability(under_odds)
    total = over + under
    return over / total, under / total


def expected_return(probability: float, offered_odds: float) -> float:
    """Expected net return per unit stake, conditional on a supplied probability.

    Excludes pushes, fees, limits, and execution effects.
    """
    probability = _finite(probability, "Probability")
    if not 0 <= probability <= 1:
        raise ValueError("Probability must be between 0 and 1")
    price_probability = american_to_probability(offered_odds)
    return probability / price_probability - 1
