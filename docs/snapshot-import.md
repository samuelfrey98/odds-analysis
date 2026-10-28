# Importing saved event-odds snapshots

`odds-analysis import-snapshot` reads local files and writes a normalized CSV plus an audit manifest. It never connects to a provider, reads browser state, loads credentials, or places wagers. The bundled fixtures contain invented events and players.

## Supported provider shape

The first adapter follows The Odds API's documented [v4 event-odds response](https://the-odds-api.com/liveapi/guides/v4/#get-event-odds). A single event object or a list of event objects is accepted. The required source fields are:

```text
event: id, sport_key, commence_time, bookmakers[]
bookmaker: key, markets[]
market: key, last_update, outcomes[]
outcome: name, description, price, point
```

`description` supplies the player alias, `name` supplies Over/Under, and `point` supplies the threshold. Source [market identifiers](https://the-odds-api.com/sports-odds-data/betting-markets.html) are mapped to the toolkit's canonical identifiers. Save prices in American format and declare `--odds-format american`; the adapter does not guess or convert decimal odds. This implementation requires market-level `last_update` and does not substitute bookmaker-level update time.

This adapter reads local files. The separate [manual capture command](live-capture.md) can acquire one supported live event. The importer does not support historical response wrappers, arbitrary HTML, moneylines, spreads, or integer/push thresholds. If collecting your own authorized data, save the JSON response body without credential-bearing request URLs, and record its capture timestamp separately. No account or purchase is required for the included example.

## Explicit mapping

See [the synthetic example mapping](../examples/snapshot_mapping.json). The five required sections are:

| Section | Source identity → canonical identity |
| --- | --- |
| `events` | Source event ID → shared event ID |
| `players` | Source event ID → object of exact player aliases → shared player name/ID |
| `sports` | Source sport key → canonical sport identifier |
| `books` | Source bookmaker key → canonical book name |
| `markets` | Source market key → canonical market identifier |

For example, aliases `A. Example` and `Alex Example` can both map to `Alex Example` inside one source event. An alias from another event is never reused automatically. Source matching is exact; player-name abbreviations, case differences, and spelling variations require explicit entries.

Different source books must retain different canonical names after whitespace normalization. This prevents a mapping from accidentally merging reference and target prices. The author of the mapping is responsible for event identity and market equivalence: do not map full-game and quarter markets to the same canonical market. Unknown source identities produce diagnostics; there is no fuzzy matching or fallback.

JSON duplicate keys, malformed documents, non-finite JSON numbers, invalid mapping sections, and colliding book mappings are file-level failures. Nested malformed containers, missing mappings, invalid outcomes, and bad source timestamps produce diagnostics at their JSON locations. The adapter exports only validated quote fields, not extra response metadata.

## Timestamp policy

Supply `--captured-at` as the actual time the response was saved, with a UTC offset. This value is recorded in the manifest and is never used to refresh a price.

Each normalized quote's `observed_at` is the source market's `last_update`. Both sides of a source market share that update timestamp. Missing, naive, or post-capture update timestamps invalidate that market. No timestamp comes from the local clock, filename, filesystem modification time, or another source level.

The later analysis still applies its independent `--as-of` and maximum-age policy. A file captured at 13:00 containing prices last updated at 12:00 will therefore be stale in a 13:00 report with a 15-minute limit. An old snapshot can still be analyzed reproducibly using its historical report time.

Capture time and source update time cannot establish that a book would have accepted a wager at that price. They describe data provenance and eligibility for a market comparison.

## Run the fixture

```sh
odds-analysis import-snapshot examples/saved_event_odds.json \
  --mapping examples/snapshot_mapping.json \
  --captured-at 2030-01-15T12:05:00Z \
  --odds-format american \
  --output reports/imported.csv

odds-analysis reports/imported.csv \
  --as-of 2030-01-15T12:05:00Z \
  --output reports/imported-report.md
```

The import writes eight quotes with no diagnostics. Analysis produces four comparisons, including two that cannot be assigned probability gaps because the reference and target thresholds differ.

## Failures and partial imports

By default any import diagnostic blocks the export and returns exit code 2. The command prints diagnostic codes and up to ten source locations without echoing raw rejected values. Correct the file/mapping and rerun, or explicitly use `--allow-partial` to export accepted records and all diagnostics in the companion manifest.

`--allow-partial` does not relax quote validation, invent missing sides, or allow a zero-quote export. A successful partial import returns exit code 0 and reports its diagnostic count. Always inspect the manifest when using that flag; subsequent CSV analysis cannot recover the rejected source records. An issue can describe a whole rejected container, so issue counts are not rejected-outcome counts.

The output CSV and its `<output-name>.manifest.json` companion must both be new paths. Input files are never modified. Existing outputs, symlinks at those output paths, and input/output collisions are rejected. A write failure rolls back files newly created by that invocation; the two-file export is not an atomic transaction across a process crash.

## Audit manifest

The companion JSON records:

- Manifest schema version, source format, and declared odds format.
- Capture time in UTC and SHA-256 hashes of the original source and mapping bytes.
- Event count, imported-row count, and complete diagnostic list.
- Each exported CSV line's source JSON path and source update timestamp.

The hashes identify the exact local inputs; they do not certify provider authenticity. The manifest excludes filenames, filesystem paths, request URLs, extra response fields, and rejected raw values. Whitespace changes to an input change its hash. Repeating an import of the same inputs and capture time to a new output path produces identical CSV and manifest contents.

Keep your own source snapshots, mappings, and exports under `private/` or `reports/` so Git ignores them. Only the synthetic fixtures belong in the repository.
