# Historical Truth Acquisition (HTA v1.0)

## Purpose

HTA populates the frozen Alpha Data Platform architecture with official market
history while preserving source bytes, source rights, provenance, and replay
isolation. It creates an isolated `WAREHOUSE_v2_CANDIDATE`; it does not replace
Warehouse v1 or migrate any replay consumer.

`PRODUCTION_INFLUENCE=false` is an enforced model invariant.

## Source Rights

Alpha does not assume that an exchange web page grants historical retention or
automated acquisition rights. Automated NSE and BSE records remain
`LICENCE_REQUIRED` until a valid agreement is registered. Manual import requires
the operator to attest that each source was lawfully obtained and may be retained
for internal research.

No public-page scraper, cookie flow, CAPTCHA handling, browser automation, or
terms bypass is part of HTA. Missing licensed data remains unknown and fails
certification.

## Stage Order

1. `SECURITY_IDENTITY` produces `SECURITY_MASTER_v1`.
2. `TRADING_CALENDAR` produces `TRADING_CALENDAR_v1`.
3. `DAILY_EQUITY_HISTORY` produces `DAILY_MARKET_HISTORY_v1`.
4. `INDEX_HISTORY` produces `INDEX_HISTORY_v1`.
5. `INDEX_MEMBERSHIP` produces `INDEX_MEMBERSHIP_v1`.
6. `CORPORATE_ACTIONS` produces `CORPORATE_ACTIONS_v1`.
7. `DELIVERY_HISTORY` produces `DELIVERY_HISTORY_v1`.

Every stage is independently evidenced and certified. Downstream stages cannot
receive a stage PASS while prerequisite stages are not PASS.

## Manual Source Layout

Place lawfully obtained source files under a dataset-specific directory:

```text
official-sources/
  nse-security-master/
  nse-trading-calendar/
  nse-equity-bhavcopy/
  bse-equity-bhavcopy/
  nse-index-nifty-50-ohlcv/
  nse-historical-index-membership/
  nse-corporate-actions/
  bse-corporate-actions/
  nse-delivery/
```

CSV, TXT, ZIP, and GZIP source files are supported by the immutable archive.
Historical membership input must explicitly contain effective dates and members,
additions, or removals. Alpha never substitutes current constituents.

Run:

```bash
poetry run python -m alpha data acquire \
  --source-dir official-sources \
  --lawfully-obtained \
  --since 2016-01-01 \
  --until 2026-07-19 \
  --resume --verify --parallel 4
```

## Restart and Integrity

Original bytes are content-addressed by SHA-256 and never overwritten. Atomic
checkpoints record attempts, verified byte counts, checksum, bounded exponential
retry delay, and terminal state. Repeating an import is idempotent. A file that
changes between preflight and custody is marked corrupt and rejected.

Licensed provider adapters implement the chunked connector protocol. The download
coordinator persists each verified byte offset, resumes partial files after an
interruption, retries with bounded exponential backoff, recovers from checksum
corruption by restarting only the affected partition, and downloads independent
partitions concurrently. HTA deliberately registers no NSE/BSE network connector
until the relevant acquisition and retention rights are configured.

Derived Parquet, JSON, CSV, and Markdown artifacts can be regenerated from the
immutable raw vault and candidate DuckDB store.

## Reconciliation

HTA compares candidate NSE and BSE observations with matching Legacy observations
where available. Every price, volume, missing observation, identity, symbol, and
corporate-action discrepancy is classified. Reconciliation never selects a source
winner and performs zero automatic overwrites.

## Certification

Dataset certification evaluates:

- source-file presence and SHA-256 verification;
- parser acceptance and quarantine;
- requested date coverage;
- schema consistency;
- identity resolution;
- unresolved reconciliation findings.

Statuses are `PASS`, `PASS_WITH_WARNINGS`, and `FAIL`. Only a dataset-level PASS
is eligible for ACTIVE status. The warehouse candidate requires every mandatory
dataset and logical stage to pass and a Historical Truth Score of at least 97.00.
Even then, the result is only `READY_FOR_ACTIVATION_REVIEW`; HTA never activates
it automatically.

## Commands

```text
alpha data acquire
alpha data certify
alpha data reconcile
alpha data scorecard
alpha data warehouse
```

The acquisition command supports `--dataset`, `--resume`, `--verify`, `--force`,
`--parallel`, `--since`, and `--until`. `--force` only reruns derivation and
verification; it cannot bypass authorization or mutate archived bytes.

## Required Outputs

HTA writes the acquisition manifest, security master, daily/index/membership/
corporate-action/delivery Parquet datasets, reconciliation CSV, certification and
scorecard reports, candidate metadata, and an executive report under
`.alpha/data_platform/HTA_v1.0` by default.

When official inputs are absent, those outputs still exist as typed empty
artifacts, certifications fail, the truth score reflects missing evidence, and
the candidate remains `NOT_READY`.
