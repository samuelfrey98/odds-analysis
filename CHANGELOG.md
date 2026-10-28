# Changelog

## 0.5.0 — Portfolio release

The first release packages the completed remake as a standard-library Python toolkit. It includes the earlier development milestones below, plus an MIT license, a self-contained demo, and guides for reproducible local analysis.

### Included

- Strict CSV validation, American-odds probability math, paired-side margin removal, and pregame snapshot selection.
- Same-event/player/market/threshold comparisons with explicit freshness, conflict, and missing-data diagnostics.
- Median consensus across separately normalized reference books, minimum coverage, disagreement controls, and per-book evidence.
- Saved The Odds API v4 event-odds import with exact identity mappings, source timestamps, and hashed audit manifests.
- Seeded eight-frame simulation and independent expected-versus-observed replay checks.
- Manual one-event NBA player-points capture, environment-only credentials, quota checks, private storage, and no automatic retries.
- Deterministic Markdown/JSON reports, synthetic examples, and 125 automated tests on Python 3.11–3.14.

### Validation and scope

The offline demo passes 24 comparison checks and eight diagnostic checks. A manual live capture was also verified on 2026-10-28: 265 quotes imported without import errors, producing 22 comparisons and no qualifying gaps. The saved inputs reproduce the original reports exactly. Real provider responses and account data are excluded from the release.

The toolkit supports positive half-integer pregame player-prop thresholds. It does not model pushes, outcomes, execution, settlement, or returns. Reference consensus is an explicit comparison assumption, not a calibrated prediction.

### Development milestones

| Version | Milestone |
| --- | --- |
| 0.1 | Offline CSV analysis and explainable reports |
| 0.2 | Saved provider snapshot importer and provenance |
| 0.3 | Multi-book median consensus and coverage controls |
| 0.4 | Seeded simulation and replay |
| 0.5 | Bounded manual capture and portfolio packaging |
