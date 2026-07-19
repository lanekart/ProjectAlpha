# Setup Discovery & Evidence Engine (SDE v1.0)

## Purpose

SDE explains two frozen candidate-research gaps:

1. `SETUP_FAMILY_NOT_SUPPORTED`
2. `LOOKBACK_MISMATCH`

It does not optimize Alpha, add setups, change a lookback, or influence production.
Every recommendation is a research recommendation and
`PRODUCTION_INFLUENCE=false`.

## Evidence Flow

SDE reads the immutable candidate-research funnel, associated point-in-time
onsets, and forward-event labels. It then reads historical OHLCV through
`LegacyMarketDataStore`.

The feature engine computes only information visible at each onset:

- base duration and depth;
- volatility contraction;
- moving-average alignment;
- relative-strength trend when available;
- breakout angle and volume;
- ATR expansion;
- trend slope;
- consolidation geometry;
- liquidity profile.

Future return, holding period, prospective reward/risk, and 60-session return
are excluded from `SetupFeatureRecord.cluster_vector()`. They are attached only
after labels are frozen so the report can describe historical outcomes.

## Stable Clustering

`UnsupportedSetupClusterEngine` uses deterministic robust scaling,
farthest-first initialization, and deterministic k-means. It evaluates 8 to 15
families and selects the partition with the strongest centroid-separation score,
subject to a penalty for tiny clusters. The output retains cluster support,
representative symbols, representative charts, feature centroids, and separate
development, validation, and holdout outcomes.

The feature matrix is hashed independently of outcomes. Tests prove that
changing future outcomes does not change vectors or cluster assignments.

## Lookback Proof

The canonical structural lookback is 60 bars. SDE tests expanded views of 90,
120, 160, and 200 bars using only bars available on each tested date.

A `LOOKBACK_MISMATCH` claim is retained only when:

1. the canonical 60-bar view does not identify a coherent setup;
2. one expanded window does identify it;
3. the minimum visible window and first detectable date can be recorded; and
4. price remains within the frozen 10% entry-extension limit.

Otherwise the claim is classified as canonical-window sufficient, unsupported
by expanded evidence, too extended, or data insufficient. A rejected claim is
not counted as a proven lookback mismatch.

## Setup Vocabulary

Each family is classified as:

- existing canonical setup;
- canonical variant;
- new archetype;
- ambiguous;
- discard.

A non-positive aggregate or holdout outcome forces `DISCARD`. Broad family
coverage raises candidate-explosion risk. No family is production eligible.
Positive evidence can only recommend isolated Strategy Lab and walk-forward
research.

## Evidence Book

`top100_missed_opportunities.pdf` ranks missed cases retrospectively. Outcome
data may rank pages but cannot create setup families. Every chart ends at the
frozen onset date and displays close, 20-EMA, 50-EMA, and volume. Cluster
representatives not present in the top 100 appear in an appendix.

## Commands

```text
poetry run python -m alpha setup-discovery report
poetry run python -m alpha setup-discovery summary
poetry run python -m alpha setup-discovery deep-dive --symbol KALYANKJIL
poetry run python -m alpha setup-discovery deep-dive --symbol PCJEWELLER
```

Default output is `.alpha/setup_discovery/SDE_v1.0`.

## Required Artifacts

- `setup_clusters.csv`
- `lookback_evidence.csv`
- `top100_missed_opportunities.pdf`
- `setup_family_catalog.json`
- `setup_recommendations.md`
- `kalyan_deep_dive.md`
- `pcjeweller_deep_dive.md`

Additional feature, manifest, summary, and ranked-opportunity artifacts preserve
reproducibility and IRD provenance.

## Constraints

- SDE depends on a completed frozen candidate-research artifact.
- Missing relative-strength history remains missing and is median-imputed only
  inside clustering; it is never fabricated in exported evidence.
- Unsupported cases without a matched point-in-time series remain unclustered
  and are reported explicitly. Family coverage always uses the full unsupported
  population as its denominator.
- The legacy warehouse may contain provisional identity and corporate-action
  limitations inherited from its source manifest.
- Observed missed-case share is not a full-population false-positive estimate.
- Production introduction requires separate strategy-lab, walk-forward, shadow,
  and human approval workflows.
