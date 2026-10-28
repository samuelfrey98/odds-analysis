# Manual live capture

`odds-analysis capture` is the only command that makes provider requests or reads `ODDS_API_KEY`. It fetches one upcoming NBA event's `player_points` market in the `us` region, then runs the existing saved-snapshot importer and consensus analyzer. It has no scheduling or execution component. The portfolio demo and all automated tests work offline.

The integration follows The Odds API's [v4 event-list and event-odds documentation](https://the-odds-api.com/liveapi/guides/v4/). API access and coverage depend on the user's account. Install the package, set the key in the local environment, then run:

```sh
odds-analysis capture
```

See the [README](../README.md#capture-one-live-event) for a masked shell input example. There is no `--api-key` argument, credential file loader, or `.env` dependency. Keep credentials out of shell command literals and source files.

## Request bounds and credits

The command makes one event-list request. It requires a readable remaining-credit header of at least one and a zero-cost header before continuing. Events that have already started, malformed events, and events from other sports are ineligible. With `--event-id`, that exact event must appear as upcoming in the list; otherwise the earliest upcoming event is chosen, breaking time ties by event ID.

The command then makes at most one event-odds request. Parameters are fixed to one region, one market, ISO dates, and American prices. Under the provider's documented cost formula this plans for at most one credit. Server-side billing remains the provider's responsibility; unexpected or missing charge metadata stops analysis and remains visible in the audit. A timeout may have consumed a credit even when the client received no response. There are no automatic retries, fallback games, or loops to find a signal. A new invocation is a new request and may use another credit.

Quota headers are saved as nonnegative integers or null. Only `remaining`, `used`, and `last` are retained; arbitrary response headers are omitted. Inspect the captured values rather than assuming an old account balance still applies.

## Private outputs and provenance

The default output is `./private/capture-TIMESTAMP/`. A custom `--output` must be a new directory inside the current directory's `private/` folder. Existing paths and symlink storage paths are rejected before any request. New capture directories use mode 0700 and files use 0600 on platforms supporting POSIX permissions. Each bundle also contains a `.gitignore` that ignores its contents. These controls complement the repository's existing `private/` ignore rule; they do not encrypt files or prevent `git add --force`.

On success the bundle contains:

| File | Purpose |
| --- | --- |
| `snapshot.json` | Original successful event-odds response bytes |
| `mapping.json` | Exact provider IDs, book keys, and player names mapped to themselves; NBA sport key mapped to `nba` |
| `import-diagnostics.json` | Full import manifest, including rejected data |
| `quotes.csv` | Accepted normalized quotes |
| `quotes.csv.manifest.json` | CSV/source mapping provenance |
| `report.md`, `report.json` | Analyzer output at the capture time |
| `capture.json` | Package version, configuration, request statuses, quota metadata, capture time, source hash, and final status |

The client pins the HTTPS provider host, blocks redirects, ignores environment proxy settings, limits each response to 8 MiB, and uses a 30-second socket timeout. Only fixed error messages and numeric HTTP statuses are exposed; error bodies and credential-bearing request URLs are not saved. Successful JSON responses containing the key, including JSON-escaped copies, are rejected before their bodies are written. No request URLs are recorded.

Capture time is recorded after the response body is received. Source market `last_update` values remain quote observation times, and the report's `as_of` is the capture time. Capture does not refresh old prices. A game that starts during the request is saved but not analyzed. JSON and processing failures preserve available audit metadata; a filesystem failure or interrupted process can leave a partial directory. Inspect saved files before starting another capture.

Exact names from this provider are retained rather than inferred across different providers. Player abbreviations remain distinct names. Integer/push thresholds, invalid odds, missing timestamps, unknown market keys, and other unsupported data retain the importer's normal diagnostics. Any diagnostic blocks normalization by default. `--allow-partial` explicitly permits analysis of accepted quotes while preserving the complete diagnostic manifest; it never allows a zero-quote export.

## Analysis and local replay

Default books are `fanduel` as target and `draftkings`, `betmgm`, and `betrivers` as references. These are illustrative choices, not calibrated estimates of reliability or independence. Missing books are visible through coverage and exclusions. The existing defaults require two usable references when multiple books are configured, allow quote age up to 15 minutes, flag a positive gap of at least two percentage points, and suppress gaps above ten percentage points of reference disagreement.

```sh
odds-analysis capture --event-id YOUR_EVENT_ID \
  --reference-book draftkings --reference-book betmgm \
  --target-book fanduel --output private/my-capture
```

The saved CSV can be analyzed repeatedly without API calls. Substitute the exact `captured_at` value from `capture.json`:

```sh
odds-analysis private/my-capture/quotes.csv \
  --as-of CAPTURED_AT_WITH_OFFSET \
  --reference-book draftkings --reference-book betmgm \
  --target-book fanduel --output reports/reanalysis.md
```

The [snapshot importer](snapshot-import.md) can also reuse the saved response and mapping. Hashes identify local bytes and do not authenticate the provider. Reports describe observed market comparisons; they do not establish availability for execution or returns.

## Exit codes

| Code | Meaning |
| ---: | --- |
| 0 | Capture, normalization, and analysis succeeded with at least one target comparison; a gap is not required |
| 1 | Response was captured, but import was blocked or no target comparisons were available |
| 2 | Invalid configuration, unavailable quota/event, provider failure, unexpected billing metadata, or processing/storage failure |

Network failures and invalid provider responses are tested using an injected transport with dummy credentials. The suite never reads a real key or calls a provider. The saved provider fixture remains synthetic.
