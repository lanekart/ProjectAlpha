# DSI-010 — Official Calendar Source Workflow

## Objective

Convert the unresolved 2005–2015 calendar population into immutable official NSE
calendar sources without inferring holidays from HTTP 404 responses or special
sessions from observed weekend candles.

## Discovery

Run:

```bash
poetry run python -m alpha benchmark \
  decision-superiority-pre2016-calendar-discovery \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --manifest alpha_data/manifests/archive_manifest.jsonl \
  --output artifacts/dsi010_pre2016_calendar_discovery
```

The command exports:

- every latest manifest row whose normalized status is `unavailable`;
- every observed Saturday or Sunday candle session;
- yearly evidence requirements for 2005 through 2015;
- a summary that explicitly keeps calendar certification disabled.

Discovery rows are not calendar decisions. Their initial states are:

```text
UNREVIEWED
PENDING_OFFICIAL_EVIDENCE
PENDING_SPECIAL_SESSION_EVIDENCE
```

## Official review

For one official NSE document, prepare a CSV containing only dates supported by
that document:

```csv
trading_date,classification,description,review_state
2005-01-26,HOLIDAY,Republic Day,VERIFIED_OFFICIAL_EVIDENCE
```

Allowed classifications are exactly:

```text
HOLIDAY
SPECIAL_SESSION
```

Every row must be marked `VERIFIED_OFFICIAL_EVIDENCE`. Pending, inferred, blank,
duplicate, out-of-period or unsupported rows fail closed.

## Normalize one source

```bash
poetry run python -m alpha benchmark \
  decision-superiority-pre2016-calendar-source-build \
  --review-csv <REVIEWED_CSV> \
  --source-document <DOWNLOADED_OFFICIAL_NSE_DOCUMENT> \
  --source-url <OFFICIAL_NSE_HTTPS_URL> \
  --source-id <STABLE_SOURCE_ID> \
  --covered-year 2005 \
  --output <NORMALIZED_SOURCE_JSON>
```

The builder accepts only official NSE hosts, binds both the source document and
review CSV by SHA-256, and produces JSON compatible with Alpha's existing
`OfficialSessionCalendarEngine`.

## Final calendar certification

Once official sources jointly cover every year from 2005 through 2015:

```bash
poetry run python -m alpha benchmark \
  decision-superiority-pre2016-calendar-certify \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --manifest alpha_data/manifests/archive_manifest.jsonl \
  --official-source <SOURCE_1_JSON> \
  --official-source <SOURCE_2_JSON> \
  --output artifacts/dsi010_pre2016_calendar
```

A ready result requires all unavailable weekdays to reconcile to official
holidays and every observed official special session to reconcile without
conflict.

## Source boundary

Discovery and reviewed-source implementation boundary:

`afabdfb2c1ec1d1f36467e2faf092d86d34c9835`

Permanent GitHub validation must pass on the subsequent owner-authored
publication head before local use.

## Governance

```text
CALENDAR_INFERENCE_FROM_HTTP_404_PERMITTED=false
CALENDAR_INFERENCE_FROM_OBSERVED_CANDLES_PERMITTED=false
SYNTHETIC_HOLIDAYS_PERMITTED=false
PRODUCTION_INFLUENCE=false
```
