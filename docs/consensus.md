# Multi-book consensus

Consensus compares the target price with a documented summary of several reference markets. It does not estimate player performance or establish a profitable betting strategy.

## Calculation

For each configured book, select its latest eligible reference snapshot at the exact event, player, market, and target threshold. Both over and under must be present at that book's same observation time. Apply proportional margin removal to that pair, separately for each book.

If the resulting over probabilities are `p_1 ... p_n`, use:

```text
consensus_over_p  = median(p_1 ... p_n)
consensus_under_p = 1 - consensus_over_p
range_pp         = 100 × (largest side probability - smallest side probability)
gap_pp           = 100 × (consensus probability for target side - target implied p)
```

For an odd number of books, the median is the middle sorted probability. For an even number, it is the arithmetic mean of the two central probabilities. Computing the over median and complementing it for under keeps the two consensus outcomes complementary. The reference pair must describe exhaustive outcomes without pushes; positive half-integer player-prop lines are the supported case.

Each distinct book gets one contribution, regardless of row count, duplicate rows, or the number of older snapshots. The target book cannot also be a reference, and duplicate configured book names are rejected after whitespace normalization. Prices are never averaged directly in American-odds space.

The median is a simple, auditable summary that limits how far one extreme book can move a three-or-more-book estimate. Two books yield a midpoint and provide no such outlier protection. No book is silently removed as an outlier: all usable matching books contribute to the displayed range and evidence.

## Eligibility and exclusions

The existing validation and quote-selection rules apply independently to each book. Reference pairs cannot borrow a missing side from another book, another threshold, or another observation time. A newer incomplete reference snapshot does not fall back to an older complete pair.

For each target quote, every configured reference appears either as a contribution or an exclusion. Reasons include:

| Reason | Meaning |
| --- | --- |
| `stale_quote` | Matching source observations exceeded the configured age window |
| `future_quote` | Matching source observations were after the report time |
| `conflicting_quote` | Prices disagreed for the same quote identity and timestamp |
| `incomplete_reference` | Latest eligible reference snapshot lacked a complete pair |
| `different_line` | Complete eligible reference markets exist only at other thresholds |
| `no_reference` | No complete eligible matching reference market is available |

An excluded book can have several time-related reasons if all matching observations were rejected for different reasons. Conflict and incomplete-snapshot reasons take precedence over older rejected observations. Alternative complete eligible thresholds are shown alongside exclusions as context; they never receive interpolated probabilities.

References from different books may have different update times, provided all are eligible for the explicit report time. The window does not prove simultaneous availability. Distinct event start times for the same sport/event ID still trigger the dataset's conservative event-conflict rule, which excludes the event across the selected books.

Invalid CSV rows remain in dataset diagnostics; the analyzer cannot attribute a rejected, unparsed row to a trusted book or event. Import-stage exclusions remain in the import's companion manifest.

## Minimum coverage and disagreement policy

- One configured reference defaults to a minimum of one usable book, preserving the original behavior.
- Several configured references default to a minimum of two usable books. Set `--min-reference-books` explicitly to require more, or to allow one. It must be between one and the number of configured references.
- `--max-disagreement-pp` defaults to 10 and accepts values from 0 to 100. A range equal to the threshold is allowed; a larger range suppresses the probability gap. A numerical tolerance of `1e-10` percentage points handles floating-point equality at this boundary.

The default coverage and range limits are demonstration policies. They have not been calibrated against outcomes. A single contributing book has a displayed range of zero; that does not demonstrate agreement. Increasing the disagreement limit preserves more comparisons but also accepts wider differences between reference estimates.

| Status | Probability and gap behavior |
| --- | --- |
| `gap` | Enough references, acceptable range, and positive gap meets the flag threshold |
| `within_threshold` | Enough references and acceptable range, but no qualifying positive gap |
| `insufficient_references` | At least one complete matching pair exists, but coverage is below minimum; probability and gap are null |
| `reference_disagreement` | Enough matching books, but range exceeds the limit; median is shown and gap is null |
| `different_line` | No exact-line contributors; complete eligible reference pairs exist elsewhere |
| `no_reference` | No exact-line contributors or alternative complete reference pairs |

Quorum takes precedence over disagreement: there is no consensus estimate when the configured minimum has not been met. Excluded books never count toward that minimum.

## Report and Python API

Markdown shows the contributor count, probability range, per-book price pair and timestamp, and exclusions for multi-book reports. Single-book Markdown retains its existing compact layout. JSON includes these details for both modes, without display rounding.

Analysis JSON declares `schema_version: 2`. New top-level fields are `reference_books`, `min_reference_books`, `max_disagreement_pp`, and `consensus_method` (`median`). Each comparison adds `reference_count`, `reference_spread_pp`, `reference_contributions`, and `reference_exclusions`.

The legacy `reference_book` field is a display label containing the configured book names. `reference_observed_at` is set only for one contributing reference; a multi-book consensus has no single source timestamp. Use each contribution's `observed_at`. `reference_lines` is the union of complete eligible thresholds across the configured books.

```python
report = analyze(
    loaded_quotes,
    as_of=report_time,
    reference_books=["Reference A", "Reference B", "Reference C"],
    target_book="Target",
    min_reference_books=2,
    max_disagreement_pp=10,
)
```

`reference_book="Reference"` still works for a single book. Supplying both old and new reference arguments is rejected. Book selection is sorted so reordering the configured books or the same source records does not change the report.

## What agreement cannot establish

Books can copy one another, share data suppliers, or have the same systematic error. Multiple matching prices are not independent observations of a player's future performance. The range is a descriptive statistic of the selected markets, not a confidence interval, standard error, or guarantee of accuracy. Outcome data and a separate evaluation design would be needed to assess predictive performance.
