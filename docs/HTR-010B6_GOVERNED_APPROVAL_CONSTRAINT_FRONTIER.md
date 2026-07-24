# HTR-010B6 Governed Approval-Constraint Frontier and Remediation Attribution

## Purpose

HTR-010B6 converts the accepted HTR-010B5 institutional approval-gate evidence into
a deterministic constraint frontier. It identifies every frozen constraint binding an
approvable RAW or ADJUSTED candidate, measures numeric distance-to-clear when the
signed evidence supports measurement, and records the minimal evidence or setup work
required under the existing policy.

The milestone does **not** change strategy logic, institutional approval thresholds,
stress rules, trade-plan rules, portfolio policy, execution assumptions, Historical
Truth, or production consumers. It does not claim that a candidate would have been
approved after a hypothetical mutation. It describes the observed frontier only.

## Required handoff

The command requires:

- a signed HTR-010B5 approval-gate certificate in
  `READY_FOR_GOVERNED_APPROVAL_GATE_RESEARCH` state;
- the seven B5 support artifacts in the same directory;
- the exact policy and pipeline source tree bound by the B5 certificate;
- a B6 output directory.

B6 validates B5 with `require_ready=True`. It then verifies and loads the bound
candidate and gate-event ledgers. The B5 certificate, candidate ledger, gate ledger,
frozen policy hashes, and frozen pipeline-component hashes are all bound into the B6
certificate.

## Frozen threshold contract

B6 snapshots the measurable thresholds used by the unchanged institutional stack,
including:

- MEDIUM adjusted-confidence eligibility;
- deployment score of 85;
- 60 completed matched-setup samples for base approval evidence;
- posterior probability of 0.52 and expectancy of 0.10 for historical edge;
- base reward/risk of 2R;
- base stop-distance maximum of 10%;
- base capacity score of 35;
- stress sample, reward/risk, volatility, capacity, and stop-distance requirements;
- optimized trade-plan quality score of 70.

Every base and stress gate family also receives a categorical contract row. B6 never
imputes a numeric distance when the B5 evidence does not contain the required metric.
Categorical constraints therefore remain explicit rather than being assigned an
invented score.

## Constraint frontier

For every approvable candidate, B6 records:

- all reached failed base, stress, stress-final-action, and trade-plan gates;
- the exact frozen constraint identifier and remediation class;
- threshold, observed value, signed margin, gap-to-clear, and normalized gap for
  measurable constraints;
- explicit categorical constraints for evidence not represented numerically;
- the minimum remediation set required by the conjunctive frozen policy;
- nearest measured constraints and a deterministic per-arm frontier rank;
- the candidate input fingerprint inherited from B5.

A minimal remediation set contains all distinct failed constraints. This is not a
policy-relaxation simulation: every failed constraint must be resolved under the
existing policy. The ledger always records
`policy_threshold_change_required=false` and
`counterfactual_approval_claimed=false`.

## RAW-versus-ADJUSTED comparison

B6 pairs candidates by decision date and symbol. A changed constraint set or gap is
explained only when the B5 input fingerprint changed between price arms. A one-sided
candidate or a changed frontier with unchanged inputs is an unexplained divergence
and blocks readiness.

## Boundary probes

The certificate runs deterministic boundary probes for every measurable threshold.
Each probe checks an observation below, exactly at, and above the frozen boundary and
verifies the comparator semantics. These probes test the B6 measurement contract;
they do not alter replay candidates and cannot influence recommendation, approval,
allocation, execution, learning, or production.

## Readiness states

- `READY_FOR_GOVERNED_APPROVAL_CONSTRAINT_RESEARCH`
- `BLOCKED_BY_EMPTY_APPROVAL_CONSTRAINT_POPULATION`
- `BLOCKED_BY_INCOMPLETE_APPROVAL_CONSTRAINT_EVIDENCE`
- `BLOCKED_BY_CONSTRAINT_FRONTIER_IMPLEMENTATION_DEFECT`
- `BLOCKED_BY_UNEXPLAINED_CONSTRAINT_FRONTIER_DIVERGENCE`

The ready state requires nonempty approvable populations in both price arms,
classified constraint evidence for every candidate, passing deterministic boundary
probes, no implementation defect, and no unexplained RAW-versus-ADJUSTED frontier
divergence.

## Outputs

The command writes:

- `htr010b6_approval_constraint_certificate.json`;
- `htr010b6_candidate_constraint_frontier.csv`;
- `htr010b6_constraint_margin_ledger.csv`;
- `htr010b6_gate_bottleneck_prevalence.csv`;
- `htr010b6_minimal_remediation_sets.csv`;
- `htr010b6_raw_adjusted_constraint_comparison.csv`;
- `htr010b6_threshold_contract_snapshot.csv`;
- `htr010b6_counterfactual_probe_ledger.csv`;
- `htr010b6_executive_report.md`.

Every supporting artifact hash is bound into the signed B6 certificate. Validation
fails closed after a support-file change, source-hash change, readiness contradiction,
or governance-flag change.

## Command

```bash
poetry run python -m alpha benchmark governed-approval-constraint-frontier \
  --b5-certificate artifacts/htr010b5_governed_approval_gate_forensics/htr010b5_approval_gate_certificate.json \
  --output artifacts/htr010b6_governed_approval_constraint_frontier
```

The command displays one determinate seven-stage progress bar.

## Implementation validation

The milestone branch is validated with locked Ruff checking and formatting, strict
MyPy across `alpha`, focused B6 contract and tamper regressions, public CLI
registration, and every permanent repository CI shard. A signed real-data B6
certificate over the accepted B5 artifact directory remains mandatory before merge.

## Guardrails

Every B6 certificate records:

- `POLICY_CHANGE_PERMITTED=false`;
- `THRESHOLD_CHANGE_PERMITTED=false`;
- `COUNTERFACTUAL_MUTATION_ENABLED=false`;
- `COUNTERFACTUAL_APPROVAL_CLAIMED=false`;
- `GOVERNED_ADJUSTED_TRADE_RESEARCH_ENABLED=false`;
- `LIVE_SCORING_ENABLED=false`;
- `RECOMMENDATION_INFLUENCE=false`;
- `PORTFOLIO_POLICY_INFLUENCE=false`;
- `EXECUTION_INFLUENCE=false`;
- `LEARNING_MUTATION_ENABLED=false`;
- `ACTIVE_REPLAY_INTEGRATION=false`;
- `PRODUCTION_INFLUENCE=false`.

B6 permits approval-constraint research only. Economic claims, threshold changes,
policy changes, governed trade research, or production activation require separate
future milestones.
