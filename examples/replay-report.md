# Simulation replay

**PASS** · Seed: **42** · Frames: **8**

Comparison checks: **24/24**. Diagnostic checks: **8/8**.

This is a seeded, scripted demonstration using invented quotes. A passing replay verifies the authored software scenarios; it does not establish predictive accuracy, arbitrage profitability, or real-world returns.

| Step | Time (UTC) | Scenario | Comparison checks | Diagnostics | Result |
| ---: | --- | --- | ---: | --- | --- |
| 0 | 2030-01-15T12:00:00+00:00 | normal | 3/3 | none | PASS |
| 1 | 2030-01-15T12:00:30+00:00 | target_lag | 3/3 | none | PASS |
| 2 | 2030-01-15T12:01:00+00:00 | stale_references | 3/3 | stale_quote | PASS |
| 3 | 2030-01-15T12:01:30+00:00 | reference_recovery | 3/3 | none | PASS |
| 4 | 2030-01-15T12:02:00+00:00 | line_mismatch | 3/3 | none | PASS |
| 5 | 2030-01-15T12:02:30+00:00 | missing_sides | 3/3 | incomplete_reference | PASS |
| 6 | 2030-01-15T12:03:00+00:00 | reference_disagreement | 3/3 | none | PASS |
| 7 | 2030-01-15T12:03:30+00:00 | target_converges | 3/3 | none | PASS |

## Expected versus observed

### 0. normal

Books have similar estimates; the target has no qualifying gap.

| Player / side / line | Expected | Observed | Result |
| --- | --- | --- | --- |
| Alex Example / over 24.5 | within_threshold | within_threshold | PASS |
| Blair Example / over 18.5 | within_threshold | within_threshold | PASS |
| Casey Example / over 32.5 | within_threshold | within_threshold | PASS |

Expected diagnostics: none. Observed diagnostics: none.

### 1. target_lag

References move while the target still shows its initial price.

| Player / side / line | Expected | Observed | Result |
| --- | --- | --- | --- |
| Alex Example / over 24.5 | gap | gap | PASS |
| Blair Example / over 18.5 | within_threshold | within_threshold | PASS |
| Casey Example / over 32.5 | within_threshold | within_threshold | PASS |

Expected diagnostics: none. Observed diagnostics: none.

### 2. stale_references

Two references still show their initial, now-stale observations.

| Player / side / line | Expected | Observed | Result |
| --- | --- | --- | --- |
| Alex Example / over 24.5 | insufficient_references | insufficient_references | PASS |
| Blair Example / over 18.5 | within_threshold | within_threshold | PASS |
| Casey Example / over 32.5 | within_threshold | within_threshold | PASS |

Expected diagnostics: stale_quote. Observed diagnostics: stale_quote.

### 3. reference_recovery

Reference updates arrive while the target price still lags.

| Player / side / line | Expected | Observed | Result |
| --- | --- | --- | --- |
| Alex Example / over 24.5 | gap | gap | PASS |
| Blair Example / over 18.5 | within_threshold | within_threshold | PASS |
| Casey Example / over 32.5 | within_threshold | within_threshold | PASS |

Expected diagnostics: none. Observed diagnostics: none.

### 4. line_mismatch

References quote a different threshold from the target.

| Player / side / line | Expected | Observed | Result |
| --- | --- | --- | --- |
| Alex Example / over 24.5 | different_line | different_line | PASS |
| Blair Example / over 18.5 | within_threshold | within_threshold | PASS |
| Casey Example / over 32.5 | within_threshold | within_threshold | PASS |

Expected diagnostics: none. Observed diagnostics: none.

### 5. missing_sides

Two references each omit one side; neither forms a complete pair.

| Player / side / line | Expected | Observed | Result |
| --- | --- | --- | --- |
| Alex Example / over 24.5 | insufficient_references | insufficient_references | PASS |
| Blair Example / over 18.5 | within_threshold | within_threshold | PASS |
| Casey Example / over 32.5 | within_threshold | within_threshold | PASS |

Expected diagnostics: incomplete_reference. Observed diagnostics: incomplete_reference.

### 6. reference_disagreement

Fresh, complete references disagree beyond the range limit.

| Player / side / line | Expected | Observed | Result |
| --- | --- | --- | --- |
| Alex Example / over 24.5 | reference_disagreement | reference_disagreement | PASS |
| Blair Example / over 18.5 | within_threshold | within_threshold | PASS |
| Casey Example / over 32.5 | within_threshold | within_threshold | PASS |

Expected diagnostics: none. Observed diagnostics: none.

### 7. target_converges

The target price adjusts and the qualifying gap disappears.

| Player / side / line | Expected | Observed | Result |
| --- | --- | --- | --- |
| Alex Example / over 24.5 | within_threshold | within_threshold | PASS |
| Blair Example / over 18.5 | within_threshold | within_threshold | PASS |
| Casey Example / over 32.5 | within_threshold | within_threshold | PASS |

Expected diagnostics: none. Observed diagnostics: none.
