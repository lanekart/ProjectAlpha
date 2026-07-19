# BUY Signal Reconstruction

This milestone is diagnostic-only. It reconstructs BUY_DIRECTIONAL scoring
from smaller, transparent feature groups and compares those models against the
current composite score.

`PRODUCTION_INFLUENCE=false`

## Scope

The diagnostics answer whether BUY precision improves when Alpha uses:

- price structure alone;
- price plus volume;
- price plus volume plus support/resistance;
- entry timing, regime, setup, volatility, and trade-plan quality as optional
  additions;
- backward ablations from the current full component stack.

No production recommendation weights, approval thresholds, allocation logic,
entry timing, trade plans, regime policy, execution, or live providers are
modified.

## Required Commands

```bash
poetry run python -m alpha replay buy-signal-reconstruction
poetry run python -m alpha replay buy-feature-ablation
poetry run python -m alpha replay buy-false-positive-audit
poetry run python -m alpha replay buy-false-negative-audit
poetry run python -m alpha replay buy-minimal-models
poetry run python -m alpha replay buy-precision-frontier
```

All commands support:

```bash
--format text
--format json --output report.json
--format csv --output report.csv
--group-by feature|setup|regime|timing|year|horizon
--model <name>
```

## Interpretation

The report should not be read as a trade recommendation. A high-precision point
must still pass coverage, effective sample size, fold stability, concentration,
and economic quality before it can be considered research evidence.
