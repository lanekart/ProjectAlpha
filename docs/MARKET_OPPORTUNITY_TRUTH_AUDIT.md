# Market Opportunity Truth Audit (MOTA v1.0)

## Purpose

MOTA estimates the observed market's supply of point-in-time tradable onsets
before comparing that supply with Alpha. It is a research denominator, not an
optimization target and not a production policy.

`PRODUCTION_INFLUENCE=false`

## Frozen Evidence

MOTA is anchored to `ALPHA_BASELINE_v1.0` and persists the source commit,
warehouse version, candidate version, feature version, baseline manifest hash,
and all input checksums. It refuses evidence that does not match the frozen
baseline population.

The denominator is the 133,185-row pre-association population reconstructed by
the point-in-time feature-attribution audit. The 55,014 hindsight-linked onset
population is explicitly excluded because those rows had already survived a
future-event association.

## Causal Boundary

The pipeline has two phases:

1. Load point-in-time onset features, assess tradability, assign provisional
   quality, assign a natural opportunity family, and freeze a decision hash.
2. Attach 120-session outcome evidence and calculate lifecycle statistics.

Future returns, MFE, MAE, realized R, target hits, and stop hits cannot enter
onset detection, tradability, quality, or family assignment. Tests verify this
boundary by changing outcomes while holding the point-in-time classification
fixed.

## Opportunity Definition

Each onset must have an ordered positive entry, stop, and target; prospective
reward/risk of at least 1.5R; point-in-time average traded value of at least
INR 5 million; acceptable extension; and an evidence record explicitly marked
as free of future fields. Unknown or invalid evidence fails closed.

The resulting population is an empirical definition under a versioned policy.
It is not claimed to be a unique, model-free definition of every opportunity
that existed in the market.

## Provisional Quality Policy

Grades A+, A, B, and C use only prospective reward/risk, source confidence,
liquidity, trend alignment, volatility, geometry, and extension. `Not Tradable`
is retained as a typed state, although the frozen source is already the
pre-qualified tradable-onset population.

A+/A is not certified as institutional quality. In the current evidence, A+/A
has better grouped realized R than B/C, but the individual A+, A, B, and C
tiers are not monotonic. Reports therefore label A+/A as **provisional** and
require forward validation before treating the taxonomy as established.

## Lifecycle Semantics

MOTA evaluates up to 120 later market sessions and records:

- available forward bars and outcome maturity;
- first target-or-stop event under deterministic same-bar ordering;
- days to peak and days to failure;
- maximum favorable and adverse excursion;
- realized R supplied by the frozen outcome evidence.

Incomplete end-boundary histories remain partial. Missing values are never
fabricated.

## Natural Families

Opportunity families are deterministic descriptions of point-in-time market
geometry, volatility, liquidity, trend, base depth, and relative volume. They
are not Alpha setup labels and do not use outcomes during assignment. Outcome
statistics are joined only after each family assignment is frozen.

## Alpha Comparison

The comparison follows:

`Market Opportunity -> Detection Proxy -> Directional Candidate -> Approval -> Execution`

Matches are one-to-one by symbol and bounded to five market sessions or the
opportunity's first lifecycle event, whichever occurs first. This prevents one
Alpha record from claiming multiple market opportunities and prevents a late
decision from being credited after the opportunity has resolved.

The persisted technical ranking is only a detection proxy because complete
pre-candidate setup-detection history was not saved. Candidate recall uses
directional BUY/STRONG BUY records. Move and capital capture remain unavailable
when no execution exists.

## Environment Limitation

Authoritative historical market-regime evidence is unavailable. MOTA reports
regime attribution as unavailable and does not reconstruct or infer bull, bear,
or sideways labels. The legacy warehouse also remains provisional.

## Commands

```text
poetry run python -m alpha market-opportunity audit
poetry run python -m alpha market-opportunity calendar
poetry run python -m alpha market-opportunity density
poetry run python -m alpha market-opportunity compare
poetry run python -m alpha market-opportunity report
```

`audit` creates exactly nine deterministic artifacts in
`.alpha/market_opportunity/MOTA_v1.0`. The other commands read those frozen
artifacts and do not recompute the audit.

## Artifacts

- `market_opportunities.csv`
- `opportunity_calendar.csv`
- `opportunity_density.csv`
- `quality_distribution.csv`
- `opportunity_clusters.csv`
- `alpha_vs_market.csv`
- `capture_statistics.csv`
- `executive_report.md`
- `manifest.json`

The manifest records source and artifact hashes plus all isolation guardrails.

## Isolation Controls

MOTA does not modify recommendation features, gates, approvals, weights, setup
definitions, execution, allocation, or production behavior. Its immutable
manifest enforces:

```text
PRODUCTION_INFLUENCE=false
NO_FEATURE_CHANGES=true
NO_GATE_CHANGES=true
NO_APPROVAL_CHANGES=true
NO_WEIGHT_CHANGES=true
NO_SETUP_CHANGES=true
POINT_IN_TIME_ONLY=true
```
