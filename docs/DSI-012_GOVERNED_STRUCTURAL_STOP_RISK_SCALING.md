# DSI-012 — Governed 1.50x Structural-Stop Risk Scaling

## Objective

Test one frozen hypothesis only:

`STOP-STRUCTURAL-10D` from the signed DSI-009 evidence boundary, replayed with a
fixed `1.50x` daily-notional overlay.

The milestone does not search leverage levels, stop levels, entries, targets,
holding periods, rankings, or financing assumptions.

## Frozen source chain

- signed DSI-009 certificate and support package;
- signed DSI-008 performance-improvement certificate;
- signed DSI-007 regime-strategy certificate;
- the same governed market database used to rehydrate DSI-009;
- incumbent next-session-open entry;
- `STOP-STRUCTURAL-10D`;
- unchanged DSI-007 portfolio policy and cost model.

The rehydrated base portfolio must reproduce the signed DSI-009 structural-stop
CAGR, drawdown, Calmar, win rate, expectancy, and trade count within fixed
tolerances before the overlay is evaluated.

ATR warm-up availability is governed by mechanism rather than by whole-row
admission. Missing ATR leaves incumbent, gap, retest, regime, structural-support,
and maximum-risk mechanisms eligible when their own required evidence is
complete. ATR-dependent entry and stop challengers remain explicitly unavailable
for those rows and cannot receive an imputed ATR value.

## Overlay definition

For each governed portfolio session:

1. read the actual structural-stop portfolio daily return and gross exposure;
2. multiply the daily return and gross exposure by exactly `1.50`;
3. charge financing only on exposure above `1.00`;
4. compound the resulting daily return into a separate research equity curve.

Base financing is fixed at `12%` annualised. A separate `18%` stress is
reported but cannot be used for selection or acceptance.

The overlay is a daily-notional research construct. It is not represented as a
whole-share executable portfolio.

## Acceptance gates

The base-financing overlay passes the retrospective mechanical target only if:

- net CAGR is at least `25%`;
- maximum drawdown is no worse than `-12%`;
- Calmar is at least `2.0`;
- daily portfolio-P&L profit factor is at least `1.5`;
- trade expectancy remains positive;
- excess CAGR over Nifty 500 TRI is at least `5 percentage points`;
- rehydration parity is exact within frozen tolerances;
- no scaled entry breaches the original liquidity-capacity limit;
- maximum gross exposure is no more than `1.25`;
- maximum scaled position fraction is no more than `25%`.

A pass permits governed forward paper evaluation only. It does not validate the
strategy, authorise live use, or promote a mechanism.

## Corrected-warehouse empirical result

The original signed DSI-009 structural-stop result could not be reproduced from
the corrected warehouse, so DSI-007, DSI-008, and DSI-009 were recertified using
the frozen comparison window and policy.

The recertified upstream evidence concluded:

- DSI-007 incumbent net CAGR: `-3.09%`;
- DSI-007 incumbent maximum drawdown: `-23.04%`;
- Nifty 500 TRI CAGR: `16.82%`;
- accepted entry champion: `NONE`;
- accepted stop champion: `NONE`;
- best descriptive stop: `STOP-ATR-225`, with `4.46%` CAGR;
- forward-paper eligibility: `false`.

The fixed `STOP-STRUCTURAL-10D` 1.50x overlay produced:

- base-financing CAGR: `-0.14%`;
- base-financing maximum drawdown: `-25.52%`;
- base-financing Calmar: `-0.01`;
- daily portfolio-P&L profit factor: `1.00`;
- stress-financing CAGR: `-0.23%`;
- acceptance passed: `false`;
- readiness: `READY_WITH_STRUCTURAL_STOP_RISK_SCALING_REJECTED`.

The hypothesis is therefore rejected. No smaller or larger multiplier, financing
rate, stop, entry, or portfolio-policy search is authorised from this result.

## Deterministic validation

Two independent DSI-012 runs using byte-identical but separately located DSI-009
certificate packages produced byte-identical DSI-012 outputs after canonicalising
source locators to filenames while retaining SHA-256 as the authoritative source
identity.

- DSI-009 deterministic file count: `26`;
- DSI-012 deterministic file count: `13`;
- `DSI012_DETERMINISTIC=true`;
- `DETERMINISTIC_RECERTIFICATION_PASSED=true`;
- both DSI-012 certificates validated successfully.

The completed milestone is a valid governed negative result, not a validated
strategy. `VALIDATED_STRATEGY=false`, `AUTOMATIC_STRATEGY_PROMOTION_ENABLED=false`,
and `PRODUCTION_INFLUENCE=false` remain authoritative.

## Commands

```bash
poetry run python -m alpha benchmark \
  decision-superiority-structural-stop-risk-scaling \
  --dsi009-certificate <DSI009_CERTIFICATE> \
  --dsi008-certificate <DSI008_CERTIFICATE> \
  --dsi007-certificate <DSI007_CERTIFICATE> \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --output artifacts/dsi012_structural_stop_risk_scaling
```

```bash
poetry run python -m alpha benchmark \
  decision-superiority-structural-stop-risk-scaling-verify \
  --certificate <DSI012_CERTIFICATE>
```

## Governance

- no leverage search;
- no financing-rate selection;
- no entry, stop, target, ranking, or portfolio-policy changes;
- no automatic strategy promotion;
- no live or production activation;
- `PRODUCTION_INFLUENCE=false`.
