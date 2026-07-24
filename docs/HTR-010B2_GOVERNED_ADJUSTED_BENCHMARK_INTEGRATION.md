# HTR-010B2 — Governed Adjusted Benchmark Integration

## Purpose

HTR-010B2 activates corporate-action-adjusted prices only inside the immutable Canonical Alpha Benchmark Replay research boundary.

It does not enable adjusted prices in live scoring, portfolio policy, production recommendations, execution, or mutable learning.

- `ACTIVE_REPLAY_INTEGRATION=false`
- `PRODUCTION_INFLUENCE=false`

## Required upstream contracts

The command fails closed unless all of the following are valid and mutually consistent:

1. HTR-010B1 final closure report.
2. B1H replay-admission contract.
3. B1H identity-admission rows.
4. Identical signed RAW and ADJUSTED universe files.
5. Canonical HTR-005-compatible identity timeline.
6. Canonical HTR-005-compatible corporate-action timeline.
7. Historical Truth Warehouse candles and immutable snapshots for the full signed dependency window.

The final closure decision must be one of:

- `READY_FOR_GOVERNED_ADJUSTED_REPLAY`
- `READY_WITH_GOVERNED_EXCLUSIONS`

Contract contradictions, implementation defects, unsigned universes, digest mismatches, missing admitted identities, or session differences block the run.

## Point-in-time semantics

B2 does not persist one permanently adjusted candle table and reuse it across dates.

Every benchmark read is canonicalized at query time using that read's point-in-time boundary:

- A daily candle read on session `T` uses only actions effective on or before `T`.
- A historical indicator window ending on `T` rebases prior candles only with actions effective on or before `T`.
- A future-label window is transformed on one consistent end-of-window basis so pre-action and post-action bars remain comparable.
- RAW and ADJUSTED arms use the same signed identity-session population, replay dates, benchmark policy, costs, and execution model.

This prevents both look-ahead adjustment and mixed-basis labels.

## Benchmark command

```bash
poetry run python -m alpha benchmark governed-adjusted-replay \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --historical-truth-snapshots alpha_data/snapshots \
  --identity-artifact <B1_FINAL_CANONICAL_IDENTITIES_JSON> \
  --corporate-action-artifact <B1_FINAL_CANONICAL_ACTIONS_JSON> \
  --final-closure-report <B1_FINAL_CLOSURE_REPORT_JSON> \
  --admission-contract <B1H_REPLAY_CONTRACT_JSON> \
  --identity-admission <B1H_IDENTITY_ADMISSION_JSON> \
  --raw-universe <B1H_RAW_UNIVERSE_JSON> \
  --adjusted-universe <B1H_ADJUSTED_UNIVERSE_JSON> \
  --output artifacts/htr010b2_governed_adjusted_benchmark
```

The replay start, replay end, warm-up start, and outcome end are taken from the signed B1H contract rather than from ad hoc command-line dates.

## Outputs

The output directory contains:

- `raw/` — normal CABR artifacts from the governed RAW arm.
- `adjusted/` — normal CABR artifacts from the governed ADJUSTED arm.
- `store_contracts/htr010b2_raw_store_contract.json`.
- `store_contracts/htr010b2_adjusted_store_contract.json`.
- `htr010b2_governed_adjusted_benchmark_report.json`.
- `htr010b2_benchmark_comparison.json`.
- `htr010b2_executive_report.md`.

Both store contracts carry the same signed identity-session SHA-256 and distinct price-view identities.

## Comparison fields

The final report compares at least:

- replay session count;
- eligible security count;
- eligible security-observation count;
- technical candidate count;
- institutional approval count;
- trade count;
- CAGR;
- maximum drawdown;
- expectancy;
- canonical replay attestation lineage.

Differences in decision or performance metrics are expected research results. Differences in sessions, eligible population, or unsigned source contracts are unexplained parity failures.

## Readiness decisions

### `READY_FOR_GOVERNED_ADJUSTED_BENCHMARK_RESEARCH`

Issued only when the signed session and eligible-population parity checks pass. This permits adjusted-price benchmark research and report generation only.

### `BLOCKED_BY_BENCHMARK_PARITY_DIVERGENCE`

Issued when RAW and ADJUSTED arms do not share the same governed benchmark population or source-contract separation cannot be proven.

Neither state enables production influence.

## Validation gates

Before PR readiness:

```bash
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy alpha
poetry run pytest -q tests/benchmark_replay/test_governed_adjusted.py
poetry run python -m alpha benchmark --help
```

The deterministic B2 tests prove:

1. Pre-split history is rebased as of the replay date.
2. A pre-action daily read is not adjusted using a future action.
3. Future labels use one consistent end-of-window basis.
4. A non-ready B1 final closure fails closed.

## Deliberate exclusions

HTR-010B2 does not:

- change strategy weights or approval thresholds;
- optimize on adjusted replay results;
- overwrite RAW historical truth;
- mutate prior decisions or learning ledgers;
- enable adjusted prices in production consumers;
- certify economic superiority from a single replay window.

A later milestone must separately govern any expansion beyond benchmark research.
