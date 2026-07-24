# HTR-010B5 Governed Institutional Approval-Gate Forensics and Non-Vacuity Certification

## Purpose

HTR-010B5 explains why the unchanged institutional approval engine rejected every
BUY or STRONG_BUY candidate in the policy-consistent zero-trade population certified
by HTR-010B4. It distinguishes a selective, empirically reached gate from an
unreachable, incomplete, vacuous, or hard-coded all-reject implementation.

The milestone does not change recommendation thresholds, institutional approval
policy, portfolio policy, execution assumptions, Historical Truth, or any production
consumer. It permits forensic research only.

## Required handoff

The command requires explicit paths for:

- the signed HTR-010B2 governed adjusted benchmark report;
- the signed HTR-010B4 trade-formation certificate;
- the B2 RAW and ADJUSTED benchmark artifact directories;
- the governed identity and corporate-action artifacts;
- the B1 final closure report;
- the B1H admission contract, identity admission, and paired universes;
- the Historical Truth snapshot source and B5 output directory.

All upstream JSON digests, benchmark manifest hashes, point-in-time flags, and
research-only guardrails are validated before the institutional decision path is
rerun. The B4 handoff must be the exact certified zero-trade state: funnel metrics
evaluated, economic metrics unevaluated, no implementation or divergence defects,
and the sole readiness blocker `ZERO_TRADE_POPULATION`. Benchmark artifact digests
must be valid SHA-256 values, candidate-statistics rows must cover every positive
replay session in deterministic order, and their first and last dates must equal the
signed manifest bounds. Every explicit input file and frozen policy source is
hashed before execution and verified unchanged immediately before certification.
The seven CABR `VersionFreeze` component hashes—features, candidate generation,
setup discovery, feature attribution, approval policy, trade-plan policy, and the
decision engine—are recomputed from the current source tree, required to match both
signed manifests, and rechecked after replay.

The governed stores are rebuilt from the signed B1/B1H inputs. Identity-session,
closure, admission, governed-input, unobserved-identity, canonical-attestation, and
replay-session lineage must match HTR-010B2 exactly. The forensic replay must emit a
nonempty deterministic canonical-attestation set that is a subset of the signed B2
attestation lineage. Intermediate store contracts live in a temporary workspace and
are removed after the paired replay closes.

## Forensic contract

For each RAW and ADJUSTED replay candidate, B5 records:

- the recommendation signal, score, evidence, entry, risk, data, and capacity inputs;
- every base gate family as a deterministic PASS or FAIL event;
- all reached stress-test outcomes and the stress final action;
- the reached trade-plan quality decision and final action;
- the terminal gate, final institutional approval, provisional upstream
  allocation, and post-gate portfolio state;
- reconciliation against the signed B2 approval row and B4 aggregate funnel counts;
- a deterministic input fingerprint for RAW-versus-ADJUSTED attribution.

A missing candidate, session, gate reason, stage result, benchmark parity match,
replay-session bound, or one-sided arm record is an implementation defect or
unexplained divergence. Approval of a non-approvable signal is an implementation
defect. Positive upstream allocation is recorded as provisional evidence, not treated
as post-gate approval, because the existing intelligence pipeline constructs allocation
before institutional evaluation. Any
candidate-level mismatch in signal, score, approval, or primary reason blocks
readiness; an aggregate count cannot conceal row-level drift. B5 never infers a
rejection reason from a zero count.

## Structural non-vacuity probes

The certificate executes isolated invariant probes against the frozen
`InstitutionalDecisionEngine`:

1. one complete control candidate must traverse the base, stress, and trade-plan
   stages and receive final acceptance;
2. one controlled mutation for every `RejectionReasonCode` must produce the expected
   base gate failure;
3. one candidate that clears every base gate must be rejected independently by the
   stress stage;
4. one candidate that clears the base and stress stages must be rejected independently
   by trade-plan quality;
5. the full probe set must produce identical results on two consecutive evaluations.

These synthetic probes are not replay candidates. They cannot affect benchmark
counts, recommendations, allocation, execution, learning, or production. They prove
only that the frozen gate can accept a compliant input and can discriminate the
base, stress, and trade-plan decision stages.

## Non-vacuity decision

The gate is certified non-vacuous only when:

- each arm contains at least one empirical BUY or STRONG_BUY candidate;
- every empirical rejection has a complete terminal trace;
- the control acceptance path is reachable;
- every base gate family is discriminating;
- independent stress-stage and trade-plan-stage rejection paths are discriminating;
- the probes are deterministic;
- B2/B4 reconciliation is exact;
- no implementation defect or unexplained RAW/ADJUSTED divergence remains.

A zero-approval population may therefore be policy-consistent without being
trade-ready. B5 certifies the decision mechanism, not economic superiority.

## Readiness states

- `READY_FOR_GOVERNED_APPROVAL_GATE_RESEARCH`
- `BLOCKED_BY_VACUOUS_APPROVAL_GATE`
- `BLOCKED_BY_UNREACHED_APPROVAL_GATE`
- `BLOCKED_BY_INSUFFICIENT_APPROVAL_GATE_EVIDENCE`
- `BLOCKED_BY_APPROVAL_FORENSIC_IMPLEMENTATION_DEFECT`
- `BLOCKED_BY_UNEXPLAINED_APPROVAL_GATE_DIVERGENCE`

The ready state enables governed approval-gate forensic research only. It does not
supersede HTR-010B4's block on governed adjusted trade research.

## Outputs

The command writes:

- `htr010b5_approval_gate_certificate.json`;
- `htr010b5_candidate_gate_forensics.csv`;
- `htr010b5_gate_event_ledger.csv`;
- `htr010b5_gate_prevalence.csv`;
- `htr010b5_raw_adjusted_gate_comparison.csv`;
- `htr010b5_structural_non_vacuity_probes.csv`;
- `htr010b5_evidence_deficiency_attribution.csv`;
- `htr010b5_executive_report.md`.

The certificate binds exactly the seven supporting files listed after the JSON
certificate, all eleven explicit input artifacts, rebuilt governed-store lineage,
canonical attestations, the seven frozen CABR pipeline-component hashes, and the
exact frozen policy source-file set. Validation rejects a missing or unexpected
support-artifact name, an invalid SHA-256 value, any
support-file modification, a readiness/enablement contradiction, or a ready-state
certificate that lacks empirical, structural, reconciliation, zero-approval,
lineage, or guardrail proof. A downstream consumer can also provide its current
project root to the validator and require exact frozen-policy and pipeline-component
parity.

## Command

```bash
poetry run python -m alpha benchmark governed-approval-gate-forensics \
  --b2-report artifacts/htr010b2_governed_adjusted_benchmark/htr010b2_governed_adjusted_benchmark_report.json \
  --b4-certificate artifacts/htr010b4_governed_trade_formation/htr010b4_trade_formation_certificate.json \
  --raw-benchmark artifacts/htr010b2_governed_adjusted_benchmark/raw \
  --adjusted-benchmark artifacts/htr010b2_governed_adjusted_benchmark/adjusted \
  --identity-artifact artifacts/htr010b1_identity_timeline.json \
  --corporate-action-artifact artifacts/htr010b1_canonical_action_timeline.json \
  --final-closure-report artifacts/htr010b1_final_closure_report.json \
  --admission-contract artifacts/htr010b1h_shadow_admission_contract.json \
  --identity-admission artifacts/htr010b1h_identity_admission.json \
  --raw-universe artifacts/htr010b1h_raw_universe.json \
  --adjusted-universe artifacts/htr010b1h_adjusted_universe.json \
  --historical-truth-snapshots alpha_data/snapshots \
  --output artifacts/htr010b5_governed_approval_gate_forensics
```

The command presents one determinate nine-stage progress bar.

## Guardrails

Every B5 certificate records:

- `GOVERNED_ADJUSTED_TRADE_RESEARCH_ENABLED=false`;
- `LIVE_SCORING_ENABLED=false`;
- `RECOMMENDATION_INFLUENCE=false`;
- `PORTFOLIO_POLICY_INFLUENCE=false`;
- `EXECUTION_INFLUENCE=false`;
- `LEARNING_MUTATION_ENABLED=false`;
- `ACTIVE_REPLAY_INTEGRATION=false`;
- `PRODUCTION_INFLUENCE=false`.

A ready certificate must keep every guardrail false, contain no implementation
defect or unexplained arm divergence, reconcile both benchmark arms with zero parity
mismatches, and preserve HTR-010B4's zero-trade blocker. Production activation,
policy relaxation, threshold changes, and economic claims require separate future
milestones.
