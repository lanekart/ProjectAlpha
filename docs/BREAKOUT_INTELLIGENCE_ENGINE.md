# Breakout Intelligence Engine

Project Alpha's Breakout Intelligence Engine is a research-only diagnostic layer for
classifying breakout behavior, measuring what happens afterward, and auditing whether
breakout evidence adds value beyond existing confirmation intelligence.

`PRODUCTION_INFLUENCE=false`: the engine does not alter recommendation scoring,
allocation, trade planning, live feeds, shadow policies, or order behavior.

## Purpose

The engine answers five questions:

1. What kind of breakout was visible at the decision timestamp?
2. Did that breakout later hold, fail, retest, reach target, or stop out?
3. Are false breakouts and weak relative strength separate failure mechanisms or
   mostly the same failure wearing two labels?
4. Which breakout classes look useful enough for future policy research?
5. Which evidence inputs overlap with existing price, volume, confirmation, or
   trade-plan features?

## Event Semantics

Breakout classification is ex-ante. The class is assigned only from evidence that
would have been available at the timestamp:

- price versus a point-in-time resistance or breakout reference
- volume confirmation
- relative strength state
- participation proxy
- support/resistance context
- volatility and stop-distance quality
- retest or support-hold state
- regime and sector context where available
- trade-plan quality
- gap behavior
- data completeness

Retrospective outcomes are stored separately and never overwrite the ex-ante class.
A `HEALTHY_BREAKOUT` can later become `FAILED_WITHIN_3_SESSIONS`; it remains a
healthy-looking breakout at the original timestamp.

## Breakout Classes

The engine supports these deterministic ex-ante classes:

- `NO_BREAKOUT`
- `BREAKOUT_FORMING`
- `PREMATURE_BREAKOUT`
- `HEALTHY_BREAKOUT`
- `WEAK_BREAKOUT`
- `UNCONFIRMED_BREAKOUT`
- `GAP_BREAKOUT`
- `RANGE_BREAKOUT`
- `RETEST_BREAKOUT`
- `LATE_BREAKOUT`
- `EXTENDED_BREAKOUT`
- `EXHAUSTED_BREAKOUT`
- `FAILED_BREAKOUT`
- `AMBIGUOUS_BREAKOUT`
- `INSUFFICIENT_EVIDENCE`

`UNCONFIRMED_BREAKOUT` means the reference level was cleared but confirmation
inputs such as volume or relative strength are missing. `WEAK_BREAKOUT` means those
inputs are available and negative.

## Outcomes

Retrospective labels include:

- `HELD_BREAKOUT`
- `FAILED_WITHIN_1_SESSION`
- `FAILED_WITHIN_3_SESSIONS`
- `FAILED_WITHIN_5_SESSIONS`
- `RETEST_HELD`
- `RETEST_FAILED`
- `CONTINUED_TO_TARGET`
- `STOPPED_AFTER_VALID_BREAKOUT`
- `OUTCOME_AMBIGUOUS`
- `OUTCOME_UNAVAILABLE`

The engine reports target hits, stop hits, barrier ordering, terminal return, MFE,
MAE, realised R multiple, and holding flags where data exists.

## Evidence Lineage

Every evidence item includes:

- raw source fields
- transformations
- lookback window description
- historical availability
- point-in-time safety flag
- missingness
- upstream dependencies
- overlapping evidence groups
- downstream consumers

This is intentionally conservative. Missing data is surfaced as missing; it is not
filled with invented resistance, volume, RS, or capacity values.

## Independence and Overlap Audits

The false-breakout audit compares:

- false breakout only
- weak relative strength only
- both
- neither
- successful breakouts with weak RS
- failed breakouts with strong RS

The report then gives a cautious relationship conclusion such as
`INDEPENDENT_FAILURE_MECHANISMS`, `MOSTLY_OVERLAPPING_FAILURE_MECHANISMS`,
`WEAK_RS_PRECEDES_BREAKOUT_FAILURE`, or `INSUFFICIENT_EVIDENCE`.

This is a diagnostic approximation, not a causal proof.

## Policy Frontier

The class frontier evaluates simple research policies, including:

- healthy breakouts only
- healthy or retest breakouts
- high-confidence healthy breakouts
- healthy breakouts plus RS confirmation
- healthy breakouts plus participation confirmation
- rejecting premature or weak classes
- rejecting exhausted or extended classes
- combining class filters with cancellation awareness

For each policy Alpha reports precision, recall, coverage, effective sample size,
expectancy, delay, concentration, fold stability, and confidence interval.

## CLI Commands

Available commands:

```bash
poetry run python -m alpha replay breakout-intelligence
poetry run python -m alpha replay breakout-classification-audit
poetry run python -m alpha replay breakout-transition-audit
poetry run python -m alpha replay breakout-rs-independence
poetry run python -m alpha replay false-breakout-analysis
poetry run python -m alpha replay breakout-lineage-audit
poetry run python -m alpha replay breakout-stability-audit
poetry run python -m alpha replay breakout-class-frontier
poetry run python -m alpha replay breakout-opportunity-paths
```

Common filters:

```bash
--symbol SYMBOL
--opportunity-id OPPORTUNITY_ID
--breakout-class healthy-breakout
--policy healthy-only
--group-by breakout-class|transition|setup|regime|rs-state|year|horizon
--format text|json|csv
--output path
```

JSON and CSV exports require `--output`.

## Interpretation

The engine should be treated as decision-quality instrumentation:

- useful if class precision, expectancy, and stability are materially better than
  the frozen confirmation baseline
- explainability-only if it improves diagnostics but not precision
- redundant if lineage overlap is high and policy results do not improve
- not ready if effective sample size or data completeness is weak

No single class should be promoted into production gates without a separate
readiness review and sufficient out-of-sample evidence.

## Point-in-Time Reference Dataset

The original directional replay rows did not persist resistance levels or their
source bars. A price, score, target, or present-day resistance cannot safely stand in
for a historical breakout reference. Those rows therefore correctly produced
`INSUFFICIENT_EVIDENCE`.

`breakout_reference_dataset_v1` is the immutable sidecar that supplies the missing
point-in-time evidence. It is reconstruction, not prediction: it recreates only the
level that could have been calculated from completed bars at the historical decision
boundary. It never uses outcomes to form or select a level.

For legacy date-only replay rows, Alpha uses the previous completed persisted NSE
session. The candidate-day close is excluded. A proven after-close timestamp may use
that session's completed daily bar; pre-market and intraday decisions use the previous
session because daily OHLCV cannot represent a partial session. The observation bar
is never used to form its own resistance.

Supported methods remain separately identified:

- `PRIOR_SWING_HIGH`: latest pivot whose right-side confirmation bars were complete
  before the observation bar
- `RANGE_RESISTANCE`: range high with at least two tolerance-clustered touches
- `ROLLING_HIGH`: highest completed high in the configured prior window

The default method is `PRIOR_SWING_HIGH`. Alpha does not select a method using future
profitability.

The canonical price representation is raw, unadjusted OHLCV from Alpha's persisted
`daily_prices` store. Reference and comparison prices always use the same mode. A
known split inside the lookback trims the raw window to post-split bars; an unexplained
large discontinuity is `CORPORATE_ACTION_AMBIGUITY`. A post-candidate action is never
applied retrospectively.

Every record stores the cutoff, source timestamps, raw and normalized checksums,
security-master evidence, algorithm/configuration versions, warnings, exclusions,
and a semantic hash. Operational retrieval and reconstruction timestamps are omitted
from that semantic hash. `REFERENCE_NOT_FORMED` means sufficient valid history proved
that no qualifying level existed. An unavailable or ambiguous reconstruction remains
`INSUFFICIENT_EVIDENCE` in Breakout Intelligence.

Reference dataset commands:

```bash
poetry run python -m alpha replay breakout-reference-reconstruct --dry-run
poetry run python -m alpha replay breakout-reference-reconstruct
poetry run python -m alpha replay breakout-reference-readiness
poetry run python -m alpha replay breakout-reference-integrity
poetry run python -m alpha replay breakout-reference-provenance
poetry run python -m alpha replay breakout-reference-sample --limit 20
```

This milestone does not calculate breakout profitability, tune class thresholds, or
change recommendation, approval, allocation, entry, stop, or target policy.

## Source-Gap Attribution

The source-gap audit explains every unreconstructable reference record, compares the
ready and unavailable populations, and reports deterministic recovery scenarios. It
does not repair records or use outcomes to reconstruct evidence. See
`docs/BREAKOUT_SOURCE_GAP_AUDIT.md` for cause precedence, selection-bias safeguards,
recovery classes, CLI commands, and the validation gate.
