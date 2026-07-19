# Institutional Approval Diagnostics

Alpha's institutional gates are intentionally strict. A zero-approval replay is
therefore a valid safety result: it means no candidate cleared every required
evidence, risk, data, and trade-plan criterion under the current policy.

It does not prove that no profitable stock existed in the market. It proves only
that Alpha refused to deploy capital because the recorded evidence was not strong
enough for institutional approval.

## Commands

```bash
poetry run python -m alpha replay approval-diagnostics
poetry run python -m alpha replay approval-diagnostics --nearest 20
poetry run python -m alpha replay approval-diagnostics --group-by criterion
poetry run python -m alpha replay approval-failures --near-approval-only
poetry run python -m alpha replay approval-outcomes
poetry run python -m alpha replay approval-outcomes --group-by criterion
poetry run python -m alpha replay profitable-rejections --minimum-return 5
poetry run python -m alpha replay entry-opportunities
poetry run python -m alpha replay entry-timing
poetry run python -m alpha replay entry-timing --group-by entry-state
poetry run python -m alpha replay entry-timing-failures --profitable-only
poetry run python -m alpha replay entry-timing-audit
poetry run python -m alpha replay entry-timing-audit --profitable-rejections
poetry run python -m alpha replay approval-baseline-audit
poetry run python -m alpha replay gate-attribution
poetry run python -m alpha replay gate-attribution --group-by gate
poetry run python -m alpha replay gate-opportunity-cost
poetry run python -m alpha replay gate-downside-protection
poetry run python -m alpha replay gate-overlap
poetry run python -m alpha replay gate-interactions
poetry run python -m alpha replay gate-ranking
poetry run python -m alpha replay gate-economic-impact
poetry run python -m alpha replay directional-signal-audit
poetry run python -m alpha replay directional-signal-audit --group-by setup
poetry run python -m alpha replay signal-ranking
poetry run python -m alpha replay signal-calibration
poetry run python -m alpha replay signal-components
poetry run python -m alpha replay signal-lineage
poetry run python -m alpha replay signal-outcome-quality
poetry run python -m alpha replay market-regime-audit
poetry run python -m alpha replay market-regime-audit --group-by regime
poetry run python -m alpha replay market-regime-audit --group-by setup
poetry run python -m alpha replay regime-lineage
poetry run python -m alpha replay regime-transitions
poetry run python -m alpha replay regime-reference-comparison
poetry run python -m alpha replay regime-intervention
poetry run python -m alpha replay regime-episodes
poetry run python -m alpha replay regime-retracement-interaction
poetry run python -m alpha replay market-state-persistence-audit
poetry run python -m alpha replay market-state-persistence-audit --group-by status
poetry run python -m alpha replay market-state-persistence-audit --group-by fallback
poetry run python -m alpha replay market-state-inventory
poetry run python -m alpha replay market-state-timestamps
poetry run python -m alpha replay market-state-reconstruction
poetry run python -m alpha replay market-state-comparison
poetry run python -m alpha replay market-state-fallbacks
poetry run python -m alpha replay market-state-episodes
poetry run python -m alpha replay market-state-selection-effect
poetry run python -m alpha replay market-state-classifier-replay
poetry run python -m alpha replay market-state-counterfactuals
poetry run python -m alpha replay sector-source-audit
poetry run python -m alpha replay sector-taxonomy-list
poetry run python -m alpha replay historical-sector-build
poetry run python -m alpha replay historical-sector-build --persist-diagnostic
poetry run python -m alpha replay historical-sector-build --resume
poetry run python -m alpha replay historical-sector-build-status
poetry run python -m alpha replay historical-sector-store-validate
poetry run python -m alpha replay historical-sector-coverage
poetry run python -m alpha replay historical-sector-conflicts
poetry run python -m alpha replay historical-sector-changes
poetry run python -m alpha replay historical-sector-show --symbol SYMBOL --date YYYY-MM-DD
poetry run python -m alpha replay historical-sector-state --date YYYY-MM-DD
poetry run python -m alpha replay diagnostic-market-state-v3-build
poetry run python -m alpha replay diagnostic-market-state-v2-v3-comparison
poetry run python -m alpha replay diagnostic-market-state-v3-readiness
poetry run python -m alpha replay historical-sector-source-audit
poetry run python -m alpha replay historical-sector-source-list
poetry run python -m alpha replay historical-sector-source-show --source SOURCE_ID
poetry run python -m alpha replay historical-sector-source-sample --source SOURCE_ID
poetry run python -m alpha replay historical-sector-source-identity-test --source SOURCE_ID
poetry run python -m alpha replay historical-sector-source-coverage
poetry run python -m alpha replay historical-sector-source-taxonomy
poetry run python -m alpha replay historical-sector-source-licensing
poetry run python -m alpha replay historical-sector-source-value
poetry run python -m alpha replay historical-sector-source-combinations
poetry run python -m alpha replay historical-sector-acquisition-decision
poetry run python -m alpha replay regime-input-dependency-audit
poetry run python -m alpha replay simplified-regime-models
poetry run python -m alpha replay simplified-regime-distribution
poetry run python -m alpha replay simplified-regime-outcomes
poetry run python -m alpha replay simplified-regime-outcomes --date-weighted
poetry run python -m alpha replay simplified-regime-quality
poetry run python -m alpha replay simplified-regime-threshold-stability
poetry run python -m alpha replay simplified-regime-incremental-value
poetry run python -m alpha replay simplified-regime-intervention
poetry run python -m alpha replay simplified-regime-setup-interaction
poetry run python -m alpha replay simplified-regime-retracement-interaction
poetry run python -m alpha replay simplified-regime-selection-effect
poetry run python -m alpha replay simplified-regime-interpretability
poetry run python -m alpha replay sector-maximum-impact
poetry run python -m alpha replay regime-parsimony-decision
poetry run python -m alpha replay regime-production-dependency
poetry run python -m alpha replay regime-score-influence
poetry run python -m alpha replay regime-verdict-influence
poetry run python -m alpha replay regime-ranking-influence
poetry run python -m alpha replay regime-selection-influence
poetry run python -m alpha replay regime-approval-influence
poetry run python -m alpha replay regime-allocation-influence
poetry run python -m alpha replay regime-setup-influence
poetry run python -m alpha replay regime-asymmetry
poetry run python -m alpha replay recorded-vs-v2-regime-influence
poetry run python -m alpha replay regime-context-only
poetry run python -m alpha replay regime-safe-deactivation-readiness
```

The diagnostic commands support `--format json` and `--format csv` with
`--output`.

## What the diagnostics show

- Each approval criterion is evaluated independently.
- Every failed candidate gets a primary rejection reason and secondary reasons.
- The approval margin shows how close the candidate came to approval.
- Near-approval candidates are sorted deterministically by margin, then symbol,
  then replay date.
- Missing trade-plan fields are reported as missing instead of guessed.
- Historical evidence gaps remain explicit; Alpha does not fabricate win rate,
  expectancy, or posterior probability.

## Reading zero approvals

When approvals are zero, approval precision is unavailable because precision is:

```text
correct approvals / all approvals
```

With no approvals, there is no denominator. This is not the same as bad
precision. It means Alpha emitted no deployable trades, so approval precision
cannot be measured for that replay slice.

Use rejection diagnostics to answer:

- Were candidates close to approval?
- Which gate failed most often?
- Did failures cluster around evidence, data completeness, trade plan quality, or
  risk?
- Which symbols or setup types are nearest to becoming deployable?

Use outcome-conditioned diagnostics to answer:

- Did rejected candidates later become profitable?
- Which gates rejected the most later-profitable candidates?
- Were failures narrow misses or material failures?
- Did winners and losers differ on pre-trade evidence?
- Was excessive stop distance mainly an entry-timing problem?
- Are posterior probabilities calibrated against observed replay outcomes?
- Are historical matches numerous but too heterogeneous to trust?

Use entry-timing diagnostics to answer:

- Was Alpha early, preferred, extended, late, or still setup-forming?
- Did preferred entries perform better than late entries?
- Did profitable rejections actually have acceptable timing but fail other gates?
- Was the stop-distance bottleneck caused by poor entry timing?
- Did timing score, stop distance, reward/risk, or distance from support separate
  winners from losers?

Use entry-timing validation and gate-attribution audits to answer:

- Are the observed entry states empirically separating winners from losers?
- Are profitable rejections mostly late/extended, or did they have acceptable
  timing and fail non-entry gates?
- Does entry timing add information beyond stop distance, reward/risk, and price
  extension?
- Are state boundaries stable near threshold cutoffs?
- Is the approval baseline mismatch caused by different approval definitions,
  different replay universes, different filters, or a true inconsistency?

Use non-entry gate attribution to answer:

- Which non-entry gates reject later-profitable candidates?
- Which non-entry gates reject losing candidates and provide downside
  protection?
- Which gate failures are unique versus shared with other failed gates?
- Which gates overlap heavily in decision outcomes or source features?
- Which gate combinations dominate acceptably timed rejected candidates?
- Whether the next bottleneck is directional signal quality, probability
  calibration, historical evidence quality, trade-plan quality, data
  completeness, or gate redundancy.

Use directional signal quality audits to answer:

- Whether BUY-like verdicts actually rank ahead of AVOID/SELL-like verdicts in
  completed replay outcomes.
- Whether higher recommendation scores, posterior probabilities, expectancy, or
  evidence scores separate later winners from later losers.
- Whether score buckets are calibrated against observed outcomes.
- Whether profitable rejected candidates were primarily missed because of poor
  directional ranking, probability calibration, evidence lineage, or component
  weakness.
- Whether results differ by setup family, final verdict, market regime, replay
  horizon, or benchmark-relative excess return.
- Whether evidence layers are independent or partly derived from the same
  historical replay features.

Use market-regime audits to answer:

- Which production regime labels and aliases exist today.
- Whether candidate regime attachments are exact, carried forward, missing,
  stale, or defaulted to neutral.
- Whether replay candidates were mostly labelled `NEUTRAL` because the sample
  was genuinely neutral, because neutral boundaries are too broad, because
  missing inputs collapsed into neutral, or because candidate generation selected
  mostly one regime.
- Whether transparent reference states disagree with production regimes.
- Whether regime intervention improved or degraded ranking, BUY precision, and
  top-decile win rate.
- Whether poor results are global, concentrated in momentum-continuation setups,
  concentrated in neutral markets, or linked to retracement behaviour.

Use market-state persistence audits to answer:

- Whether an authoritative historical market-state snapshot exists.
- Which market-state fields are persisted, transient, reconstructable, or
  unavailable.
- Whether candidate regime labels have source timestamps.
- Whether neutral labels came from genuine classification or missing inputs.
- Whether same-date reconstruction is possible without future data.
- Whether replayed classifier output agrees with attached candidate regimes.
- Whether candidate generation itself is concentrated in narrow market states.

Use historical sector classification diagnostics to answer:

- Which local files or stores contain sector classification evidence, and
  whether each source is authoritative, effective-dated, current-only, index
  membership only, weak inference, or unusable.
- Which sector taxonomy is being used, which hierarchy fields are available,
  and whether the taxonomy has an explicit effective period.
- Whether security-to-sector identity is matched by stable security id, ISIN,
  supported symbol lineage, ambiguous symbol, or unmatched evidence.
- Whether any sector classification changes or conflicts exist and how they are
  resolved.
- Whether current sector labels are being kept out of historical evidence when
  no effective dates exist.
- Whether diagnostic market-state v3 can be built from real sector history, or
  whether it must remain blocked because only current-only sector labels exist.
- Whether sector state materially improves regime validation before any
  production redesign is considered.

## Historical Sector Source Acquisition and Feasibility

Alpha must begin historical sector ingestion with a named, reviewed source. A
generic requirement for "sector history" is not sufficient.

Source authority is classified explicitly:

- `OFFICIAL_AUTHORITATIVE`
- `OFFICIAL_WITH_LIMITATIONS`
- `STRONG_COMMERCIAL`
- `STRONG_PUBLIC_ARCHIVE`
- `SUPPORTED_RECONSTRUCTION_SOURCE`
- `CURRENT_STATE_ONLY`
- `INDEX_MEMBERSHIP_ONLY`
- `WEAK`
- `UNUSABLE`

Temporal suitability is audited separately from source authority. A downloadable
archive is not automatically point-in-time sector evidence; its temporal
semantics must be understood. Only true effective-dated, archived snapshot-dated,
or change-event-dated sources can support historical reconstruction. Publication
date alone must not become a classification effective date.

Identity requirements are also separate. A viable source should join to Alpha's
security master through ISIN, an exchange instrument identifier, a provider
instrument key, or supported symbol lineage. Symbol-only and company-name-only
matches are diagnostic evidence at best and must preserve ambiguity, reused
symbol conflicts, and corporate-action conflicts.

Taxonomy requirements are strict. Classifications across years must not be
combined unless the taxonomy is stable/versioned or an explicit mapping exists.
Unversioned taxonomy, renamed sectors, merged sectors, split sectors, or
methodology changes are blocking limitations until mapped.

Licensing and operation are reported as feasibility facts, not legal conclusions:
free or paid, registration required, API availability, bulk download support,
manual archive requirements, redistribution/storage uncertainty, rate limits,
commercial-use restrictions, automation restrictions, and maintenance burden.

Safe source combinations require a primary classification source, a supporting
identity source, an effective-date source, and a taxonomy mapping plan. Index
membership and sector index history are not safe substitutes for security-level
sector classification.

Sector data should not be acquired merely to satisfy completeness if the
classifier is structurally insensitive to sector state. The source-value audit
therefore reports candidate dates potentially affected by sector, candidate
records potentially affected, maximum regime assignment changes, and maximum
score intervention changes before recommending acquisition.

Use:

```bash
poetry run python -m alpha replay historical-sector-source-audit
poetry run python -m alpha replay historical-sector-source-list
poetry run python -m alpha replay historical-sector-source-show --source SOURCE_ID
poetry run python -m alpha replay historical-sector-source-sample --source SOURCE_ID
poetry run python -m alpha replay historical-sector-source-identity-test --source SOURCE_ID
poetry run python -m alpha replay historical-sector-source-coverage
poetry run python -m alpha replay historical-sector-source-taxonomy
poetry run python -m alpha replay historical-sector-source-licensing
poetry run python -m alpha replay historical-sector-source-value
poetry run python -m alpha replay historical-sector-source-combinations
poetry run python -m alpha replay historical-sector-acquisition-decision
```

These commands support `--format json` and `--format csv` with `--output`.
They do not persist historical sector classifications and do not build
diagnostic v3.

## Benchmark-and-Breadth Regime Simplification Audit

Alpha can compare simpler, research-only regime definitions against the frozen
indexed diagnostic market-state store and candidate outcome ledger.

The audit compares:

- benchmark trend only;
- benchmark trend plus volatility;
- benchmark plus point-in-time breadth;
- transparent reference breadth state;
- current compatible classifier without sector;
- recorded/reconstructed diagnostic v2.

Benchmark-only models may report `INSUFFICIENT_INPUT` when benchmark return,
moving-average, or volatility fields exist in builder logic but are not
materialized in the indexed diagnostic v2 table. That is intentional: the audit
uses persisted point-in-time evidence only and does not reconstruct hidden
inputs.

The simplification reports show input dependency, model complexity,
distribution, candidate-weighted and date-weighted outcomes, quality-slice
stability, threshold perturbation stability, incremental value, intervention
effects, setup and retracement interactions, selection effects, sector maximum
impact, and a parsimony decision.

Use:

```bash
poetry run python -m alpha replay regime-input-dependency-audit
poetry run python -m alpha replay simplified-regime-models
poetry run python -m alpha replay simplified-regime-distribution
poetry run python -m alpha replay simplified-regime-outcomes
poetry run python -m alpha replay simplified-regime-outcomes --date-weighted
poetry run python -m alpha replay simplified-regime-quality
poetry run python -m alpha replay simplified-regime-threshold-stability
poetry run python -m alpha replay simplified-regime-incremental-value
poetry run python -m alpha replay simplified-regime-intervention
poetry run python -m alpha replay simplified-regime-setup-interaction
poetry run python -m alpha replay simplified-regime-retracement-interaction
poetry run python -m alpha replay simplified-regime-selection-effect
poetry run python -m alpha replay simplified-regime-interpretability
poetry run python -m alpha replay sector-maximum-impact
poetry run python -m alpha replay regime-parsimony-decision
```

These commands support `--format json` and `--format csv` with `--output`.

This layer is diagnostic-only. It must not implement a simplified production
classifier, tune thresholds, select historically optimal boundaries, alter
regime labels, change market-intelligence weights, modify recommendation
scores, alter verdicts, change candidate generation, change entry timing,
change trade plans, alter approvals, modify allocation, or treat absent sector
history as evidence.

## Market Regime Production Influence and Safe Deactivation

Alpha now audits where market regime influences production decisions before any
deactivation is considered. The audit maps direct and indirect consumers across
recommendation scoring, verdict thresholds, institutional decision quality,
setup scorecards, allocation eligibility, CLI rendering, snapshot persistence
and candidate generation.

The influence audit reports:

- dependency map and maximum theoretical impact;
- reconstructed production regime intervention;
- score influence across fixed counterfactual views;
- verdict transitions caused by removing recorded regime intervention;
- ranking influence, AUC, top-decile overlap and displacement;
- candidate selection, BUY classification, approval and allocation influence;
- setup-level concentration;
- bullish promotion and bearish demotion asymmetry;
- recorded-regime versus diagnostic V2-regime differences;
- context-only retained capabilities;
- safe-deactivation preconditions and decision matrix.

Use:

```bash
poetry run python -m alpha replay regime-production-dependency
poetry run python -m alpha replay regime-score-influence
poetry run python -m alpha replay regime-verdict-influence
poetry run python -m alpha replay regime-ranking-influence
poetry run python -m alpha replay regime-selection-influence
poetry run python -m alpha replay regime-approval-influence
poetry run python -m alpha replay regime-allocation-influence
poetry run python -m alpha replay regime-setup-influence
poetry run python -m alpha replay regime-asymmetry
poetry run python -m alpha replay recorded-vs-v2-regime-influence
poetry run python -m alpha replay regime-context-only
poetry run python -m alpha replay regime-safe-deactivation-readiness
```

These commands support `--format json` and `--format csv` with `--output`.

A diagnostic conclusion that market regime is weak does not by itself justify
removing it from production. Alpha must first measure every downstream decision
affected by regime intervention.

Context-only regime retains explanatory and analytical value while preventing
unvalidated regime classifications from changing capital decisions.

Safe deactivation requires a versioned feature flag, shadow comparison,
rollback path and regression evidence. This audit designs that future path but
does not activate it.

## Policy integrity

Approval diagnostics must not loosen production gates. They explain rejection
quality and near-misses, but they do not create fallback approvals.

Outcome-conditioned diagnostics may use future bars only after the replay
decision has already been recorded. They are for bottleneck analysis, not for
retroactively changing historical decisions.

Entry timing remains separate from directional verdict, institutional approval,
and capital allocation. A stock can be a good directional idea but a poor
immediate trade if it is late, extended, or has unattractive stop distance.

Entry timing validation is diagnostic-only. It must not alter production
thresholds, weights, timing rules, recommendation scores, approval decisions, or
portfolio allocation.

Non-entry gate attribution is also diagnostic-only. It must not lower
thresholds, remove gates, bypass gates, auto-approve candidates, change
recommendation weights, change allocation, or proceed directly to Dynamic Entry
Zone Optimization.

Directional signal quality audits are diagnostic-only. They do not change
production scores, verdicts, indicator weights, decision gates, timing states,
trade plans, approvals, allocation, thresholds, posterior probabilities, or
replay outcomes. They explain whether the previous conclusion
`DIRECTIONAL_SIGNAL_QUALITY_IS_PRIMARY_BOTTLENECK` is supported by replayed
evidence.

Market-regime audits are diagnostic-only. They do not relabel historical regime
records, change regime thresholds, flip component signs, change recommendation
scores, change indicator weights, change verdicts, change institutional gates,
change entry timing, change trade plans, change approvals, change allocation, or
change probability models. Diagnostic reference states and counterfactual
intervention views are research-only.

Market-state persistence audits are diagnostic-only. They do not create or
overwrite production market-state snapshots, retroactively relabel candidates,
change classifier thresholds, change recommendation scores, change gates,
change trade plans, change approvals, change allocations, change posterior
probabilities, or rewrite historical candidate records.

Historical sector classification ingestion is diagnostic-only. A current sector
label is not historical sector evidence unless the source provides or supports a
valid effective period for that classification. Index membership and sector
classification are different concepts; index membership must not be used as a
sector taxonomy substitute. Current-only sector mappings may be inventoried and
stored as diagnostic limitations, but they must not be applied backward as
authoritative history, used as strong sector evidence, used to change v1/v2
diagnostic outputs, or used to alter production recommendations, gates,
allocation, trade plans, classifier thresholds, regime labels, posterior
probabilities, or expectancy. Sector-state ingestion is justified only if it
materially improves regime validity or completeness under a point-in-time,
effective-dated dataset.

## Approval Baseline Reconciliation

Alpha tracks more than one approval concept:

- `replay approval-diagnostics` measures strict institutional deployment
  approval through the current gatekeeper logic.
- `replay entry-timing` reports the raw `approved_for_deployment` flag recorded
  on historical candidate records before the strict diagnostic layer is applied.

Therefore a replay can show zero strict institutional approvals and non-zero raw
recorded approvals at the same time. That is not automatically an approval
regression. The correct audit conclusion is
`DIFFERENT_APPROVAL_CONCEPTS` unless the same approval definition, universe, and
filters produce conflicting counts.

Use:

```bash
poetry run python -m alpha replay approval-baseline-audit
```

to print the compared source, replay universe, date range, approval stage,
definition, concept, approval count, rejection count, and conclusion.

## Entry Timing States

- `SETUP_FORMING`: structure exists, but no clean executable entry is available.
- `EARLY_ENTRY`: price is near a developing entry, but confirmation is incomplete.
- `AGGRESSIVE_ENTRY`: reward/risk is attractive near support, but execution is
  suitable only for aggressive profiles.
- `PREFERRED_ENTRY`: price is in the best structural entry area with acceptable
  stop distance and reward/risk.
- `CONFIRMATION_ENTRY`: breakout or reversal confirmation exists and the entry is
  still economically acceptable.
- `EXTENDED_ENTRY`: the directional idea may remain valid, but price has moved
  too far from support or the preferred zone.
- `LATE_ENTRY`: the setup is stale or stop/reward economics are materially poor.
- `INVALID_ENTRY`: support or structural invalidation has already failed.
- `ENTRY_UNAVAILABLE`: Alpha lacks enough same-date structure to classify timing.

Timing score is an execution-quality score, not a recommendation score. It uses
structural location, stop efficiency, reward/risk, extension, volume context,
relative strength, and setup freshness. Low-sample timing states are labelled
`INSUFFICIENT EVIDENCE` rather than promoted as superior.

## Non-Entry Gate Attribution

The primary universe is restricted to completed replay outcomes with acceptable,
executable entry timing:

```text
AGGRESSIVE_ENTRY
PREFERRED_ENTRY
CONFIRMATION_ENTRY
```

Secondary states are reported separately for context:

```text
SETUP_FORMING
EARLY_ENTRY
EXTENDED_ENTRY
LATE_ENTRY
INVALID_ENTRY
ENTRY_UNAVAILABLE
```

Late, invalid, unavailable, and setup-forming candidates are excluded from the
primary conclusion so poor execution timing does not distort non-entry gate
findings.

Gate attribution is not causality. If a gate failed on a later-profitable
candidate, the report says the gate is associated with that rejected winner; it
does not prove the gate caused the missed return. Likewise, avoided downside is
not realised portfolio profit.

Gross attribution counts every candidate failed by a gate. Because multiple
gates can fail the same candidate, gross missed-upside and avoided-downside
totals can overlap across gates. Unique attribution counts only candidates where
that gate was the sole non-entry failed gate.

High overlap does not automatically justify gate removal. Gates may be designed
as defence-in-depth controls, and feature overlap must be interpreted alongside
unique failures, downside protection, false-negative burden, data availability,
and replay sample size.

Missing-data gates are treated explicitly. If an authoritative gate result says
data was unavailable, the attribution report preserves that as missing input
rather than guessing a pass or failure.

No-look-ahead integrity is preserved: future bars are used only to classify
post-decision replay outcomes. Future outcomes do not affect gate evaluation,
timing state, recommendation, probability, trade plan, approval, or allocation.

## Directional Signal Quality Audit

The directional signal audit starts after entry timing and non-entry gate
attribution. Its primary universe is completed replay outcomes, with separate
views for:

- all completed candidates;
- candidates with acceptable entry timing;
- candidates whose forward return was positive.

The audit classifies outcome quality into explicit labels:

```text
CLEAN_WIN
VOLATILE_WIN
LATE_WIN
INVALIDATED_THEN_WIN
CLEAN_LOSS
STOPPED_THEN_RECOVERED
FLAT
OUTCOME_UNAVAILABLE
```

This separates clean directional correctness from noisy outcomes where the idea
eventually worked only after invalidation, large adverse movement, or weak
timing. A later-profitable rejection is not automatically evidence that a gate
was wrong; the audit checks whether the original directional score and evidence
ranked that candidate properly.

The report includes:

- verdict-level directional accuracy, including BUY precision and profitable
  AVOID/SELL counts;
- score-ranking diagnostics such as top-decile hit rate, bottom-decile hit
  rate, ROC-AUC, and Spearman-like correlation for recommendation score,
  evidence score, posterior probability, expectancy, setup score, and component
  scores;
- calibration buckets comparing predicted posterior probability with observed
  win rate;
- component attribution for trend, volume, relative strength, volatility,
  candle, retracement, breakout, and price/volume evidence where those fields
  exist;
- lineage records explaining which outputs reuse the same recorded source
  features;
- overlap findings showing when outputs such as expectancy and posterior
  probability should not be treated as independent confirmation;
- setup, verdict, regime, horizon, and benchmark-relative summaries;
- counterfactual ranking views that ask whether simple ranking by a score would
  have recovered more winners than the recorded verdict path.

The audit may conclude:

```text
DIRECTIONAL_SIGNAL_QUALITY_IS_PRIMARY_BOTTLENECK
PROBABILITY_CALIBRATION_IS_PRIMARY_BOTTLENECK
HISTORICAL_EVIDENCE_QUALITY_IS_PRIMARY_BOTTLENECK
TRADE_PLAN_OR_EXECUTION_QUALITY_IS_PRIMARY_BOTTLENECK
NO_SINGLE_DIRECTIONAL_BOTTLENECK
INSUFFICIENT_EVIDENCE_FOR_DIRECTIONAL_CONCLUSION
```

If evidence is insufficient, Alpha prints the actual sample count and avoids
fabricating precision, win rate, expectancy, or probability. If directional
signal quality is the bottleneck, the next safe milestone is a diagnostic signal
definition audit, not immediate production threshold changes.

## Market Regime Classifier and Intervention Audit

The market-regime audit traces the regime path from production enum inventory to
candidate attachment and post-decision outcome analysis:

```text
market and breadth inputs
-> regime feature construction
-> regime classification
-> candidate regime attachment
-> regime adjustment to score
-> final verdict or approval effect
-> post-decision outcome
```

If the ledger does not persist a full market-regime state table, source input
timestamps, previous regime, or pre-regime production score, the audit reports
those fields as unavailable or reconstructed. It does not guess hidden state.

The audit includes:

- production regime inventory from market-intelligence enums and recorded
  candidate regimes;
- lineage records for input construction, classification, attachment, and
  recommendation intervention;
- candidate timestamp and join integrity checks;
- regime distributions across all candidates, completed outcomes, acceptably
  timed candidates, BUY candidates, winners, and losers;
- transition counts and transition matrix;
- transparent reference-state comparison using only recorded same-date features
  such as benchmark return, trend score, and volatility fields when available;
- episode detection from available benchmark-return snapshots;
- regime-feature separability;
- reconstructed pre-regime versus post-regime ranking metrics;
- setup-regime and retracement-regime interactions;
- research-only counterfactual views such as no regime adjustment, price-only
  ranking, regime-as-veto, and neutral-as-zero-adjustment.

The audit may conclude:

```text
REGIME_CLASSIFIER_HAS_USEFUL_SEPARATION
REGIME_CLASSIFIER_COLLAPSES_TO_NEUTRAL
DEFAULT_NEUTRAL_FALLBACK_IS_PRIMARY_BOTTLENECK
REGIME_TIMESTAMP_ALIGNMENT_IS_PRIMARY_BOTTLENECK
REGIME_FEATURE_QUALITY_IS_PRIMARY_BOTTLENECK
REGIME_THRESHOLD_DEFINITION_IS_PRIMARY_BOTTLENECK
REGIME_INTERVENTION_DEGRADES_SIGNAL_QUALITY
MOMENTUM_NEUTRAL_INTERACTION_IS_PRIMARY_BOTTLENECK
CANDIDATE_SAMPLE_LACKS_REGIME_DIVERSITY
MARKET_REGIME_IS_NOT_THE_PRIMARY_BOTTLENECK
INSUFFICIENT_EVIDENCE_FOR_REGIME_CONCLUSION
```

The conclusion is intentionally allowed to narrow or overturn the previous
directional-audit hypothesis. A correct classifier with negative regime
intervention value-add is reported as an intervention problem, not automatically
as a classification problem.

## Market State Persistence & Reconstruction Audit

This audit exists because a regime classifier can only be judged after Alpha
knows whether the classifier received and persisted valid point-in-time inputs.
It traces:

```text
source market data
-> benchmark observations
-> breadth observations
-> volatility observations
-> sector observations
-> feature construction
-> classifier input
-> classifier output
-> persisted market-state snapshot
-> candidate attachment
-> recommendation intervention
-> replay audit reconstruction
```

Authoritative state means a persisted market-level snapshot with its own source
timestamp. Reconstructed state means a diagnostic approximation rebuilt from
same-date candidate fields such as benchmark return, price/trend score, breadth
score, volatility score, and participation score where those fields are already
recorded.

A reconstructed market state is a diagnostic approximation, not an automatic
replacement for the production record.

Timestamp semantics are explicit:

- `EXACT`: source timestamp matches the candidate decision date.
- `CARRIED_FORWARD_VALID`: source timestamp predates the decision but remains
  inside the configured staleness tolerance.
- `CARRIED_FORWARD_STALE`: source timestamp is older than the tolerance.
- `FUTURE_TIMESTAMP`: source timestamp is after the decision date and is a
  no-look-ahead integrity failure.
- `DEFAULTED_WITHOUT_SOURCE`: the candidate has a neutral regime but no
  persisted market-state source timestamp.
- `RECONSTRUCTED_SAME_DATE`: the audit used same-date candidate fields because
  no authoritative source timestamp exists.

Fallback classifications explain why neutral labels appear. Examples include
missing benchmark input, missing breadth input, insufficient lookback, missing
market-state record, candidate attachment missing, and genuine neutral
classification. The audit does not infer classifier exceptions unless explicit
evidence exists.

Market episodes are built only from available same-date diagnostic state. If
benchmark history is absent, episode coverage is reported as limited rather than
filled with invented data.

Classifier replay is diagnostic. It compares the original candidate-attached
regime, a replayed production-like state from available inputs, and a transparent
reference state. Agreement labels include exact match, directional match,
neutral collapse, sign conflict, original defaulted, and replay unavailable.

The audit may conclude:

```text
MARKET_STATE_HISTORY_NOT_PERSISTED
MARKET_STATE_HISTORY_PARTIALLY_PERSISTED
DEFAULT_NEUTRAL_FALLBACK_IS_PRIMARY_BOTTLENECK
MARKET_STATE_TIMESTAMP_ALIGNMENT_IS_PRIMARY_BOTTLENECK
CANDIDATE_REGIME_ATTACHMENT_IS_PRIMARY_BOTTLENECK
REPLAY_RECONSTRUCTION_IS_PRIMARY_BOTTLENECK
MARKET_STATE_INPUT_COMPLETENESS_IS_PRIMARY_BOTTLENECK
CANDIDATE_SELECTION_EFFECT_IS_PRIMARY_BOTTLENECK
PRODUCTION_CLASSIFIER_DISAGREES_WITH_RECONSTRUCTION
PRODUCTION_CLASSIFIER_APPEARS_CONSISTENT
MARKET_STATE_PERSISTENCE_IS_SUFFICIENT
INSUFFICIENT_EVIDENCE_FOR_MARKET_STATE_CONCLUSION
```

Threshold or intervention audits should only follow once persistence,
timestamp-linkage, reconstruction, and attachment quality are adequate.

## Live Benchmark Market-State Capture

Alpha uses one explicit broad-market benchmark configuration for market-state
capture:

- Logical benchmark: `NIFTY 50 broad-market ETF proxy`
- Provider symbol: `NIFTYBEES`
- Instrument identifier: `NSE_EQ|NIFTYBEES`
- Exchange: `NSE`
- Asset type: `ETF`
- Currency: `INR`
- Session calendar: `NSE`
- Historical source: local `daily_prices` populated from NSE bhavcopy ingestion

This benchmark is an explicit configured proxy, not an implicit substitution of
a stock, sector index, or current-day value. If the configured provider symbol is
missing, benchmark fields remain unavailable; Alpha does not convert missing
benchmark values to zero.

Point-in-time benchmark features are built by `BenchmarkStateBuilder` from bars
whose `trade_date` is at or before the decision timestamp. The builder supplies
features to snapshot persistence only. It does not classify regimes, tune
thresholds, change recommendation scores, or alter allocation.

Feature formulas are deterministic:

```text
return_1d = close_t / close_t-1 - 1
return_5d = close_t / close_t-5 - 1
return_20d = close_t / close_t-20 - 1
DMA_n = arithmetic mean of the latest n closes, only when n bars exist
distance_DMA_n = close_t / DMA_n - 1
ATR(14) = arithmetic mean of the latest 14 true ranges
volatility = population standard deviation of latest 20 daily close-to-close returns
```

Returns, DMA distances, and volatility are decimal units, not percent strings.
For example `0.0100` means `1.00%`.

Timestamp alignment is recorded as:

```text
SAME_TRADING_DAY
PREVIOUS_COMPLETED_SESSION
CARRIED_FORWARD_VALID
CARRIED_FORWARD_STALE
FUTURE_BAR_REJECTED
BENCHMARK_BAR_UNAVAILABLE
```

Daily benchmark bars are treated as completed-session evidence only when their
date is at or before the decision timestamp. Alpha does not invent intraday
benchmark state from daily bars.

Snapshot completeness now separates benchmark availability from classifier
output:

- `COMPLETE`: required benchmark, breadth, sector, volatility, and participation
  inputs are present and timestamp-valid.
- `PARTIAL`: the classifier can run, but diagnostic or non-essential inputs are
  still unavailable.
- `MINIMUM_VIABLE`: only the minimum safe input set exists.
- `INSUFFICIENT`: required benchmark or market inputs are missing.
- `UNAVAILABLE`: no valid market state could be constructed.

Fallback-neutral and genuine-neutral are distinct. A genuine neutral snapshot has
`classifier_regime=NEUTRAL`, `fallback_applied=False`, and
`fallback_reason=NONE`. A fallback-neutral snapshot records the precise primary
reason, such as `BENCHMARK_HISTORY_UNAVAILABLE`,
`BENCHMARK_LOOKBACK_INSUFFICIENT`, `BENCHMARK_LATEST_BAR_STALE`,
`BENCHMARK_TIMESTAMP_INVALID`, or missing breadth/sector inputs.

Useful audit commands:

```bash
poetry run python -m alpha market-state benchmark
poetry run python -m alpha market-state benchmark-history
poetry run python -m alpha market-state benchmark-coverage
poetry run python -m alpha market-state completeness
poetry run python -m alpha replay benchmark-state-audit
poetry run python -m alpha replay market-state-backfill-plan
```

A persisted snapshot is authoritative evidence of what production used, but a
partial snapshot does not prove that the classifier received sufficient market
information.

Historical backfill must reuse the same benchmark identity, timestamp semantics,
and feature definitions as live snapshot construction.

## Historical Market-State Backfill Readiness

Alpha includes a no-write readiness audit before any historical market-state
snapshot backfill is allowed. The audit answers whether historical candidate
dates have enough trustworthy point-in-time inputs to reconstruct market state.
It does not create snapshots, attach snapshot IDs to candidates, relabel
outcomes, tune classifier thresholds, change recommendations, or alter
allocation.

Readiness commands:

```bash
poetry run python -m alpha replay market-state-backfill-readiness
poetry run python -m alpha replay market-state-backfill-readiness --group-by date
poetry run python -m alpha replay market-state-backfill-readiness --group-by year
poetry run python -m alpha replay market-state-source-inventory
poetry run python -m alpha replay benchmark-date-reconciliation
poetry run python -m alpha replay benchmark-lookback-gaps
poetry run python -m alpha replay benchmark-source-integrity
poetry run python -m alpha replay benchmark-proxy-suitability
poetry run python -m alpha replay historical-breadth-readiness
poetry run python -m alpha replay historical-sector-readiness
poetry run python -m alpha replay classifier-version-readiness
poetry run python -m alpha replay market-state-backfill-simulate
```

The default readiness output reports:

- primary conclusion
- secondary conclusions
- recommended next milestone
- explicitly prohibited next action
- benchmark, breadth, sector, and classifier-version readiness

`NIFTYBEES` remains an explicit ETF proxy for broad-market diagnostics. The
readiness audit may find it suitable for diagnostic reconstruction with
limitations, but authoritative backfill should prefer official NIFTY 50 index
history where available.

The dry-run simulation emits candidate-date rows that say whether a partial
diagnostic reconstruction would be possible. Those rows are not authoritative
snapshots and must not be linked back to historical candidates until a separate
write-enabled backfill milestone is reviewed and approved.

## Classifier Version Lineage and Decision Provenance

Alpha now records a normalized decision-provenance record for new runtime
decisions. One runtime evaluation reuses one provenance record, and generated
market-state snapshots and candidate decisions reference that provenance ID.
Legacy records remain readable with missing provenance explicitly represented as
unknown.

Decision provenance captures:

- application and build version
- Git commit, branch, and working-tree state where available
- market-state snapshot schema version
- benchmark builder version
- market feature definition version
- market classifier version and semantic fingerprint
- fallback-policy version
- market-intelligence, recommendation, entry-timing, trade-plan, approval, and
  allocation policy versions
- runtime command, runtime mode, source, and creation timestamp

Component analytical versions are centralized in the provenance registry. A
component version should change when decision-relevant behaviour changes. Pure
refactoring may keep the same analytical version if thresholds, labels, feature
definitions, fallback semantics, score configuration, and output interpretation
remain unchanged.

Fingerprints are deterministic semantic hashes of component names, analytical
versions, config versions, and decision-relevant configuration. They deliberately
avoid runtime-dependent representations such as memory addresses. Source-code
hashes may be useful supporting evidence, but they are not a substitute for
semantic component versions.

Compatibility classifications:

- `EXACT_VERSION_MATCH`: persisted component version equals the replay component
  version.
- `EXACT_FINGERPRINT_MATCH`: persisted fingerprint equals the current replay
  fingerprint.
- `SEMANTICALLY_COMPATIBLE`: supported evidence shows decision-relevant
  behaviour is equivalent.
- `FORWARD_COMPATIBLE_FOR_REPLAY`: current logic can process the old output
  contract, but exact original behaviour is not proven.
- `INCOMPATIBLE`: known changes affected classification, thresholds, feature
  definitions, fallback semantics, or output interpretation.
- `VERSION_UNKNOWN`, `FINGERPRINT_UNKNOWN`, and `INSUFFICIENT_EVIDENCE`: exact
  replay must not be claimed.

A replay result is not an exact historical reproduction merely because the
current classifier can process the historical inputs.

Missing classifier-version lineage must remain unknown unless authoritative or
strongly supported compatibility evidence exists.

Component compatibility does not permit historical records to be rewritten.

## Historical Analytical Release Manifest

Alpha now includes a reviewed analytical release-manifest audit for historical
lineage recovery. The manifest is intentionally conservative: it inventories
available evidence, identifies analytical eras, validates manifest entries, and
assigns candidate rows to the strongest supported historical status without
mutating legacy records.

Evidence reliability hierarchy:

- `AUTHORITATIVE`: persisted record-level provenance, fingerprints, or runtime
  ledger evidence.
- `STRONG`: explicit code or release evidence tied to decision-relevant
  configuration, but not necessarily to a specific record.
- `SUPPORTING`: documentation or package metadata that helps explain lineage but
  is not record-level proof.
- `WEAK`: date proximity, schema resemblance, or output-signature similarity.
- `UNUSABLE`: absent, contradictory, or non-actionable evidence.

Manifest review statuses:

- `VERIFIED`: strong or authoritative evidence supports the entry.
- `SUPPORTED`: enough evidence exists for semantic compatibility, but exact
  historical reproduction may still be constrained.
- `PROVISIONAL`: diagnostic-only; never exact.
- `REJECTED` and `UNKNOWN`: not eligible for historical backfill.

A Git commit proves that code existed, not necessarily that it produced a
specific historical decision.

Date-range and output-signature compatibility may support diagnostic replay but
do not establish exact historical provenance.

Unknown legacy provenance is an acceptable and more trustworthy result than a
falsely precise historical version assignment.

Candidate-era assignment statuses include persisted exact provenance, persisted
exact classifier version, verified or supported manifest match, multiple possible
eras, output-signature only, date-range only, conflicting evidence, incompatible
era, and unknown era. Assignments are audit outputs only; they are not written
back into candidate rows.

Backfill eligibility from the manifest remains separate from execution. Exact
or verified rows can be marked eligible for a future reviewed backfill, while
output-signature-only rows remain blocked or diagnostic-only. The release
manifest audit explicitly prohibits historical backfill, automatic era
assignment, threshold tuning, recommendation changes, approval changes, and
allocation changes.

Useful provenance commands:

```bash
poetry run python -m alpha provenance current
poetry run python -m alpha provenance show --provenance-id <id>
poetry run python -m alpha provenance history
poetry run python -m alpha provenance components
poetry run python -m alpha provenance coverage
poetry run python -m alpha provenance manifest
poetry run python -m alpha provenance manifest show --era-id <id>
poetry run python -m alpha provenance manifest validate
poetry run python -m alpha provenance eras
poetry run python -m alpha provenance evidence
poetry run python -m alpha replay classifier-version-lineage
poetry run python -m alpha replay classifier-version-lineage --group-by status
poetry run python -m alpha replay classifier-version-evidence
poetry run python -m alpha replay classifier-version-compatibility
poetry run python -m alpha replay analytical-version-drift
poetry run python -m alpha replay historical-backfill-version-eligibility
poetry run python -m alpha replay historical-release-evidence
poetry run python -m alpha replay historical-analytical-eras
poetry run python -m alpha replay historical-manifest-coverage
poetry run python -m alpha replay historical-era-assignment
poetry run python -m alpha replay historical-era-assignment --group-by status
poetry run python -m alpha replay historical-backfill-manifest-eligibility
```

Historical backfill eligibility remains conservative. Authoritative backfill
requires point-in-time-safe market inputs, compatible feature definitions, known
classifier and fallback lineage, matching timestamp semantics, and deterministic
transformation lineage. Records with only forward-compatible evidence remain
diagnostic unless a separate reviewed policy explicitly allows otherwise.

## Diagnostic Historical Market-State Reconstruction Dataset

Alpha now supports a separate diagnostic market-state reconstruction dataset.
This dataset is stored outside the authoritative market-state snapshot ledger and
is never attached to legacy candidate rows as production lineage.

Diagnostic reconstructed market states describe what Alpha's compatible current
research logic infers from point-in-time historical data. They do not prove what
the original production system classified.

Diagnostic reconstruction records must never be written into the authoritative
market-state snapshot table or attached to legacy candidate records as
production lineage.

Post-decision outcomes may evaluate a frozen reconstruction but may never
influence its inputs, classification, completeness, or quality.

Dataset identity:

- dataset version: `diagnostic-market-state-reconstruction-v1`
- reconstruction IDs include market date, decision cutoff, benchmark identity,
  feature-definition version, classifier version/fingerprint, compatibility
  status, dataset version, and source-lineage fingerprint.
- multiple diagnostic dataset versions may coexist.

Candidate linkage is diagnostic-only. The mapping records reconstruction ID,
candidate stable ID, timestamp difference, recorded regime, setup, verdict,
entry state, and outcome availability. It does not update
`CandidateDecisionRecord.market_state_snapshot_id`.

Benchmark reconstruction reuses `BenchmarkStateBuilder` and the canonical
`NIFTYBEES` configuration. Bars after the decision cutoff are excluded. Early
history remains partial or unavailable when 20/50/200-DMA, ATR, or volatility
inputs are not yet reconstructable.

Breadth is currently labelled
`DIAGNOSTIC_CURRENT_UNIVERSE_RECONSTRUCTION`. It uses same-date local price bars
and explicitly discloses survivorship/current-universe bias. Point-in-time
universe membership is not proven. DMA breadth is left unavailable until a
separate point-in-time breadth-history milestone exists.

Sector state remains `SECTOR_STATE_UNAVAILABLE` unless point-in-time sector
history is provided. Current sector mappings must not be treated as historical
truth.

Classifier replay for deployment-unproven records is labelled
`CURRENT_COMPATIBLE_CLASSIFIER_REPLAY`; replay regime is stored separately from
the recorded candidate regime. The transparent reference state is a simple,
deterministic diagnostic grouping based on same-date benchmark trend,
volatility, and breadth. It is not truth and it is not production policy.

Useful diagnostic reconstruction commands:

```bash
poetry run python -m alpha replay diagnostic-market-state-build --dry-run
poetry run python -m alpha replay diagnostic-market-state-build --persist-diagnostic
poetry run python -m alpha replay diagnostic-market-state-coverage
poetry run python -m alpha replay diagnostic-market-state-history
poetry run python -m alpha replay diagnostic-market-state-show --reconstruction-id <id>
poetry run python -m alpha replay diagnostic-market-state-lineage --reconstruction-id <id>
poetry run python -m alpha replay diagnostic-market-state-quality
poetry run python -m alpha replay diagnostic-market-state-no-look-ahead
poetry run python -m alpha replay reconstructed-regime-comparison
poetry run python -m alpha replay reconstructed-neutral-collapse
poetry run python -m alpha replay reconstructed-regime-outcomes
poetry run python -m alpha replay reconstructed-regime-outcomes --group-by regime
poetry run python -m alpha replay reconstructed-regime-outcomes --group-by quality
poetry run python -m alpha replay reconstructed-regime-outcomes --date-weighted
poetry run python -m alpha replay reconstructed-regime-intervention
poetry run python -m alpha replay reconstructed-regime-threshold-density
poetry run python -m alpha replay reconstructed-regime-threshold-stability
poetry run python -m alpha replay reconstructed-regime-coherence
poetry run python -m alpha replay reconstructed-regime-episodes
poetry run python -m alpha replay reconstructed-setup-regime
poetry run python -m alpha replay reconstructed-retracement-regime
poetry run python -m alpha replay reconstructed-selection-effect
poetry run python -m alpha replay reconstructed-breadth-sensitivity
poetry run python -m alpha replay reconstructed-sector-sensitivity
poetry run python -m alpha replay regime-threshold-readiness
```

The build command is dry-run by default. It writes only when
`--persist-diagnostic` is supplied, and even then it writes only to the separate
diagnostic reconstruction dataset.

Operational note: Alpha database CLI commands must be run serially. Concurrent
DuckDB-backed commands can contend for the database lock. Alpha now reports this
as concurrent database access and advises serial execution rather than trying
unsafe automatic retries or lock deletion.

## Point-in-Time Market Universe, Sector Membership, and Breadth History

Alpha now has a separate diagnostic layer for point-in-time market universe
membership, security identity, listing/delisting evidence, sector membership,
and breadth reconstruction. This layer is versioned separately from production
market-state snapshots and from the earlier diagnostic v1 reconstruction
dataset.

A security that exists in today’s database must not be included in historical
breadth before its historical listing date.

Current sector classification is not historical sector classification unless the
source provides effective dates.

Point-in-time market breadth and sector state improve diagnostic validity but do
not by themselves justify production threshold changes.

The current implementation deliberately labels local price-derived membership
as weak inferred evidence unless an official security master provides listing,
delisting, ISIN, symbol-change, and corporate-action lineage. The `daily_prices`
sector column is treated as `CURRENT_MAPPING_DIAGNOSTIC`; it is useful for
diagnostic coverage checks, but it is not accepted as point-in-time sector
truth.

Useful point-in-time diagnostic commands:

```bash
poetry run python -m alpha replay security-master-source-audit
poetry run python -m alpha replay security-identity-audit
poetry run python -m alpha replay listing-delisting-audit
poetry run python -m alpha replay point-in-time-universe-build
poetry run python -m alpha replay point-in-time-universe-build --persist-diagnostic
poetry run python -m alpha replay point-in-time-universe-build --resume --persist-diagnostic
poetry run python -m alpha replay point-in-time-build-status
poetry run python -m alpha replay point-in-time-build-history
poetry run python -m alpha replay point-in-time-build-profile
poetry run python -m alpha replay point-in-time-dataset-validate
poetry run python -m alpha replay point-in-time-store-import --build-id BUILD_ID
poetry run python -m alpha replay point-in-time-store-status
poetry run python -m alpha replay point-in-time-store-validate
poetry run python -m alpha replay point-in-time-store-profile
poetry run python -m alpha replay point-in-time-store-equivalence --build-id BUILD_ID
poetry run python -m alpha replay point-in-time-read-profile --date YYYY-MM-DD
poetry run python -m alpha replay point-in-time-universe-coverage
poetry run python -m alpha replay point-in-time-universe-show --date YYYY-MM-DD
poetry run python -m alpha replay point-in-time-sector-build
poetry run python -m alpha replay point-in-time-sector-coverage
poetry run python -m alpha replay sector-classification-conflicts
poetry run python -m alpha replay point-in-time-breadth
poetry run python -m alpha replay point-in-time-sector-state --date YYYY-MM-DD
poetry run python -m alpha replay survivorship-bias-audit
poetry run python -m alpha replay diagnostic-market-state-v2-build
poetry run python -m alpha replay diagnostic-market-state-v2-integrity
poetry run python -m alpha replay diagnostic-market-state-v1-v2-comparison
poetry run python -m alpha replay diagnostic-market-state-v2-outcomes
poetry run python -m alpha replay diagnostic-market-state-v2-outcomes --date-weighted
poetry run python -m alpha replay diagnostic-market-state-v2-quality
poetry run python -m alpha replay diagnostic-market-state-v2-intervention
poetry run python -m alpha replay diagnostic-market-state-v2-threshold-stability
poetry run python -m alpha replay diagnostic-market-state-v2-coherence
poetry run python -m alpha replay diagnostic-market-state-v2-setup-regime
poetry run python -m alpha replay diagnostic-market-state-v2-retracement-regime
poetry run python -m alpha replay diagnostic-market-state-v2-selection-effect
poetry run python -m alpha replay diagnostic-market-state-v2-breadth-value
poetry run python -m alpha replay diagnostic-market-state-v2-sector-materiality
poetry run python -m alpha replay diagnostic-market-state-v2-readiness
poetry run python -m alpha replay sector-incremental-value
poetry run python -m alpha replay point-in-time-history-readiness
```

The point-in-time universe build command is dry-run by default. It writes only
when `--persist-diagnostic` is supplied. Diagnostic market-state v2 also remains
dry-run by default and blocks persistence until point-in-time universe and sector
integrity are strong enough for reviewed analytical release.

Point-in-time build commands and point-in-time report commands are deliberately
separated. Build commands create or resume the diagnostic materialization.
Report commands read a completed compatible materialization. Reporting commands
must not silently trigger a full historical rebuild.

A point-in-time dataset is not considered complete merely because some rows have
been persisted. Its build manifest and validation report must both indicate
completion.

The materialization lifecycle records a build manifest with source fingerprint,
configuration fingerprint, requested date range, batch size, completed dates,
failed dates, current checkpoint, row counts, builder versions, and validation
status. Checkpoints are append-safe and record the completed batch date range,
batch fingerprint, rows written, breadth snapshots written, sector-state rows
written, and validation status. Resume continues only when source and
configuration fingerprints are compatible.

The analytical store is an indexed diagnostic read model over the validated JSON
materialization. The JSON materialization remains the source artifact until
store equivalence is validated. Normal reporting commands should use the store
when it exists, but they must not overwrite, delete, or mutate the source JSON
artifact.

Point-in-time universe rows represent market membership evidence, not candidate
decisions. Diagnostic v2 candidate links must be grounded in candidate ledger
records only. Treating universe membership rows as candidate links is an
integrity failure because it inflates diagnostic coverage and contaminates
candidate-outcome analysis.

Diagnostic v2 validation freezes the audited dataset identity before joining
outcomes: dataset version, dataset fingerprint, point-in-time store build id,
store source and configuration fingerprints, universe and breadth fingerprints,
sector fingerprint, builder versions, classifier version and fingerprint,
feature definition version, candidate-link fingerprint, reconstruction count,
and candidate-link count. The audit is refused if candidate-link integrity fails.

Diagnostic v2 decision-readiness commands answer whether v2 outcome separation
is stable by candidate weighting and date weighting, whether v1/v2 regime
changes matter, whether setup and retracement interactions are material, whether
point-in-time breadth adds evidence, and whether sector history remains the
limiting input. The conclusion is deterministic and must identify the next
evidence milestone rather than tuning production thresholds from hindsight.

Performance optimization must preserve the exact point-in-time membership,
breadth and sector semantics validated by the reference implementation. The
optimized materialization uses deterministic batches and reusable source access,
but does not change membership rules, listing/delisting inference, sector
authority, breadth formulas, regime labels, thresholds, recommendations,
approvals, allocation, or diagnostic v1.

DuckDB database-backed Alpha commands must still run serially. The
point-in-time materializer does not delete lock files, allow concurrent writers,
or treat partial batches as complete.

Every point-in-time report supports text output. Exportable reports also support
`--format json` or `--format csv` with `--output`.

This layer is diagnostic-only. It must not change market-regime thresholds,
regime labels, classifier conditions, recommendation scores, recommendation
behavior, portfolio allocation, diagnostic v1 records, authoritative snapshots,
legacy candidate records, provenance manifests, release manifests, posterior
probabilities, expectancy, entry timing, trade plans, approvals, or allocation.
It must also not select historically optimal regime boundaries, change
market-intelligence weights, alter candidate generation, flip retracement signs,
overwrite diagnostic v2 inputs from outcomes, or represent reconstructed v2 as
exact historical production state.

## Reconstructed Regime Outcome Validation and Threshold Readiness

Alpha now validates the frozen diagnostic reconstruction dataset against replay
candidate outcomes without changing production behavior.

The audit identity includes:

- dataset version;
- dataset content fingerprint;
- classifier version used;
- classifier fingerprint used;
- feature-definition version;
- reconstruction count;
- candidate-link count;
- duplicate/orphan/future-source checks.

If the diagnostic dataset changes, the dataset fingerprint changes and the
outcome audit must be treated as a new research artifact.

Outcome universes are explicit:

- `ALL_COMPLETED_OUTCOMES`
- `ACCEPTABLE_ENTRY_TIMING`
- `BUY_OR_STRONG_BUY`
- `HIGH_DIAGNOSTIC_QUALITY`
- `HIGH_OR_MEDIUM_DIAGNOSTIC_QUALITY`
- `COMPLETE_DIAGNOSTIC_ONLY`
- `EXACT_LINEAGE_ONLY`
- `COMPATIBILITY_ONLY`

The audit reuses existing replay outcome fields: forward return,
benchmark-relative return, maximum favourable excursion, maximum adverse
excursion, target hit, stop hit, and the stored outcome-quality label. It does
not invent missing outcomes.

Candidate-weighted and date-weighted results are both required. Candidate-level
observations sharing one market date are not independent market-state
observations; threshold conclusions must include date-weighted analysis.

Recovering regime diversity does not prove that the current thresholds are
economically useful.

Threshold perturbation in this audit measures stability. It must not search for
or select the historically best-performing threshold.

The readiness scorecard reports independent dimensions instead of one opaque
score:

- regime diversity;
- outcome separation;
- quality stability;
- date-level stability;
- benchmark-only consistency;
- breadth-bias sensitivity;
- sector-data sufficiency;
- classifier compatibility;
- threshold sensitivity;
- sample adequacy.

Statuses are `READY`, `CONDITIONALLY_READY`, `NOT_READY`, or
`INSUFFICIENT_EVIDENCE`.

The audit remains diagnostic-only. It is prohibited to use this milestone to
change market-regime thresholds, neutral boundaries, regime labels,
market-intelligence weights, recommendation scores, verdicts, candidate
generation, entry timing, gates, trade plans, approvals, allocation, posterior
probabilities, expectancy, or retracement signs.

## Regime Intervention Shadow Mode

Alpha now supports diagnostic-only regime shadow policies that replay
alternative regime intervention behavior from frozen candidate inputs.

Shadow policies never replace Alpha’s authoritative recommendation. They
calculate alternative decisions from the same frozen inputs and store them only
as diagnostic evidence.

The supported policy registry is intentionally narrow and versioned:

- `regime-shadow-control-v1`: current production behavior, retained as the
  authoritative comparison path.
- `regime-shadow-context-only-v1`: regime retained for explanation, grouping
  and provenance, but removed from score, verdict, ranking, approval and
  allocation eligibility.
- `regime-shadow-bearish-only-v1`: current bearish negative adjustment retained;
  bullish and neutral adjustments removed.

Bearish-only attribution is required because full regime intervention may
conceal a useful downside-protection effect inside an otherwise weak classifier.

Shadow decisions are explicitly marked `AUTHORITATIVE=false`,
`EXECUTABLE=false` and `CAPITAL_EFFECT=none`. They must live in a separate
diagnostic repository, not in the candidate ledger, and must preserve source
fingerprints, policy fingerprints, classifier/recommendation/verdict/approval
and allocation policy versions, code version and configuration fingerprint.

Use these commands for the shadow audit:

- `poetry run python -m alpha replay regime-shadow-build`
- `poetry run python -m alpha replay regime-shadow-build --persist-diagnostic`
- `poetry run python -m alpha replay regime-shadow-status`
- `poetry run python -m alpha replay regime-shadow-integrity`
- `poetry run python -m alpha replay regime-shadow-score-comparison`
- `poetry run python -m alpha replay regime-shadow-verdict-comparison`
- `poetry run python -m alpha replay regime-shadow-approval-comparison`
- `poetry run python -m alpha replay regime-shadow-allocation-comparison`
- `poetry run python -m alpha replay regime-shadow-outcomes`
- `poetry run python -m alpha replay regime-shadow-outcomes --date-weighted`
- `poetry run python -m alpha replay regime-shadow-bearish-protection`
- `poetry run python -m alpha replay regime-shadow-bullish-promotion`
- `poetry run python -m alpha replay regime-shadow-setup-attribution`
- `poetry run python -m alpha replay regime-shadow-quality`
- `poetry run python -m alpha replay regime-shadow-temporal-stability`
- `poetry run python -m alpha replay regime-shadow-readiness`

Report commands support `--format json` or `--format csv` with `--output` where
structured export is required.

A replay advantage is not sufficient for production activation. Policy changes
require stable live shadow evidence, rollback controls and versioned
provenance.

It is prohibited to use this milestone to change production outputs, candidate
rows, scores, verdicts, ranking, approvals, allocation, thresholds, regime
classification logic, diagnostic stores, snapshots, provenance, release
manifests, trade plans, entry timing, candidate generation or portfolio policy.

## Live Regime Shadow Evidence Maturation

Alpha now separates replay shadow evidence from live shadow evidence under a
predefined sequential decision protocol.

Candidate count alone is not sufficient evidence because candidates sharing one
market date also share the same market regime.

Shadow evidence must mature before evaluation. Pending or partially matured
outcomes cannot be used to justify a policy change.

Live shadow evidence must be evaluated under a predefined sequential protocol.
Alpha must not repeatedly inspect outcomes and change thresholds, horizons or
readiness rules.

The evidence hierarchy is:

- candidate-level evidence for symbol and setup interactions;
- decision-date evidence for shared market-state evaluation;
- regime-episode evidence for contiguous bullish, neutral and bearish regimes;
- policy-difference events for intervention attribution;
- independent outcome blocks to avoid treating overlapping horizons as separate
  tests.

Outcome maturity uses fixed supported horizons: `1d`, `3d`, `5d`, `10d`, `20d`
and `60d`. The primary policy-decision horizon is `20d`, matching Alpha's
current swing-trade holding-period semantics. The primary horizon was not chosen
from the shadow result.

Observation maturity statuses are `NOT_DUE`, `DUE_BUT_UNAVAILABLE`,
`PARTIALLY_AVAILABLE`, `MATURED` and `INVALIDATED`. Policy readiness uses only
`MATURED` observations.

Holding-period alignment groups evidence into `SHORT_TERM`, `SWING`,
`POSITIONAL` and `UNAVAILABLE`. Alpha must not apply one universal outcome
horizon where trade horizons differ materially.

Market episodes are deterministic contiguous runs of the authoritative recorded
regime observed in live shadow records. Episodes track regime, start and end
date, trading days, candidate count, policy-difference count, matured outcomes
and source quality. Replay records are not converted into live episodes.

Minimum evidence is evaluated by separate dimensions rather than one opaque
score:

- matured candidate coverage;
- decision-date coverage;
- regime-episode coverage;
- bearish-event coverage;
- bullish-event coverage;
- transition coverage;
- holding-period coverage;
- setup coverage;
- quality coverage;
- recent-period coverage;
- policy-difference coverage.

Context-only readiness requires matured policy-difference events, distinct
market dates, distinct episodes, bearish and bullish/neutral coverage,
recent-period coverage, and no approval or allocation surprises.

Bearish-only readiness requires matured bearish demotions, distinct bearish
dates, distinct bearish episodes, protected losing candidates, acceptable
false-demotion rate, acceptable missed-upside burden, positive date-weighted
downside protection, temporal consistency, and no downstream surprises.

Sequential review is fixed by protocol version. Reviews are allowed only by the
configured cadence: monthly, after a predefined count of newly matured
policy-difference events, after a completed bearish episode, or after a
completed regime transition. Any change to the cadence, metrics, thresholds,
primary horizon or episode definition requires a new protocol version and a new
fingerprint.

Bearish protection classifications are `TRUE_PROTECTION`, `FALSE_DEMOTION`,
`AMBIGUOUS` and `OUTCOME_UNAVAILABLE`. A negative final return alone is not
sufficient; Alpha uses path-dependent fields such as MAE, stop hit, target hit
and outcome quality when available.

Context-only harm monitoring tracks bearish or neutral demotions removed,
losers promoted, downside reintroduced, MAE worsening, stop-hit rate and
false-positive increase. Replay already shows context-only harm, so live
evidence must materially contradict that before any formal review.

Downstream guardrails continuously monitor approval, allocation, target-weight
and capital-action differences. Any non-zero live difference is a
`DOWNSTREAM_POLICY_SURPRISE` and requires formal audit. Shadow records still
have no capital effect.

Drift detection compares live shadow behavior against the replay baseline for
score-difference distribution, verdict-difference rate, regime distribution,
setup distribution, bearish-demotion frequency and outcome quality. Replay is a
benchmark, not live evidence, and must not be pooled blindly with live outcomes.

The operational commands are:

- `poetry run python -m alpha replay regime-shadow-live-status`
- `poetry run python -m alpha replay regime-shadow-observation-coverage`
- `poetry run python -m alpha replay regime-shadow-outcome-maturity`
- `poetry run python -m alpha replay regime-shadow-outcome-refresh`
- `poetry run python -m alpha replay regime-shadow-outcome-refresh --persist-diagnostic`
- `poetry run python -m alpha replay regime-shadow-policy-differences`
- `poetry run python -m alpha replay regime-shadow-live-bearish-protection`
- `poetry run python -m alpha replay regime-shadow-live-context-harm`
- `poetry run python -m alpha replay regime-shadow-live-downstream-guardrails`
- `poetry run python -m alpha replay regime-shadow-live-quality`
- `poetry run python -m alpha replay regime-shadow-live-temporal`
- `poetry run python -m alpha replay regime-shadow-live-setup`
- `poetry run python -m alpha replay regime-shadow-live-drift`
- `poetry run python -m alpha replay regime-shadow-review-checkpoint`
- `poetry run python -m alpha replay regime-shadow-live-readiness`

The live protocol may recommend only collection, formal review, drift audit,
downstream surprise audit or retaining control. It must not recommend direct
production activation.

## Live Regime Shadow Capture Operations

Live regime shadow capture is the operational bridge between frozen
authoritative current-runtime candidates and diagnostic-only shadow evidence.

Live shadow evidence begins only when an eligible current-runtime authoritative
candidate is captured from its original frozen decision inputs. Replaying
historical decisions today does not create live evidence.

Shadow capture failure must never alter or interrupt Alpha’s authoritative
recommendation, approval, allocation or persistence.

A live shadow observation is valid only when CONTROL, CONTEXT_ONLY and
BEARISH_ONLY were calculated from identical non-regime inputs.

Eligible current-runtime source modes are `LIVE_STREAM`, `CURRENT_QUOTE`,
`LATEST_COMPLETED_SESSION`, `PAPER_RUNTIME` and `MANUAL_CURRENT_ANALYSIS`.
`REPLAY` and `HISTORICAL_BACKFILL` remain replay evidence and must not enter the
live shadow repository.

The authoritative freeze boundary is:

```text
market and candidate inputs
-> authoritative evaluation
-> authoritative result frozen
-> authoritative candidate persistence
-> diagnostic shadow capture
```

Shadow capture receives a read-only frozen input derived from the persisted
authoritative candidate. It must run after authoritative score, verdict, entry
timing, trade plan, approval and allocation are final.

Configuration is disabled by default:

```text
ALPHA_REGIME_SHADOW_ENABLED=false
ALPHA_REGIME_SHADOW_CAPTURE_LIVE=false
ALPHA_REGIME_SHADOW_POLICIES=context_only,bearish_only
ALPHA_REGIME_SHADOW_FAILURE_MODE=non_blocking
```

`CONTROL` is always retained as the comparison reference. Invalid policy names
are rejected. Configuration can enable only diagnostic observation, not
production policy selection.

Exactly-once semantics use the authoritative candidate id, provenance id,
decision timestamp, source fingerprint, policy registry fingerprint and protocol
fingerprint. CLI rerenders, export retries, service restarts and repeated
persistence calls must not create duplicate live observations.

Three-policy completeness is required. A valid observation requires CONTROL,
CONTEXT_ONLY and BEARISH_ONLY. Partial policy sets are incomplete and excluded
from readiness evidence.

Input parity validation requires matching non-regime fingerprints across
policies. Only the regime intervention policy may differ. Mismatches are
`INPUT_PARITY_FAILURE` and invalidate the observation.

Authoritative candidate persistence must occur before shadow observation
persistence. If authoritative persistence fails, no shadow observation is
created. If shadow persistence fails, the authoritative candidate remains valid
and the failure is captured as non-blocking diagnostic evidence.

Capture failures are typed by stage: configuration, eligibility, evaluation,
input parity and persistence. Only safe persistence failures are considered
repairable. Repair refuses reconstruction when exact frozen inputs are not
available and must not use later market inputs.

Nightly learning now invokes live shadow outcome refresh after ordinary
candidate outcome updates. The refresh is incremental, idempotent and records a
refresh manifest when persisted. Missing bars are not treated as zero returns.

Operational health tracks eligible authoritative decisions, captured
observations, capture rate, disabled skips, ineligible skips, insufficient input,
evaluation failures, persistence failures, incomplete policy sets, input parity
failures, orphan records, duplicate attempts and repairability.

Runtime coverage is audited across live stream monitoring, current intelligence,
manual current analysis, replay, historical backfill and nightly learning. An
eligible runtime path that does not invoke diagnostic capture blocks operational
readiness.

Operational commands:

- `poetry run python -m alpha replay regime-shadow-runtime-coverage`
- `poetry run python -m alpha replay regime-shadow-capture-health`
- `poetry run python -m alpha replay regime-shadow-capture-failures`
- `poetry run python -m alpha replay regime-shadow-capture-manifests`
- `poetry run python -m alpha replay regime-shadow-live-repair`
- `poetry run python -m alpha replay regime-shadow-live-repair --persist-diagnostic`
- `poetry run python -m alpha replay regime-shadow-input-parity`
- `poetry run python -m alpha replay regime-shadow-operational-readiness`
- `poetry run python -m alpha live-shadow-smoke-test --symbol SYMBOL`

The smoke test is non-executable, places no orders, alters no portfolio state
and must not count as formal live evidence.

### Alpha live wiring and collection readiness

`alpha live --symbols ...` remains a live feed monitor first. It does not
fabricate a full trading recommendation from a partial tick. When regime shadow
capture is explicitly enabled, the runtime now uses this order:

```text
provider configured
-> instrument subscription
-> live tick received
-> one-minute live bar snapshot constructed
-> feed health and staleness assessed
-> non-executable authoritative live diagnostic candidate persisted
-> frozen input created from the persisted candidate
-> LiveRegimeShadowCaptureService invoked
-> CLI rendering remains unchanged unless --shadow-diagnostics is requested
```

The live diagnostic candidate records a stable candidate id, decision
timestamp, symbol, frozen score/verdict, no-deployment approval state, source
mode, source fingerprint, market-state snapshot id and provenance id. It is
`WATCHLIST`/`AVOID`, approved capital is zero, and it is used only to validate
shadow capture wiring.

Eligible live decision event:

```text
a new persisted live diagnostic candidate id from a genuine live snapshot
```

Repeated CLI rendering, unchanged live snapshots, export retries, service
retries and process restarts must not create duplicate authoritative candidates
or duplicate shadow observations. Duplicate authoritative attempts are measured
separately from duplicate shadow attempts.

Source mode is recorded as:

- `LIVE_STREAM` when the snapshot is connected and fresh.
- `CURRENT_QUOTE` when the snapshot is stale or only current quote quality is
  available.
- `LATEST_COMPLETED_SESSION` only for completed-session intelligence paths.

Future timestamps are rejected. Missing provider data, missing candidate id,
missing provenance, incomplete frozen input and input parity failure produce
diagnostic skips or failures with no capital effect and no authoritative
mutation.

Safe diagnostic enablement:

```bash
export ALPHA_REGIME_SHADOW_ENABLED=true
export ALPHA_REGIME_SHADOW_CAPTURE_LIVE=true
export ALPHA_REGIME_SHADOW_POLICIES=context_only,bearish_only
export ALPHA_REGIME_SHADOW_FAILURE_MODE=non_blocking
```

Before passive collection begins, verify:

- `poetry run python -m alpha replay regime-shadow-runtime-coverage`
- `poetry run python -m alpha replay regime-shadow-alpha-live-wiring`
- `poetry run python -m alpha replay regime-shadow-capture-health`
- `poetry run python -m alpha replay regime-shadow-input-parity`
- `poetry run python -m alpha replay regime-shadow-operational-readiness`

Passive live collection is ready only when alpha live is wired and tested,
authoritative persistence succeeds, all three shadow policies are complete,
input parity is valid, exactly-once capture is valid, failure isolation is
valid, nightly discovery is valid, approval/allocation surprises are zero and
authoritative mutation count is zero.

### Upstox authentication bootstrap

Alpha treats Upstox credentials as local operator secrets. The repository may
contain `.env.example` with variable names, but real tokens, client secrets and
authorization codes must remain in environment variables, an operating-system
keychain, or an untracked local `.env` file.

Required variables:

- `UPSTOX_CLIENT_ID`: required to construct the authorization URL.
- `UPSTOX_CLIENT_SECRET`: required only for authorization-code exchange.
- `UPSTOX_REDIRECT_URI`: must match the URI configured in the Upstox app.
- `UPSTOX_ACCESS_TOKEN`: required for live feed access.
- `UPSTOX_TOKEN_METADATA_PATH`: optional safe metadata path; defaults to
  `.alpha/upstox_token_metadata.json`.
- `UPSTOX_INSTRUMENT_REGISTRY`: optional local instrument registry JSON path.

Token metadata stores only provider, token fingerprint, expected expiry, last
validation status and credential source. It never stores the raw access token,
authorization code or client secret.

Daily operating workflow:

1. Run `poetry run python -m alpha provider upstox status`.
2. If authorization is required, run
   `poetry run python -m alpha provider upstox login-url`.
3. Authorize the app in Upstox and copy the one-use code.
4. Run `poetry run python -m alpha provider upstox exchange-code` and paste
   the code when prompted. Avoid `--code` unless shell history risk is
   acceptable.
5. Export the received access token into the local environment for the current
   session.
6. Run `poetry run python -m alpha provider upstox validate-token`.
7. Run `poetry run python -m alpha provider upstox status --authorize-feed`.
8. Start `poetry run python -m alpha live --symbols SYMBOL`.

Upstox access tokens are treated as expiring at 3:30 AM India time on the next
applicable day. Alpha refuses to start the live provider when the configured
token is past its expected expiry.

Market-data feed status:

- Alpha records `UPSTOX_MARKET_DATA_FEED_V3` and uses the V3 feed-authorize
  endpoint to obtain the one-use WebSocket redirect URL.
- The current repository still has a provider shell for streaming transport:
  V3 WebSocket connection, binary subscription, protobuf decoding and
  reconnect classification are not yet materialized in production code.
- Formal live shadow evidence must therefore wait for a genuine authenticated
  snapshot from a completed feed implementation; replay, smoke tests and
  synthetic fixtures remain ineligible.
