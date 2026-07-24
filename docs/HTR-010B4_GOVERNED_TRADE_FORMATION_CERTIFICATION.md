# HTR-010B4 Governed Trade-Formation and Economic Non-Vacuity Certification

## Purpose

HTR-010B4 explains the complete frozen RAW-versus-ADJUSTED candidate-to-trade funnel after the accepted HTR-010B2 benchmark and HTR-010B3 stability gate. It does not change thresholds, strategy logic, approval policy, portfolio policy, execution assumptions, Historical Truth, or production consumers.

The milestone is deliberately non-vacuous and fail-closed. It either certifies a sufficiently broad paired trade population for governed trade research, or it certifies why the unchanged policy produced no trades or insufficient trades.

## Signed inputs

The command requires explicit paths for:

- the signed HTR-010B2 governed adjusted benchmark report;
- the signed HTR-010B3 stability certificate;
- the signed HTR-010B3 research activation contract;
- the B2 RAW benchmark artifact directory;
- the B2 ADJUSTED benchmark artifact directory;
- the canonical B1 corporate-action timeline;
- the B4 output directory.

All JSON digests and every artifact hash listed by each benchmark manifest are verified before funnel evidence is constructed.

## Funnel contract

Every candidate is assigned exactly one terminal state along the unchanged path:

`candidate -> approvable signal -> institutional approval -> portfolio entry -> executed trade -> completed outcome`

Terminal gates include non-approvable signals, explicit institutional rejection reasons, zero-allocation or entry unavailability evidence, ranking/capital/liquidity restrictions, and completed trades. Missing or contradictory terminal evidence is an implementation defect.

The certificate separately reports:

- candidate, approvable-signal, approval, portfolio-entry, and trade counts;
- dominant gates and gate categories;
- paired RAW/ADJUSTED entry decisions;
- gate changes and unexplained divergences;
- paired, one-sided, and unmatched trades;
- transaction costs, slippage, realized returns, drawdowns, and capital utilization;
- action-affected, unaffected, and action-type cohorts.

## Readiness states

- `READY_FOR_GOVERNED_ADJUSTED_TRADE_RESEARCH`
- `BLOCKED_BY_ZERO_TRADE_POPULATION`
- `BLOCKED_BY_INSUFFICIENT_COMPLETED_TRADES`
- `BLOCKED_BY_FUNNEL_IMPLEMENTATION_DEFECT`
- `BLOCKED_BY_UNEXPLAINED_TRADE_DIVERGENCE`

The ready state requires at least 20 completed paired trades spanning at least two B3 stability windows. These thresholds are certification requirements only; the underlying benchmark policy is never relaxed to manufacture trades.

A zero-trade result can still be certified as policy-consistent when both arms have zero approvals and trades, every candidate has an explained terminal gate, and no implementation defect or unexplained divergence exists. Such a certificate remains blocked for trade research.

## Outputs

The command writes:

- `htr010b4_trade_formation_certificate.json`;
- `htr010b4_funnel_ledger.csv`;
- `htr010b4_gate_attribution.csv`;
- `htr010b4_entry_eligibility_comparison.csv`;
- `htr010b4_trade_pairing.csv`;
- `htr010b4_economic_impact.csv`;
- `htr010b4_action_cohort_impact.csv`;
- `htr010b4_executive_report.md`.

## Command

```bash
poetry run python -m alpha benchmark governed-trade-formation \
  --b2-report artifacts/htr010b2_governed_adjusted_benchmark/htr010b2_governed_adjusted_benchmark_report.json \
  --b3-certificate artifacts/htr010b3_governed_adjusted_stability/htr010b3_stability_certificate.json \
  --b3-activation-contract artifacts/htr010b3_governed_adjusted_stability/htr010b3_research_activation_contract.json \
  --raw-benchmark artifacts/htr010b2_governed_adjusted_benchmark/raw \
  --adjusted-benchmark artifacts/htr010b2_governed_adjusted_benchmark/adjusted \
  --corporate-action-artifact artifacts/htr010b1_canonical_action_materialization/htr010b1_canonical_action_timeline.json \
  --output artifacts/htr010b4_governed_trade_formation
```

The command has one determinate eight-stage progress bar.

## Implementation validation

The milestone branch is validated with locked Ruff checking and formatting, strict MyPy across `alpha`, the B2/B3/B4 benchmark regression path, and public CLI registration. The separate real-data acceptance certificate remains mandatory before merge.

## Guardrails

A B4 certificate never changes or enables production behavior. It records:

- `LIVE_SCORING_ENABLED=false`;
- `RECOMMENDATION_INFLUENCE=false`;
- `PORTFOLIO_POLICY_INFLUENCE=false`;
- `EXECUTION_INFLUENCE=false`;
- `LEARNING_MUTATION_ENABLED=false`;
- `ACTIVE_REPLAY_INTEGRATION=false`;
- `PRODUCTION_INFLUENCE=false`.

Economic superiority is never inferred from a zero-trade or insufficient-trade population. Production activation requires a separate future milestone.
