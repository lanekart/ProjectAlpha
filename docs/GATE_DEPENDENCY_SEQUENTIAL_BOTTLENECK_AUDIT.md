# Gate Dependency & Sequential Bottleneck Audit

## Purpose

GDSBA v1.0 explains how the frozen institutional criteria jointly rejected the
1,781 BUY and STRONG BUY candidates in `ALPHA_BASELINE_v1.0`. It is a diagnostic
research subsystem. It does not change gate order, thresholds, recommendation
logic, approval policy, allocation, or trading behavior.

`PRODUCTION_INFLUENCE=false`

## Evidence Contract

The audit reads and verifies immutable evidence from:

- CABR `ALPHA_BASELINE_v1.0` for the policy identity, candidate counts, and
  initial diagnostic capital.
- ACU `ALPHA_CANONICAL_v1.0` for frozen criterion failure codes and
  explanations.
- IGTA `IGTA_v1.0` for point-in-time candidate identity and post-decision
  outcome classification.
- The exact approval-engine source whose deterministic tree hash matches the
  CABR and IGTA approval policy hash.

Every input checksum is validated before analysis. A mismatched baseline,
policy source, ACU artifact, IGTA artifact, or candidate population fails
closed.

## Two Lineage Views

The frozen decision engine accumulated every failed criterion before returning
its final decision. GDSBA therefore preserves two different and equally
important truths:

- `observed_status`: the complete set of criteria the frozen engine recorded as
  passing, failing, or not applicable.
- `sequential_status`: the path that would result if the same immutable
  criteria short-circuited in authoritative source order.

This distinction prevents later co-failures from being mislabeled as the first
cause of rejection. It also prevents the simulated short-circuit path from
erasing failures that were genuinely observed.

## Analyses

The package contains:

- `lineage.py`: complete candidate-by-criterion reconstruction.
- `gate_sequence.py`: typed authoritative criterion order and failure mapping.
- `dependency_graph.py`: conditional rejection value after another gate passes.
- `interaction_matrix.py`: joint failures, unique failures, Jaccard overlap, and
  lift.
- `marginal_value.py`: one-gate removal with no threshold changes.
- `gate_order.py`: all 5,040 permutations of the seven active failing criteria.
- `bottleneck.py`: first failures, survival, outcome paths, report cards, and
  bottleneck findings.
- `exports.py`: atomic deterministic CSV, Markdown, and checksum manifest
  output.

## Frozen Findings

The v1.0 evidence shows:

- 24,660 technical candidates led to 1,781 BUY or STRONG BUY candidates.
- `FINAL_EVIDENCE_SCORE` was the first failure for 1,119 candidates (62.83%).
- `HISTORICAL_SAMPLE` was the first failure for the remaining 662 (37.17%).
- `HISTORICAL_SAMPLE` appeared in the full observed failure set for all 1,781
  candidates, including all 486 false rejections.
- `FINAL_EVIDENCE_SCORE` was the largest sequential false-rejection blocker:
  305 of 486 false rejections (62.76%).
- Removing `HISTORICAL_SAMPLE` alone released only 15 candidates because all
  other candidates still failed at least one other criterion. Those 15 included
  7 false rejections, 6 correct rejections, and 2 marginal outcomes.
- Removing any other active criterion alone released no candidate.
- `HISTORICAL_SAMPLE` and `SETUP_SCORECARD` had the greatest supported overlap,
  with 98.71% Jaccard similarity.
- `STOP_DISTANCE` and `ENTRY_QUALITY` had the highest supported interaction
  lift, 1.21.
- Reordering the criteria changed no decision because the policy is a logical
  AND. It could reduce hypothetical short-circuit evaluation work by 27.10%,
  but this has no decision-quality implication.

These findings do not authorize a policy change. The next defensible research
question is whether the 15 candidates uniquely blocked by the historical-sample
criterion retain their observed edge in a separately reserved chronological
holdout under identical costs.

## Gate Report Cards

Grades combine resolved outcome count, rejection precision, unique marginal
survivors, and signed diagnostic value. A gate with no unique remove-one
survivors is classified `Research Only` because its independent value is not
identified in this population. Low sample counts are also `Research Only`.

Monetary fields use equal-share diagnostic notional derived from frozen CABR
initial capital. They are attribution measures, not a portfolio forecast or a
claim about deployable value.

## Commands

```text
poetry run python -m alpha gate-dependency audit
poetry run python -m alpha gate-dependency survival
poetry run python -m alpha gate-dependency interactions
poetry run python -m alpha gate-dependency report
```

The audit command accepts explicit `--igta-output`, `--acu-output`,
`--benchmark-output`, and `--output` paths. Read commands consume only exported
GDSBA artifacts.

## Artifacts

GDSBA exports:

- `gate_lineage.csv`
- `first_failure.csv`
- `gate_survival.csv`
- `dependency_matrix.csv`
- `interaction_matrix.csv`
- `marginal_value.csv`
- `false_rejection_paths.csv`
- `correct_rejection_paths.csv`
- `gate_report_card.csv`
- `gate_order.csv`
- `executive_report.md`
- `manifest.json`

The manifest records source and artifact checksums plus permanent isolation
guardrails.

## Constraints

- CABR did not preserve every component score, so GDSBA never reconstructs
  missing scores from future outcomes.
- Legacy warehouse limitations cap confidence in observed outcome economics.
- Gate order cannot affect an AND-combined policy's accepted set; ordering
  analysis concerns attribution and evaluation cost only.
- One-gate removal is not a portfolio replay and never changes production.

Permanent controls:

```text
PRODUCTION_INFLUENCE=false
NO_GATE_CHANGES=true
NO_ORDER_CHANGES=true
NO_THRESHOLD_CHANGES=true
```
