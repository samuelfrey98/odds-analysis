# From browser automation to reproducible analysis

The original 2023–2024 prototype combined desktop dialogs, Selenium table extraction, screen-coordinate mouse control, custom price/line comparisons, CSV histories, and FanDuel navigation. A separate calculator explored margin removal and distribution fitting. These experiments provide the ideas behind this remake; the old source and private account records are not bundled.

## Decisions in version 0.1

**Make the first useful path offline.** A synthetic fixture and explicit report time let someone reproduce the result without accounts or changing websites. A read-only CSV adapter is the first acquisition layer.

**Separate responsibilities.** Validated records sit between adapters and analysis. Odds math has no file or UI dependencies. Reporting consumes a structured result rather than reaching into mutable global state. The only entry-point effects are argument parsing, reading an explicitly supplied file, and writing the requested report.

**Make uncertainty visible.** Missing values are rejected rather than filled with zero. Different thresholds remain different markets. A reference pair must be complete at a shared timestamp. Stale, future, conflicting, and incomplete observations produce diagnostic codes.

**Use probabilities for the math.** American odds are nonlinear, so arithmetic averaging of signed prices is unsuitable for a consensus method. This first version uses one reference book and an explicit proportional normalization of its two sides. It does not estimate a multi-book consensus.

**Separate signals from execution.** The report shows market discrepancies with the assumption that generated them. There is no login configuration, remote code runner, browser profile reuse, mouse control, or wager-placement layer. Historical click records were insufficient to establish execution or returns; those claims do not belong in this version.

**Keep runtime installation small.** The package uses the standard library, and the tests use `unittest`. Setuptools is needed only to build/install the package. A `src` layout makes installed-package testing meaningful.

## Next useful increments

1. Add a read-only adapter for an authorized snapshot/feed source, with identity mapping and capture timestamps. Exercise it with saved fixtures before connecting a live source.
2. Add a justified consensus method operating on compatible probability estimates, while retaining each book's provenance and excluding threshold mismatches.
3. Revisit the old curve-fitting experiment as an optional module. Specify an objective, validate monotonicity and domains, and test recovery on known synthetic distributions before exposing predictions.
4. Add outcome/settlement records and an event-level evaluation design if performance analysis becomes a goal. Candidate observations alone cannot establish ROI.

Public repository naming, visibility, and licensing can be decided independently of this implementation. The project does not need a remote repository to run or be tested.
