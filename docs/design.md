# From browser automation to reproducible analysis

The original 2023–2024 prototype combined desktop dialogs, Selenium table extraction, screen-coordinate mouse control, custom price/line comparisons, CSV histories, and FanDuel navigation. A separate calculator explored margin removal and distribution fitting. These experiments provide the ideas behind this remake; the old source and private account records are not bundled.

## Design decisions

**Make the first useful path offline.** Synthetic fixtures and explicit report times let someone reproduce results without accounts or changing websites. Version 0.4 adds a one-command seeded simulation: eight scripted snapshots, independent expected behaviors, and a replay report showing whether each expectation matched. The installed demo generates its own inputs and works outside the repository.

**Separate responsibilities.** Validated records sit between adapters and analysis. Odds math has no file or UI dependencies. Reporting consumes a structured result rather than reaching into mutable global state. The only entry-point effects are argument parsing, reading an explicitly supplied file, and writing the requested report.

**Make uncertainty visible.** Missing values are rejected rather than filled with zero. Different thresholds remain different markets. A reference pair must be complete at a shared timestamp. Stale, future, conflicting, and incomplete observations produce diagnostic codes.

**Use probabilities for the math.** American odds are nonlinear, so arithmetic averaging of signed prices is unsuitable for a consensus method. Version 0.1 used one reference book and proportional normalization of its two sides. Version 0.3 adds an equal-book median of separately normalized reference probabilities, with explicit coverage and disagreement controls and per-book provenance.

**Separate signals from execution.** The report shows market discrepancies with the assumption that generated them. There is no login configuration, remote code runner, browser profile reuse, mouse control, or wager-placement layer. Historical click records were insufficient to establish execution or returns; those claims do not belong in this version.

**Keep runtime installation small.** The package uses the standard library, and the tests use `unittest`. Setuptools is needed only to build/install the package. A `src` layout makes installed-package testing meaningful.

## Next useful increments

1. Expand acquisition only when the capture contract is clear. Version 0.5 adds a manual one-event NBA player-points capture, environment-only credentials, private storage, quota metadata, and no retries. It uses the existing offline importer and analyzer; every automated test remains offline. Other sports, markets, and scheduled capture need their own explicit scope and request budget.
2. Evaluate consensus behavior against suitable outcome data before claiming predictive value. Version 0.3 implements the auditable offline calculation and synthetic cases, not a calibrated model.
3. Revisit the old curve-fitting experiment as an optional module. Specify an objective, validate monotonicity and domains, and test recovery on known synthetic distributions before exposing predictions.
4. Add outcome/settlement records and an event-level evaluation design if performance analysis becomes a goal. Candidate observations alone cannot establish ROI.

The repository is private while development continues. Licensing and any future public release can be decided independently of this implementation.
