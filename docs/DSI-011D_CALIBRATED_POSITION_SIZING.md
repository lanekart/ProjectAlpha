# DSI-011D — Calibrated Edge and Position-Sizing Audit

## Purpose

DSI-011D tests whether the validated DSI-011C trade paths benefit from
probability- and edge-aware position sizing without changing trade selection,
entry timing, stop placement, staged exits, trailing exits, or holding-period
rules.

The audit is retrospective, diagnostic-only, gross of costs, and has
`PRODUCTION_INFLUENCE=false`.

## Frozen trade population

The input is the completed neutral-regime DSI-011C challenger artifact. The
audit replays its exact completed trade paths:

- signal date;
- next-session entry date and price;
- 5% initial stop;
- 2R partial exit;
- 3R, 20-DMA trail, time exit, or other governed final exit;
- all recorded exit dates and prices.

Only the number of shares purchased is allowed to change. A flat 1% replay must
reproduce the DSI-011C CAGR, total return, drawdown, entry count, and completed
trade count within a 0.0001 tolerance. The audit fails closed if this parity gate
is not met.

## Policies

1. `FLAT_1PCT_REFERENCE`
   - exact DSI-011C 1% risk reference;
   - no new aggregate-risk cap, solely for parity.
2. `FLAT_1PCT_RISK_CAP`
   - 1% per trade;
   - maximum 3% aggregate open initial risk.
3. `UNIFORM_1_5PCT`
   - 1.5% per trade;
   - maximum 3% aggregate open initial risk.
4. `SCORE_TIERED`
   - low score tier: 0.5%;
   - middle tier: 1.0%;
   - high tier: 1.5%;
   - first 20 signals remain unseasoned at 1.0%;
   - score thresholds use only earlier signal dates.
5. `WALK_FORWARD_EDGE`
   - first 20 completed trades remain at 1.0%;
   - later sizing uses only trades completed before the current entry date;
   - posterior win probability uses a Beta(2,2) prior;
   - negative expected R: 0.5%;
   - expected R from 0 to 0.5R: 1.0%;
   - expected R at least 0.5R: 1.5%.
6. `FRACTIONAL_KELLY`
   - first 20 completed trades remain at 1.0%;
   - later sizing uses quarter-Kelly estimated from prior realised R outcomes;
   - size is floored at 0.5% and capped at 1.5%;
   - maximum 3% aggregate open initial risk.

## Chronological controls

- Same-date outcomes are unavailable to an entry made at that day’s open.
- Same-date signal scores do not affect each other’s score tiers.
- Calibration uses a score-tier sample only after at least eight completed
  observations exist in that tier; otherwise it falls back to all prior
  completed trades.
- Drawdown of at least 8% halves the requested risk fraction.
- Drawdown of at least 12% liquidates the portfolio and permanently stops new
  entries.
- Maximum concurrent positions remains five.

## Research hurdles

A policy is flagged as meeting the initial research hurdles only when it:

- exceeds the 5.7140% DSI-011C reference CAGR;
- keeps maximum drawdown at or above -12%;
- retains profit factor of at least 1.5;
- does not trigger the hard portfolio stop.

Passing these hurdles does not authorise promotion. Calibration monotonicity,
chronological stability, transaction costs, and out-of-sample validation remain
required.

## Command

```bash
poetry run python -m alpha.research.calibrated_position_sizing \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --challenger-output .alpha/research/dsi011c_20dma_reclaim_neutral \
  --output .alpha/research/dsi011d_calibrated_position_sizing
```

## Artifacts

- `sizing_audit.json`
- `sizing_audit.md`
- `policy_comparison.json`
- `policy_comparison.csv`
- `calibration.json`
- one directory per policy containing trades, equity curve, and summary
- `manifest.json`
