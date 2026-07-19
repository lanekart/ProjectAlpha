# Adaptive Indicator Weight Research Engine v1.0

## Purpose

The Adaptive Indicator Weight Research Engine evaluates whether Alpha's existing
evidence components contribute unique, stable realised payoff. It may freeze a
candidate research policy. It cannot alter recommendation scoring, deployed
weights, portfolio allocation, broker activity, or production policy.

The engine optimises for out-of-sample expectancy, stability, uniqueness,
drawdown control, and cross-population robustness. It does not optimise historical
net profit and does not treat win-rate correlation as causal contribution.

## Immutable Layers

Alpha maintains three separate weight layers:

1. `CANONICAL_WEIGHTS`: the immutable baseline.
2. `RESEARCH_PROPOSED_WEIGHTS`: frozen candidate policies.
3. `DEPLOYED_WEIGHTS`: the separately identified production layer.

The canonical baseline remains:

| Component | Weight |
|---|---:|
| Price Structure | 20 |
| Volume | 17 |
| Trend | 15 |
| Relative Strength | 13 |
| Retracement | 10 |
| Candlestick | 8 |
| Breakout / Setup | 7 |
| Market Regime | 5 |
| Sector | 3 |
| Risk / Volatility | 2 |

## Evidence Contract

Only completed, eligible outcomes can enter the research dataset. Pending,
active, missed, not-triggered, data-missing, and otherwise unresolved outcomes
are excluded. A completed record must retain actual entry, stop, exit, realised
return, realised R multiple, transaction costs, component score availability,
dataset version, policy version, and provenance.

Evidence partitions are never silently mixed:

- `DEVELOPMENT`
- `VALIDATION`
- `HOLDOUT`
- `FORWARD_OBSERVED`

The performance-ledger adapter accepts only `EXITED` outcomes. The forward
validation adapter accepts only immutable exited journal rows with actual prices
and transaction-cost evidence. Candidate-learning, approval, directional, and
Closed Learning outputs that lack complete trade economics remain diagnostic
context; they are not promoted into completed payoff evidence.

## Research Methods

### Matched Ablation

Ablations require matched with-component and without-component cohorts. Matching
holds symbol, date, strategy, setup, stop policy, exit policy, costs, dataset, and
chronological partition constant. Reports retain expectancy, win rate, winner and
loser payoff, profit factor, drawdown, trade count, and holding-period deltas.

### Marginal Contribution

The engine reports separate, inspectable measures:

- standalone median-split payoff difference;
- deterministic regularised regression coefficient on realised R;
- leave-one-component-out prediction-error change;
- chronological-partition permutation importance;
- setup-and-regime conditional contribution;
- chronological partition uncertainty range.

None of these is presented as a single opaque importance score.

### Overlap and Stability

Every component pair is assessed for score correlation, active-candidate overlap,
approval overlap, mutual information, setup/regime overlap, and source lineage.
Same-source evidence is not counted as independent confirmation.

Contribution stability is measured across partitions, sectors, setups, regimes,
horizons, five-year calendar eras, and forward outcomes. Positive development
performance followed by negative holdout performance is unstable and cannot earn
an increase.

## Proposal Guardrails

The transparent raw formula is:

```text
canonical weight
* payoff multiplier
* confidence multiplier
* stability multiplier
* uniqueness multiplier
```

The result is shrunk toward canonical, bounded, and normalised to 100%. Defaults:

- maximum relative change per revision: 20%;
- maximum component weight: 30%;
- minimum component weight: 0%;
- weak evidence receives strong canonical shrinkage;
- negative holdout contribution cannot increase a component;
- insufficient holdout evidence remains research-only;
- same-source and high-overlap evidence receives an explicit penalty.

Conditional research policies require minimum samples. Resolution uses:

```text
setup + regime -> setup -> regime -> universal adaptive -> canonical
```

Horizon-specific evidence is supported as a separate fallback before universal
weights when no setup or regime policy qualifies. Every resolution reports its
source hierarchy level.

## Policy Governance

Candidate IDs use `ALPHA_WEIGHT_RESEARCH_NNNN`. Registry writes are append-safe,
idempotent for identical manifests, and reject replacement under an existing ID.
A candidate can reach `PROMOTE_TO_POLICY_REVIEW` only after validation, holdout,
and forward-observed evidence all pass expectancy, profit-factor, drawdown,
diversity, cost, stability, overlap, and sample gates.

`PROMOTE_TO_POLICY_REVIEW` means human review. It never means deployment.

## TradingView Research Laboratory

TRL exports frozen presets:

- `ALPHA_CANONICAL`
- `NO_RETRACEMENT`
- `PRICE_ONLY`
- `PRICE_VOLUME`
- `PRICE_VOLUME_TREND`
- `MINIMAL_ALPHA`
- `ADAPTIVE_CANDIDATE_<ID>`

`trl import-weight-results` imports measured Strategy Tester CSV rows under a
stable research ID. R-normalised expectancy and payoff fields are mandatory for
ablation evidence. TradingView cannot learn, mutate, or persist weights by itself.

## IRD Integration

Every frozen candidate can be registered as a permanent IRD experiment. The
diagnostic plugin reports, when measured, the strongest positive and negative
components, most redundant pair, most stable and conditional components,
highest-value next ablation, current candidate policy, and promotion blockers.
Unavailable metrics remain explicitly unavailable.

## CLI

```bash
poetry run python -m alpha adaptive-weights audit
poetry run python -m alpha adaptive-weights contributions
poetry run python -m alpha adaptive-weights overlap
poetry run python -m alpha adaptive-weights stability
poetry run python -m alpha adaptive-weights propose
poetry run python -m alpha adaptive-weights conditional
poetry run python -m alpha adaptive-weights policy
poetry run python -m alpha adaptive-weights compare
poetry run python -m alpha adaptive-weights promotion
poetry run python -m alpha adaptive-weights report
```

Filters cover partition, setup, regime, sector, horizon, dataset version,
baseline policy, and candidate policy. Reports support JSON and CSV export.

## Mandatory Controls

```text
PRODUCTION_INFLUENCE=false
AUTOMATIC_DEPLOYMENT=false
AUTOMATIC_WEIGHT_MUTATION=false
CANONICAL_WEIGHTS_IMMUTABLE=true
HOLDOUT_REQUIRED=true
FORWARD_VALIDATION_REQUIRED=true
OVERLAP_PENALTY_REQUIRED=true
POLICY_VERSIONING_REQUIRED=true
```
