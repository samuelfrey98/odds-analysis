# Simulation and replay

Version 0.4 provides a self-contained demonstration of how the analyzer handles a changing market. It uses invented players, one event, three reference books, and one target book. No API key, network access, current clock, saved provider response, or repository fixture is needed at runtime.

```sh
odds-analysis demo
```

This generates inputs, runs the existing consensus analyzer, and writes a replay report. The default seed is 42 and the default start is `2030-01-15T12:00:00Z`. The event starts eight simulated hours later. There are eight frames, spaced 30 seconds apart; the command does not wait between them.

## Scenarios and policy

The focus market is Alex Example's over 24.5 player points. Two background player markets remain below the flag threshold in every frame. Each frame expects three comparisons, for 24 checks overall.

| Step | Scenario | Focus comparison | Expected diagnostic codes |
| ---: | --- | --- | --- |
| 0 | Similar book estimates | `within_threshold` | none |
| 1 | References move while target retains its initial price | `gap` | none |
| 2 | Two references retain observations now 60 seconds old | `insufficient_references` | `stale_quote` |
| 3 | Reference updates restore coverage | `gap` | none |
| 4 | References quote 26.5 while target quotes 24.5 | `different_line` | none |
| 5 | Two references each lack one side | `insufficient_references` | `incomplete_reference` |
| 6 | Complete references disagree widely | `reference_disagreement` | none |
| 7 | Target price adjusts and the gap disappears | `within_threshold` | none |

The demonstration policy allows a maximum observation age of 45 seconds, requires two usable references, flags a positive gap of at least two percentage points, and suppresses gaps when reference probabilities span more than ten percentage points. These settings are saved in the manifest. See the [consensus method](consensus.md) for calculation and exclusion rules.

Reference prices come from scripted input probabilities with small seeded perturbations, a proportional 4% overround, and rounding to integer American odds. Those probabilities control the scenario; they are not estimates of actual player performance. The generator has a private random-number source and does not change Python's global random state. Different seeds vary prices while retaining the authored behavior expectations. Reproducibility applies to this generator version; it is not a promise that future generator versions will emit identical bytes.

## Generate and replay separately

```sh
odds-analysis simulate --seed 7 --start 2031-02-03T07:00:00-05:00 --output reports/scenarios
odds-analysis replay reports/scenarios
odds-analysis replay reports/scenarios --output reports/second-replay
```

The seed must be an integer from 0 to 4294967295. Start times require an explicit UTC offset and are normalized to UTC. The default output for `simulate` is `reports/simulation`; for `demo`, `reports/demo`; and for `replay`, `BUNDLE/replay`.

```text
reports/demo/
    simulation.json        Version, seed, policy, frame times, expectations
    snapshots/00.csv       Full visible quote state for each frame
    ...
    snapshots/07.csv
    replay/
        summary.md         Timeline and expected versus observed comparisons
        summary.json       Structured checks and source hashes
        frames/00.md       Detailed analyzer report for each frame
        frames/00.json
        ...
        frames/07.md
        frames/07.json
```

Every output directory must be new; commands refuse existing paths. A filesystem error can leave a partially written new directory. Choose a fresh output path after resolving the error. Generated inputs and reports belong under the Git-ignored `reports/` directory.

## What replay checks

`simulation.json` uses schema version 1. Each frame names a CSV, an explicit analysis time, expected comparison identities and statuses, and expected diagnostic codes. Policy keys are `max_age_seconds`, `min_gap_pp`, `min_reference_books`, and `max_disagreement_pp`. Quotes use the existing [CSV schema](schema.md). Frame times must increase strictly, and CSV paths must resolve inside the bundle; external paths and external symlink targets are rejected.

Each CSV is the complete visible state at that frame, rather than a list of updates to accumulate. A vanished quote is absent; a delayed quote must retain its original `observed_at` timestamp in the new snapshot. Earlier quotes are never implicitly carried forward. Each frame is analyzed independently using its explicit time, so later frames cannot influence earlier results.

Expectations are authored separately from analyzer results. Replay checks the union of expected and actual comparison identities: missing and unexpected comparisons both fail. Statuses must match for every event/player/market/line/side identity. Each frame also compares the set of actual diagnostic codes with the expected set; this does not assert diagnostic multiplicities or exact message text. A passing replay requires every comparison check and every frame's diagnostic check to pass.

You can edit a generated snapshot or its expectations and replay into a new directory to inspect a failure. The expected statuses do not change the analyzer's result. The report records SHA-256 hashes of the manifest and snapshot bytes for identifying the inputs used; these hashes are not signatures or proof that an input is trustworthy.

| Exit code | Meaning |
| ---: | --- |
| 0 | Generation succeeded, or all replay expectations matched |
| 1 | Replay completed and wrote reports, but expectations differed |
| 2 | Invalid inputs or filesystem failure |

The replay is a software demonstration with intentionally constructed cases. It does not simulate outcomes, settlement, executable orders, fills, bankroll changes, or profit. Agreement with scripted expectations establishes no predictive accuracy or real-world return.
