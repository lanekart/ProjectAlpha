# DSI-002 — Governed Gate Isolation and Counterfactual Shadow Experiment

## Purpose

DSI-002 isolates the downstream effect of institutional gates and deterministic inclusion-minimal remediation sets through research-only point-in-time shadow counterfactuals.

DSI-001 established that the observed real population is entirely co-blocked. DSI-002 therefore must not infer individual gate value from co-occurrence. It must reproduce the frozen baseline, apply semantically explicit shadow interventions, rerun downstream decision stages, and preserve all governance boundaries.

## One-milestone contract

DSI-002 is delivered in one branch, one draft pull request, and one signed real-data acceptance boundary. Internal implementation phases are allowed, but partial merges and production activation are forbidden.

## Required signed lineage

The final command must fail closed unless it verifies the exact signed B5, B7, B10, and DSI-001 certificates and every required bound artifact, including canonical report digests, certificate-file hashes, contract versions, readiness decisions, and source paths.

## Frozen policy boundary

The milestone may not change gate ordering, thresholds, evidence policy, setup matching, recommendation semantics, approval policy, allocation policy, portfolio rules, execution assumptions, outcome definitions, learning state, historical truth, default runtime, or production behavior.

## Counterfactual arms

- Baseline arm: reproduce the observed frozen path.
- Single-gate arms: shadow-pass exactly one selected gate and preserve every other observed gate result.
- Minimal remediation-set arms: derive deterministic inclusion-minimal gate sets that clear all observed blockers, prove minimality, deduplicate equivalent sets, and cap combinatorial expansion.
- RAW and ADJUSTED arms: execute separately and reconcile fail closed.

## Required downstream attribution

Each valid arm must report whether it clears all blockers, changes terminal gate, creates institutional approval, creates portfolio eligibility, creates entry readiness, forms a trade, and obtains a completed, pending, censored, non-entry, or unavailable outcome.

## Statistical governance

Effect size and statistical significance remain separate. Multiple-testing correction is mandatory. Insufficient isolated evidence must remain explicit. No retain, remove, or policy-change recommendation is permitted from observational, confounded, or insufficient evidence.

## Readiness states

- `READY_FOR_GOVERNED_GATE_ISOLATION_RESEARCH`
- `BLOCKED_BY_NO_EFFECTIVE_SINGLE_GATE_ARMS`
- `BLOCKED_BY_NO_VALID_MINIMAL_REMEDIATION_SETS`
- `BLOCKED_BY_INSUFFICIENT_ISOLATED_OUTCOMES`
- `BLOCKED_BY_COUNTERFACTUAL_SEMANTIC_INVALIDITY`
- `BLOCKED_BY_COMBINATORIAL_LIMIT`
- `BLOCKED_BY_MULTIPLE_TESTING_RISK`
- `BLOCKED_BY_POINT_IN_TIME_LEAKAGE`
- `BLOCKED_BY_UNEXPLAINED_ARM_DIVERGENCE`
- `BLOCKED_BY_SOURCE_CONTRACT_FAILURE`
- `BLOCKED_BY_IMPLEMENTATION_DEFECT`

A zero-approval, zero-trade, or zero-significant-arm result is not itself an implementation failure when it is the deterministic result of the frozen system.

## Governance flags

All final outputs must preserve:

- `causal_claim_permitted=false`
- `threshold_change_permitted=false`
- `approval_policy_change_permitted=false`
- `portfolio_policy_change_permitted=false`
- `execution_policy_change_permitted=false`
- `recommendation_influence=false`
- `execution_influence=false`
- `active_replay_integration=false`
- `production_influence=false`
