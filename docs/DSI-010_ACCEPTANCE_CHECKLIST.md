# DSI-010 External-Era Acceptance Checklist

Use this checklist only after the DSI-010 source boundary is green in permanent
GitHub CI.

## Published boundaries

- Repaired implementation boundary: `9db5ef7fe8de7743e5d6fe816d06dd9f7b008fd3`.
- Acceptance-checklist publication head: resolved from the current PR head.
- The implementation boundary passed Lint run `30244800365` and CI run
  `30244800404` before this documentation-only publication update.

## Immutable inputs

- [ ] Exact DSI-010 source commit is pinned.
- [ ] Signed DSI-009 certificate and support artifacts validate.
- [ ] Signed DSI-007 certificate and regime-strategy mapping validate.
- [ ] Frozen challenger identity is exactly `STOP-STRUCTURAL-10D`.
- [ ] External protocol is exactly 2005-01-01 through 2015-12-31.
- [ ] No observation dated 2016-01-01 or later is admitted.

## Market data

- [ ] Official NSE archives are populated through the governed Historical Truth command.
- [ ] `LEGACY_INGESTION_DATABASE_USED=false` is printed by the backfill command.
- [ ] `DOWNSTREAM_GOVERNED_A_TO_B_REBUILD_REQUIRED=true` is retained after raw population.
- [ ] Historical Truth contains adjusted candles and adjustment lineage.
- [ ] Identity and membership intervals are point-in-time complete.
- [ ] Corporate-action and price-basis evidence is reconciled.
- [ ] Missing or ambiguous security-periods remain explicit exclusions.
- [ ] Bulk market files and local databases remain outside Git.

## Benchmark

- [ ] Nifty 500 TRI provenance is recorded.
- [ ] The adjacent `.provenance.json` sidecar validates against the benchmark SHA-256.
- [ ] Official `Date` and `TotalReturnsIndex` columns are accepted.
- [ ] Benchmark dates align with governed market sessions.
- [ ] Missing governed benchmark sessions remain explicit partial coverage.
- [ ] A price index is never labelled as a total-return index.
- [ ] Benchmark source and file hashes are retained.

## Test A — Frozen-policy transport

- [ ] The signed DSI-007 regime-to-strategy mapping is unchanged.
- [ ] Incumbent and challenger signals are identical before the stop change.
- [ ] Entry, targets, trailing exit, time exit and sizing remain unchanged.
- [ ] Only the initial stop changes to point-in-time ten-session support.
- [ ] Future prices determine outcomes only and never select the stop.
- [ ] Incumbent and challenger portfolio capital paths reconcile.

## Test B — Independent-era replication

- [ ] Training, validation and test folds are chronological.
- [ ] No test fold influences its own strategy selection.
- [ ] The bounded DSI-007 strategy registry is reused unchanged.
- [ ] Test B results remain separate from Test A results.

## Required reporting

- [ ] Starting and ending capital are reported.
- [ ] Gross and net CAGR are reported.
- [ ] Benchmark and excess CAGR are reported.
- [ ] Drawdown, Sharpe, Sortino and Calmar are reported.
- [ ] Trade count, win rate, expectancy and payoff are reported.
- [ ] Costs, turnover, exposure and time in market are reported.
- [ ] Calendar-year, rolling and regime results are reported.
- [ ] Concentration and robustness diagnostics are reported.

## Determinism and certification

- [ ] Two clean runs produce byte-identical deterministic artifacts.
- [ ] Every support artifact hash validates.
- [ ] Certificate validates with `require_ready=False`.
- [ ] A ready certificate validates with `require_ready=True`.
- [ ] Executive report and certificate SHA-256 values are recorded.
- [ ] Locked Ruff version is `0.15.20`.

## Governance

- [ ] External-era tuning remains false.
- [ ] Challenger contract drift remains false.
- [ ] Automatic strategy or stop promotion remains disabled.
- [ ] Default and live behavior remain unchanged.
- [ ] All production-influence flags remain false.
- [ ] The PR remains draft and unmerged during signed acceptance.
