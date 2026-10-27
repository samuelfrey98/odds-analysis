# Odds comparison report

As of **2030-01-15T12:05:00+00:00**. Reference: **Reference**. Target: **Target**.

Maximum quote age: 15 minutes. Flag threshold: 2 percentage points.

Input rows: 19; parsed: 18; eligible after exclusions/deduplication: 10.
Target comparisons: 4; positive gaps meeting threshold: 1; diagnostics: 10.

Reference probabilities use proportional margin removal on paired prices at the same threshold and timestamp. A gap is a market comparison under that assumption, not a validated edge or a bet recommendation.

| Event / player | Market | Target side / line | Price | Reference lines | Reference p | Target implied p | Gap (pp) | Status |
| --- | --- | --- | ---: | --- | ---: | ---: | ---: | --- |
| demo-001 / Alex Example | player_points | over 24.5 | +120 | 24.5 | 50.00% | 45.45% | +4.55 | gap |
| demo-001 / Alex Example | player_points | under 24.5 | -120 | 24.5 | 50.00% | 54.55% | -4.55 | within_threshold |
| demo-002 / Blair Example | player_receiving_yards | over 45.5 | -110 | 48.5 | — | 52.38% | — | different_line |
| demo-004 / Drew Example | player_rushing_yards | over 52.5 | +120 | — | — | 45.45% | — | no_reference |

## Diagnostics

- CSV line 6: **duplicate_row** — Repeated observation removed
- CSV line 11: **stale_quote** — Observation exceeds the maximum quote age; excluded
- CSV line 12: **stale_quote** — Observation exceeds the maximum quote age; excluded
- CSV line 13: **stale_quote** — Observation exceeds the maximum quote age; excluded
- CSV line 14: **incomplete_reference** — Latest reference snapshot needs both sides at the same time and line
- CSV line 15: **invalid_row** — American odds must be a finite number
- CSV line 17: **future_quote** — Observation is later than the report time; excluded
- CSV line 18: **event_started** — Event has started; pregame analysis only
- CSV line 19: **event_started** — Event has started; pregame analysis only
- CSV line 20: **event_started** — Event has started; pregame analysis only

## Interpretation

- `gap`: a positive probability gap meets the configured threshold.
- `within_threshold`: a matched market has no qualifying positive gap.
- `different_line`: reference thresholds differ; probabilities are not compared across lines.
- `no_reference`: no complete eligible reference pair is available.

Only pregame, positive half-integer player-prop lines are supported. Missing or invalid values are excluded, never replaced with zero. This report does not establish execution or profitability.
