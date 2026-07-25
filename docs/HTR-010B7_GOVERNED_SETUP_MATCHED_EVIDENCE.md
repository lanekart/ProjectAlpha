# HTR-010B7 Governed Setup-Matched Evidence Sufficiency and Outcome-Coverage Certification

## Purpose

HTR-010B7 explains the evidence bottleneck certified by HTR-010B6. It
reconstructs the point-in-time setup identity for every RAW and ADJUSTED
approvable candidate, reconciles the signed sample metadata used by the unchanged
institutional gate, measures the deficit to the frozen 60-completed-sample rule,
and records the forward-outcome coverage available inside the governed replay.

The milestone is diagnostic and policy neutral. It does not lower the evidence
threshold, widen setup matching, generate synthetic outcomes, modify recorded
outcomes, or claim that any candidate would have been approved after a hypothetical
change.

## Required handoff

The command requires explicit paths for:

- a signed HTR-010B5 certificate in
  `READY_FOR_GOVERNED_APPROVAL_GATE_RESEARCH` state;
- a signed HTR-010B6 certificate in
  `READY_FOR_GOVERNED_APPROVAL_CONSTRAINT_RESEARCH` state;
- the governed identity and corporate-action artifacts bound by B5;
- the B1 final closure report;
- the B1H admission contract, identity admission, and paired universes;
- the Historical Truth warehouse and snapshot root;
- a fresh B7 output directory.

B7 validates B5 and B6 with `require_ready=True` and checks that B6 binds the
supplied B5 certificate file. It verifies all referenced B5 and B6 support-file
hashes before reading the candidate, gate, frontier, and margin ledgers.

## Governed replay reconstruction

B7 rebuilds the paired RAW and ADJUSTED stores from the same signed identity,
action, closure, and admission inputs used by B5. It verifies:

- identity-session lineage;
- final-closure lineage;
- admission-contract lineage;
- every explicit input file hash;
- canonical consumer attestations;
- frozen policy-source hashes;
- frozen pipeline-component hashes.

The legacy governed-input manifest includes literal input path strings. Therefore,
a different absolute-versus-relative path spelling may change that legacy manifest
digest even when all files are identical. B7 records the path-sensitive digest but
uses the signed input file hashes and path-neutral lineage checks as the governing
identity proof. This avoids both false rejection from path spelling and silent
acceptance of changed evidence.

## Setup identity and outcome recovery

For each governed arm, B7 reruns the unchanged canonical audit over the signed
replay window. The audit recovers:

- recommendation rank and score;
- final signal;
- setup type;
- setup stage;
- point-in-time forward entry status;
- completed, pending, or non-entered outcome status;
- realised return and R multiple when available;
- exit reason and audit note.

The rerun record must reconcile with the B5 candidate ledger. Rank, final signal,
score, setup stage, candidate population, and outcome-row coverage are checked
explicitly. Missing or ambiguous setup identities fail closed.

## Frozen evidence rule

The institutional policy remains unchanged:

- a non-`STRONG` evidence row requires at least 60 completed matched samples;
- historical posterior must be at least 0.52 when the historical-edge gate applies;
- historical expectancy must be at least 0.10 when that gate applies.

B7 records the signed sample count, deficit to 60, coverage ratio, posterior and
expectancy availability, B5 gate result, and B6 sample-gap result. It does not infer
a missing sample count from unrelated populations.

## Certified observations versus diagnostic suspicions

B7 separates two evidentiary levels.

### Certified observations

These are directly supported by signed candidate metadata or governed forward
outcomes:

- sample count unavailable;
- zero matched outcomes;
- matched-outcome deficit below 60;
- evidence-strength label unavailable;
- posterior unavailable;
- expectancy unavailable;
- end-of-window outcome censoring;
- recorded-plan entry non-occurrence.

### Diagnostic suspicions

These are labelled hypotheses, not causal findings:

- setup rarity suspected when observed setup occurrences are below 60;
- matching fragmentation suspected when at least 60 setup occurrences exist but no
  candidate satisfies the matched-sample rule.

A B7 certificate always records
`diagnostic_suspicion_may_be_claimed_as_causality=false`.

## Evidence and outcome coverage

The setup-cohort ledger summarizes, by price arm and setup type:

- candidate count;
- unique symbols;
- observed sessions;
- known and unknown sample counts;
- minimum, median, maximum, and average samples;
- candidates meeting or missing the 60-sample rule;
- total sample deficit;
- completed, pending, and non-entered forward outcomes;
- completion rate;
- diagnostic rarity and fragmentation flags.

The outcome ledger remains point in time. Future data is used only after each
recorded decision to label the frozen trade plan. Pending end-of-data rows remain
pending; B7 does not manufacture an outcome.

## RAW-versus-ADJUSTED comparison

Candidates are paired by decision date and symbol. B7 compares:

- reconstructed setup type;
- signed evidence sample count and deficit;
- forward-outcome status;
- certified observed-cause set;
- B5 input fingerprint.

A difference is explained only when the B5 input fingerprint changed between price
arms. A one-sided candidate or changed evidence state with unchanged inputs is an
unexplained divergence and blocks readiness.

## Deterministic probes

The milestone runs deterministic probes for:

- missing sample count;
- zero samples;
- 59 samples;
- exactly 60 samples;
- more than 60 samples;
- the governed `STRONG` evidence override.

Each probe verifies the sample deficit, certified observed cause, diagnostic
suspicion, and repeatability. These probes exercise the B7 attribution contract;
they do not mutate replay candidates.

## Readiness states

- `READY_FOR_GOVERNED_SETUP_MATCHED_EVIDENCE_RESEARCH`
- `BLOCKED_BY_EMPTY_SETUP_MATCHED_EVIDENCE_POPULATION`
- `BLOCKED_BY_INCOMPLETE_EVIDENCE_PROVENANCE`
- `BLOCKED_BY_SETUP_IDENTITY_RECONSTRUCTION_DEFECT`
- `BLOCKED_BY_UNEXPLAINED_EVIDENCE_DIVERGENCE`

The ready state requires nonempty approvable populations in both arms, complete
setup identities, complete signed provenance, passing probes, no implementation
defect, and no unexplained RAW-versus-ADJUSTED evidence divergence.

## Outputs

The command writes one certificate and nine support artifacts:

- `htr010b7_setup_matched_evidence_certificate.json`;
- `htr010b7_candidate_evidence_sufficiency.csv`;
- `htr010b7_setup_cohort_coverage.csv`;
- `htr010b7_outcome_coverage_ledger.csv`;
- `htr010b7_evidence_deficit_attribution.csv`;
- `htr010b7_setup_fragmentation_diagnostics.csv`;
- `htr010b7_raw_adjusted_evidence_comparison.csv`;
- `htr010b7_evidence_provenance_audit.csv`;
- `htr010b7_evidence_boundary_probe_ledger.csv`;
- `htr010b7_executive_report.md`.

Every support-file hash, upstream certificate hash, evidence-ledger hash, explicit
input hash, policy hash, and pipeline hash is bound into the certificate.

## Command

```bash
poetry run python -m alpha benchmark governed-setup-matched-evidence \
  --b5-certificate artifacts/htr010b5/htr010b5_approval_gate_certificate.json \
  --b6-certificate artifacts/htr010b6/htr010b6_approval_constraint_certificate.json \
  --identity-artifact artifacts/identity/htr010b1_canonical_identity_timeline.json \
  --corporate-action-artifact artifacts/actions/htr010b1_canonical_action_timeline.json \
  --final-closure-report artifacts/closure/htr010b1_final_closure_report.json \
  --admission-contract artifacts/admission/htr010b1h_replay_contract.json \
  --identity-admission artifacts/admission/htr010b1h_identity_admission.json \
  --raw-universe artifacts/admission/htr010b1h_raw_universe.json \
  --adjusted-universe artifacts/admission/htr010b1h_adjusted_universe.json \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --historical-truth-snapshots alpha_data/snapshots \
  --output artifacts/htr010b7_governed_setup_matched_evidence
```

## Guardrails

Every B7 certificate records:

- `THRESHOLD_CHANGE_PERMITTED=false`;
- `SYNTHETIC_OUTCOMES_PERMITTED=false`;
- `OUTCOME_BACKFILL_MUTATION_ENABLED=false`;
- `DIAGNOSTIC_SUSPICION_MAY_BE_CLAIMED_AS_CAUSALITY=false`;
- `GOVERNED_ADJUSTED_TRADE_RESEARCH_ENABLED=false`;
- `LIVE_SCORING_ENABLED=false`;
- `RECOMMENDATION_INFLUENCE=false`;
- `PORTFOLIO_POLICY_INFLUENCE=false`;
- `EXECUTION_INFLUENCE=false`;
- `LEARNING_MUTATION_ENABLED=false`;
- `ACTIVE_REPLAY_INTEGRATION=false`;
- `PRODUCTION_INFLUENCE=false`.

B7 permits setup-matched evidence research only. Any threshold change, setup-match
policy change, learning mutation, trade research, economic claim, or production
activation requires a separate governed milestone.
