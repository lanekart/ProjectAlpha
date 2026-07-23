# HTR-010B1 Final Governed Adjusted-Replay Closure

This milestone closes the remaining B1 chain in one governed workflow.

## Scope

The final engine:

- consumes B1F official bridge certifications and B1G propagation directives;
- rebuilds bridge validation state;
- rebuilds affected admission intervals;
- preserves official evidence IDs and SHA-256 lineage;
- admits certified identity continuity without silently enabling production replay;
- keeps unresolved cases, including MCX, quarantined;
- compares raw and adjusted shadow replay summaries;
- emits one final readiness decision.

## Readiness states

- `READY_FOR_GOVERNED_ADJUSTED_REPLAY`
- `READY_WITH_GOVERNED_EXCLUSIONS`
- `BLOCKED_BY_DATA_GAPS`
- `BLOCKED_BY_CONTRACT_CONTRADICTIONS`
- `BLOCKED_BY_IMPLEMENTATION_DEFECTS`

## Command

```bash
poetry run python -m alpha.historical_truth.b1_final_closure_cli \
  --b1f-certifications artifacts/htr010b1f_official_evidence_certification_bundle_2026/05_semantic_review/htr010b1f_bridge_certifications.json \
  --b1g-directives artifacts/htr010b1g_reconciliation/htr010b1g_propagation_directives.json \
  --validation-results artifacts/htr010b1e2_final_admission_state_propagation_2026/factor_validation_results.json \
  --admission-intervals artifacts/htr010b1e2_final_admission_state_propagation_2026/replay_admission_intervals.json \
  --b1a-output artifacts/htr010b1a_admission_contract_integrity_repair \
  --b1b-output artifacts/htr010b1b_continuity_universe_closure \
  --b1c-output artifacts/htr010b1c_full_history \
  --b1d-output artifacts/htr010b1d2_bridge_aware_validation_repair_2026 \
  --b1e-output artifacts/htr010b1e2_final_admission_state_propagation_2026 \
  --b1f-output artifacts/htr010b1f_official_evidence_certification_bundle_2026 \
  --b1g-output artifacts/htr010b1g_reconciliation \
  --raw-replay-summary artifacts/b1_shadow/raw_replay_summary.json \
  --adjusted-replay-summary artifacts/b1_shadow/adjusted_replay_summary.json \
  --output artifacts/htr010b1_final_closure_2026
```

Exact input filenames may be supplied from the governed artifacts produced by the local run.

## Outputs

- `htr010b1_final_closure_report.json`
- `htr010b1_final_rebuilt_validations.json`
- `htr010b1_final_rebuilt_admission_intervals.json`
- `htr010b1_final_governed_exclusions.json`
- `htr010b1_final_shadow_replay_comparison.json`
- `htr010b1_final_executive_report.md`

## Test policy

During development:

```bash
make test-b1-final
make validate-fast
```

At milestone acceptance:

```bash
make validate-milestone
make test-full
```

The full suite runs once at the final PR readiness boundary.

## Guardrails

- No production-policy changes.
- No strategy optimization.
- No retrospective decision mutation.
- No silent identity assumptions.
- Adjusted replay remains disabled until the final readiness report permits the next integration stage.
- `PRODUCTION_INFLUENCE=false`.
