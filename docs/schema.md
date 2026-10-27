# Quote schema and selection policy

Every row represents one side of a pregame player-prop market from one book at one observation time. The adapter is read-only. CSV must be UTF-8 (a BOM is accepted), with one unique header for each field below and no extra columns. CSV quoting handles commas in names.

| Field | Meaning and constraints |
| --- | --- |
| `event_id` | Stable identifier shared across books; nonempty text |
| `event_start` | Scheduled start, ISO 8601 with explicit UTC offset |
| `observed_at` | Quote capture time, ISO 8601 with explicit UTC offset |
| `sport` | Lowercase identifier, e.g. `nba` or `nfl` |
| `player` | Consistent player identifier/name across books |
| `market` | Lowercase identifier, e.g. `player_points` |
| `line` | Positive half-integer below 1,000,000, e.g. `24.5` |
| `side` | `over` or `under` |
| `book` | Book identifier/name |
| `american_odds` | Finite conventional American odds, <= -100 or >= +100 |

Text fields are stripped and internal whitespace is collapsed. Sport, market, and side are lowercased; sport and market must match `[a-z][a-z0-9_]*`. Other identifiers retain case. Text fields are limited to 160 characters. Lines use decimal arithmetic for exact matching. Dates normalize to UTC.

`event_id`, sport, player, market, and event start together define a market. A quote identity additionally includes book, line, and side. Entity resolution is the adapter's responsibility: `A. Example` and `Alex Example` will not be guessed to be the same person. Matching by player name alone would incorrectly merge different events.

## Selection order

1. Reject a malformed header or CSV syntax as a file error. Record invalid rows as diagnostics; do not echo their raw values. A malformed-width row, missing price, zero odds, integer line, or naive timestamp is invalid.
2. Select the configured reference and target book names. Other books are not analyzed.
3. Reject conflicting start times for an event ID within a sport. This conservative check uses all parsed rows for the selected books, even if an observation would later be stale or future-dated.
4. Exclude observations after `as_of`, events starting at or before `as_of`, and quotes older than `max_age`. The exact maximum-age boundary is included.
5. Deduplicate identical prices for an identity/timestamp, retaining the lowest source line number. If prices disagree at the same timestamp, exclude that quote identity across the eligible window instead of falling back to another price.
6. For each reference market and line, select the latest remaining observation time. Both over and under must be present at that exact time. A newer incomplete snapshot invalidates that reference line; an older complete pair is not substituted. Source providers should assign a shared capture timestamp to both sides of a snapshot.
7. For each target identity, select its latest eligible observation. Compare only against a complete reference pair at its exact line. Reference and target observations can differ in time but both must fall inside the configured window.
8. Sort comparisons and diagnostics consistently. No wall-clock time enters the result; `as_of` is explicit.

No zero filling, line interpolation, cross-event matching, or automatic identity guessing occurs. The current comparison uses one reference book. If several complete reference lines exist, only an exact target threshold is used; the others are shown as context.

## Output

Markdown gives a compact comparison table and diagnostics. JSON includes the input/parsed/eligible counts, policy settings, event starts, quote observation times, reference probabilities, target implied probabilities, unrounded gaps, explanations, and row-level diagnostics. Rows identify physical CSV line numbers, including the header; a quoted multiline row is identified by its ending line.

`eligible_rows` counts valid selected-book observations after exclusions, conflict handling, and deduplication, including eligible older snapshots. It is not the number of final targets. Superseded prices are omitted from comparisons without being classified as invalid. `parsed_rows` includes valid rows from unselected books.

| Status | Interpretation |
| --- | --- |
| `gap` | Positive reference-minus-target probability difference meets `min_gap_pp` |
| `within_threshold` | Matched pair has no qualifying positive difference |
| `different_line` | Reference has complete markets, but none at the target line |
| `no_reference` | No complete eligible reference pair for this market |

An empty or wholly rejected dataset produces a report with diagnostics and no comparisons. CLI exit code 0 means a report was generated; it does not mean all input rows were accepted. Callers should inspect counts and diagnostics. Invalid arguments, file/schema errors, and write failures return exit code 2. An output path resolving to the input CSV is rejected.

For the Python API, `source_row=0` denotes a record without a CSV location. `Quote` validates values on construction; `analyze` accepts `LoadedQuotes` and explicit policy arguments. `expected_return(p, odds)` returns the net expectation per unit stake conditional on a supplied probability; it is not used to label market-comparison rows as validated opportunities.
