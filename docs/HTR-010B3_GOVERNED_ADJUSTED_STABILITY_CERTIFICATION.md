# HTR-010B3 Governed Adjusted Stability Certification

## Purpose

HTR-010B3 converts the accepted HTR-010B2 paired benchmark into a signed,
research-only activation decision. It does not alter RAW Historical Truth, enable
adjusted prices in production, or claim economic superiority.

The milestone is complete only when the signed B2 report and its RAW and
ADJUSTED benchmark artifacts pass deterministic integrity checks, stability
evidence covers four balanced replay windows, and both action-affected and
unaffected decision cohorts are observable.

## Inputs

The command requires explicit paths for:

- the signed `htr010b2_governed_adjusted_benchmark_report.json`;
- the B2 `raw/` benchmark artifact directory;
- the B2 `adjusted/` benchmark artifact directory;
- the canonical B1 corporate-action timeline;
- the B3 output directory.

No path is guessed from mutable local state.

## Signed handoff requirements

B3 accepts B2 only when:

- `contract_version=HTR-010B2-v1.0.0`;
- `readiness_decision=READY_FOR_GOVERNED_ADJUSTED_BENCHMARK_RESEARCH`;
- `governed_adjusted_benchmark_enabled=true`;
- `decision_metrics_evaluated=true`;
- the benchmark population is nonempty;
- unexplained divergences are zero;
- readiness blockers are empty;
- `ACTIVE_REPLAY_INTEGRATION=false`;
- `PRODUCTION_INFLUENCE=false`;
- the B2 report digest is valid.

Each benchmark manifest must be point-in-time enforced, prohibit future
leakage, remain diagnostic-only, and correctly hash every artifact it lists.
The candidate, approval, trade, eligibility, and capital artifacts are then
reconciled against the B2 summaries.

## Stability evidence

B3 partitions replay sessions into four balanced contiguous windows. Readiness
requires at least 80 replay sessions and at least 20 sessions per window.

For every window, B3 reports:

- RAW and ADJUSTED candidate counts;
- institutional approval counts;
- portfolio-entry counts;
- paired, RAW-only, and ADJUSTED-only decision counts;
- approval flips;
- signal changes;
- mean absolute score delta;
- RAW and ADJUSTED portfolio returns.

The partitioning is deterministic and depends only on the ordered replay
sessions.

## Corporate-action cohorts

Decision and trade rows are attributed retrospectively to:

- `ACTION_AFFECTED`;
- `UNAFFECTED`;
- each observed `ACTION_TYPE:<TYPE>` cohort.

A decision is action-affected when a resolved action for the same canonical
symbol becomes effective after the decision date and on or before the B2 replay
end. Future action evidence is used only for retrospective attribution; it is
never exposed to the original decision process.

B3 reports approval flips, signal changes, rejection-reason changes, score
deltas, paired trades, unmatched trades, exit-reason changes, and net-return
deltas. These are research observations, not optimization targets.

## Readiness

The ready state is:

`READY_FOR_GOVERNED_ADJUSTED_RESEARCH_ACTIVATION`

The blocked state is:

`BLOCKED_BY_INSUFFICIENT_STABILITY_EVIDENCE`

Blocking evidence includes:

- fewer than 80 replay sessions;
- an incomplete four-window partition;
- a window with fewer than 20 sessions;
- a window without paired decisions;
- no paired decisions overall;
- no action-affected paired decisions;
- no unaffected paired decisions;
- no resolved corporate-action evidence.

Artifact tampering, digest mismatches, duplicate decision keys, duplicate trade
identifiers, or RAW/ADJUSTED session-coverage differences fail immediately and
do not produce a ready certificate.

## Outputs

The command writes:

- `htr010b3_stability_certificate.json`;
- `htr010b3_research_activation_contract.json`;
- `htr010b3_window_stability.csv`;
- `htr010b3_cohort_stability.csv`;
- `htr010b3_decision_differences.csv`;
- `htr010b3_trade_differences.csv`;
- `htr010b3_executive_report.md`.

Both JSON contracts contain deterministic SHA-256 digests. A later adjusted
research consumer must call
`validate_governed_adjusted_research_activation` before consuming adjusted
research evidence.

## Command

```bash
poetry run python -m alpha benchmark governed-adjusted-stability \
  --b2-report artifacts/htr010b2_governed_adjusted_benchmark/htr010b2_governed_adjusted_benchmark_report.json \
  --raw-benchmark artifacts/htr010b2_governed_adjusted_benchmark/raw \
  --adjusted-benchmark artifacts/htr010b2_governed_adjusted_benchmark/adjusted \
  --corporate-action-artifact artifacts/htr010b1_canonical_action_materialization/htr010b1_canonical_action_timeline.json \
  --output artifacts/htr010b3_governed_adjusted_stability
```

The command includes a determinate six-stage progress bar.

## Validation

The milestone branch must pass the permanent repository gates before the real
B2 evidence is certified:

- locked Ruff check and format check;
- strict MyPy across the complete `alpha` package;
- the full HTR-010B2 regression suite;
- B3 command-registration, ready-path, blocked-path, artifact-tampering, and
  activation-contract guardrail tests;
- every permanent CI pytest shard.

The final acceptance remains a separate local run over the signed B2 artifacts.
The pull request stays draft until that command produces a reviewed B3
certificate and activation contract.

## Guardrails

A ready B3 contract permits only:

- governed benchmark research;
- diagnostic analysis;
- stability reporting.

It permanently records:

- `LIVE_SCORING_ENABLED=false`;
- `RECOMMENDATION_INFLUENCE=false`;
- `PORTFOLIO_POLICY_INFLUENCE=false`;
- `EXECUTION_INFLUENCE=false`;
- `LEARNING_MUTATION_ENABLED=false`;
- `ACTIVE_REPLAY_INTEGRATION=false`;
- `PRODUCTION_INFLUENCE=false`.

Production activation requires a separate future milestone and cannot be
inferred from B3 readiness.
