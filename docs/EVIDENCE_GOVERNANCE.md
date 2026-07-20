# Evidence Governance

Alpha's evidence registry is diagnostic and governance-only. It does not place orders,
change production policy, or directly emit lifecycle decisions.

## Maturity levels

- `L0 PROTOTYPE`: exploratory and incomplete.
- `L1 DETERMINISTIC`: repeatable implementation with deterministic tests.
- `L2 REPLAY_VERIFIED`: validated against governed replay data.
- `L3 FORWARD_VALIDATED`: validated on chronological or live-forward evidence.
- `L4 PRODUCTION_TRUSTED`: approved for governed production decision input.
- `L5 SELF_CALIBRATING`: continuously recalibrated from verified outcomes.

Maturity is informational by default. Environment-specific policies decide whether an
evidence provider is allowed, diagnostic-only, or blocked.

## Environments

- `RESEARCH`: permits prototype, deterministic, and penalized evidence for analysis.
- `SHADOW`: requires replay verification and sufficient sample size.
- `PRODUCTION`: requires forward validation, sufficient sample size, and active status.

Failing an environment policy does not silently discard evidence. The registry returns a
deterministic assessment with explicit reasons.

## Registry invariants

- Evidence IDs are normalized and unique.
- Conflicting duplicate registrations fail closed.
- Sample sizes cannot be negative.
- Precision and calibration error are bounded between zero and one.
- Replay maturity requires replay verification.
- Forward-validation maturity requires a recorded validation date.
- Suspended and deprecated evidence is blocked.
- Registry metadata has `production_influence=False` and cannot execute trades.

## Deterministic outputs

The framework provides stable JSON, CSV, summary, and policy-assessment outputs for
future CLI integration, audits, release gates, and the Decision Orchestrator.
