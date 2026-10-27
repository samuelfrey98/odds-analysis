# Odds comparison report

As of **2030-01-15T12:05:00+00:00**. References: **Reference A, Reference B, Reference C**. Target: **Target**.

Maximum quote age: 15 minutes. Flag threshold: 2 percentage points.

Input rows: 28; parsed: 28; eligible after exclusions/deduplication: 26.
Target comparisons: 5; positive gaps meeting threshold: 2; diagnostics: 3.

Consensus: median of per-book margin-free probabilities. Minimum usable books: 2. Maximum probability range: 10 percentage points.

Each book contributes one complete pair at the target threshold. A missing quorum or excessive disagreement suppresses the probability gap. The range describes these books, not statistical confidence or model accuracy.

| Event / player | Market | Target side / line | Price | Reference lines | Reference p | Target implied p | Gap (pp) | Status | Books | Range (pp) |
| --- | --- | --- | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: |
| consensus-001 / Alex Example | player_points | over 24.5 | +120 | 24.5 | 50.00% | 45.45% | +4.55 | gap | 3/3 | 4.35 |
| consensus-001 / Alex Example | player_points | under 24.5 | -120 | 24.5 | 50.00% | 54.55% | -4.55 | within_threshold | 3/3 | 4.35 |
| consensus-002 / Blair Example | player_points | over 28.5 | +120 | 28.5 | 66.67% | 45.45% | — | reference_disagreement | 3/3 | 25.00 |
| consensus-003 / Casey Example | player_points | over 18.5 | +120 | 18.5, 20.5 | — | 45.45% | — | insufficient_references | 1/3 | 0.00 |
| consensus-004 / Drew Example | player_points | over 12.5 | +120 | 12.5 | 51.09% | 45.45% | +5.63 | gap | 2/3 | 2.17 |

## Reference evidence

### consensus-001 / Alex Example / player_points / over 24.5

Median of per-book margin-free probabilities minus target implied probability; each matching book contributes once

| Book | Source update (UTC) | Over price | Under price | Probability for target side |
| --- | --- | ---: | ---: | ---: |
| Reference A | 2030-01-15T12:00:00+00:00 | -110 | -110 | 50.00% |
| Reference B | 2030-01-15T12:01:00+00:00 | -120 | +100 | 52.17% |
| Reference C | 2030-01-15T12:02:00+00:00 | +100 | -120 | 47.83% |

### consensus-001 / Alex Example / player_points / under 24.5

Median of per-book margin-free probabilities minus target implied probability; each matching book contributes once

| Book | Source update (UTC) | Over price | Under price | Probability for target side |
| --- | --- | ---: | ---: | ---: |
| Reference A | 2030-01-15T12:00:00+00:00 | -110 | -110 | 50.00% |
| Reference B | 2030-01-15T12:01:00+00:00 | -120 | +100 | 47.83% |
| Reference C | 2030-01-15T12:02:00+00:00 | +100 | -120 | 52.17% |

### consensus-002 / Blair Example / player_points / over 28.5

Reference probability range exceeds 10 percentage points; median shown but probability gap suppressed

| Book | Source update (UTC) | Over price | Under price | Probability for target side |
| --- | --- | ---: | ---: | ---: |
| Reference A | 2030-01-15T12:00:00+00:00 | -110 | -110 | 50.00% |
| Reference B | 2030-01-15T12:01:00+00:00 | -200 | +200 | 66.67% |
| Reference C | 2030-01-15T12:02:00+00:00 | -300 | +300 | 75.00% |

### consensus-003 / Casey Example / player_points / over 18.5

Matching reference books: 1; 2 required; no probability gap calculated

| Book | Source update (UTC) | Over price | Under price | Probability for target side |
| --- | --- | ---: | ---: | ---: |
| Reference A | 2030-01-15T12:00:00+00:00 | -110 | -110 | 50.00% |

- Excluded **Reference B**: stale_quote. Complete eligible lines: none.
- Excluded **Reference C**: different_line. Complete eligible lines: 20.5.

### consensus-004 / Drew Example / player_points / over 12.5

Median of per-book margin-free probabilities minus target implied probability; each matching book contributes once

| Book | Source update (UTC) | Over price | Under price | Probability for target side |
| --- | --- | ---: | ---: | ---: |
| Reference A | 2030-01-15T12:00:00+00:00 | -110 | -110 | 50.00% |
| Reference B | 2030-01-15T12:01:00+00:00 | -120 | +100 | 52.17% |

- Excluded **Reference C**: incomplete_reference. Complete eligible lines: none.


## Diagnostics

- CSV line 19: **stale_quote** — Observation exceeds the maximum quote age; excluded
- CSV line 20: **stale_quote** — Observation exceeds the maximum quote age; excluded
- CSV line 28: **incomplete_reference** — Latest reference snapshot needs both sides at the same time and line

## Interpretation

- `gap`: a positive probability gap meets the configured threshold.
- `within_threshold`: a matched market has no qualifying positive gap.
- `different_line`: reference thresholds differ; probabilities are not compared across lines.
- `no_reference`: no complete eligible reference pair is available.
- `insufficient_references`: matching pairs exist, but fewer than the required book count; no probability or gap is assigned.
- `reference_disagreement`: the median is shown, but the probability range exceeds the configured limit; no gap is assigned.

Only pregame, positive half-integer player-prop lines are supported. Missing or invalid values are excluded, never replaced with zero. This report does not establish execution or profitability.
