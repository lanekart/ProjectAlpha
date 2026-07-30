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
