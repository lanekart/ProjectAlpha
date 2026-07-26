# DSI-002D Governed Stage Attribution

## Purpose

DSI-002D is an observational, frozen-policy replay boundary. It verifies the
accepted DSI-002A/B/C chain, replays the unchanged DSI-002C application path,
and records which evaluator stages produced the recorded terminal decision.
It does not change a gate, construct a counterfactual, approve a candidate, or
form a trade.

## Signed Source Boundary

The command requires the accepted DSI-002A, DSI-002B, and DSI-002C
certificates. Validation binds:

- the exact certificate content digest and file digest;
- the DSI-002A captured candidate and snapshot;
- the DSI-002B frozen section lineage;
- the DSI-002C recorded decision baseline;
- the common candidate identity, date, symbol, fingerprint, price arm, and
  snapshot hash;
- evaluator source hashes and frozen policy-section hashes.

Malformed schemas, path traversal, missing support files, snapshot tampering,
lineage substitution, population mismatch, and baseline substitution fail
before replay.

## Stage Semantics

The inventory follows the actual `IntelligenceApplicationService.run` and
`RecommendationEngine._build_one` path. Canonically observed stages record
`PASS`, `FAIL`, `UNKNOWN`, or `NOT_APPLICABLE`. A stage that was not called is
never inferred to have passed or failed.

Each event distinguishes:

- stage reachability from invocation;
- canonical observation from diagnostic observation;
- normalized gate codes from raw evaluator reasons;
- the first observed blocker from all observed blockers;
- a missing evaluator from a failed evaluator.

The first blocker is the earliest observed `FAIL` in immutable stage order.
All blockers contain only observed failures. Unknown and non-reached stages
remain explicit.

## Institutional Wiring Finding

The signed DSI-002C baseline invokes recommendation construction and portfolio
construction. It does not call the separate
`InstitutionalDecisionEngine.evaluate`, `DecisionStressTestEngine`, or
`TradePlanOptimizationEngine` path.

DSI-002D inventories these repository stages because the governed candidate
flow requires them, but marks each as `MISSING_EVALUATOR_WIRING`,
`NOT_REACHED`, and invocation count zero. It does not run them as a diagnostic
substitute because doing so would create a different decision path.

This omission blocks complete institutional-stage attribution even when the
recorded terminal recommendation has exact parity.

## Early Returns and Diagnostic Observation

Canonical early returns are preserved. A downstream stage may be observed
diagnostically only when its inputs remain semantically valid, the invocation
is read-only, and its event is labelled `DIAGNOSTIC_OBSERVATION_ONLY`.
Diagnostic outcomes never contribute to the canonical blocker list or
terminal decision. DSI-002D does not force evaluation on invalid inputs.

## Candidate Flow and Price Arms

Every accepted captured candidate must reconcile to one recorded terminal
state. The flow artifact reports request assembly, recommendation availability,
institutional formation, base stages, stress stages, trade-plan stages,
terminal state, and portfolio handoff.

RAW and ADJUSTED arms are never pooled. A missing paired arm is reported as
`NOT_COMPARABLE_SINGLE_SIGNED_ARM`, not as parity. Future paired arms must
classify every divergence using signed arm-specific evidence.

## Readiness

`READY_FOR_GOVERNED_STAGE_ATTRIBUTION_RESEARCH` means the frozen stage path is
observable enough for a later governed counterfactual bundle. It does not
authorize an override.

Readiness fails closed for invalid source evidence, empty populations,
incomplete stage inventory, flow defects, parity defects, incomplete
attribution, unexplained omissions, duplicate invocations, implementation
errors, unexplained arm divergence, or artifact-integrity defects.

## Command

```bash
poetry run python -m alpha benchmark \
  decision-superiority-gate-isolation-stage-attribution \
  --dsi002a-certificate <DSI-002A-CERTIFICATE> \
  --dsi002b-certificate <DSI-002B-CERTIFICATE> \
  --dsi002c-certificate <DSI-002C-CERTIFICATE> \
  --output <OUTPUT-DIRECTORY>
```

The output contains the certificate, stage inventory, event ledger, rejection
attribution, omissions, flow reconciliation, arm comparison, invocation
integrity, structural probe ledger, source contract snapshot, and executive
report. Every support artifact is hash-bound by the certificate.

## Governance

All causal, policy-change, gate-order, counterfactual, synthetic,
recommendation, portfolio, execution, learning, replay-integration, live
scoring, and production influence flags remain false.

`PRODUCTION_INFLUENCE=false`
