# DSI-002D1 Canonical Institutional Evaluator Wiring

## Purpose

DSI-002D1 repairs the governed research path that records the DSI-002 decision
baseline. It makes the existing institutional evaluator chain observable without
changing ordinary application, live, scoring, approval, allocation, execution, or
production behavior.

`PRODUCTION_INFLUENCE=false`.

## Original Signed Path

The accepted DSI-002C path validated the frozen snapshot lineage, then rebuilt the
application input with `DemoIntelligenceInputBuilder`. It executed recommendation
generation and portfolio allocation, but did not inject or invoke
`InstitutionalDecisionEngine`.

The exact defect classification is:

- `ALTERNATE_DECISION_PATH_USED`: the frozen assembler output was not the
  application input provider used by DSI-002C.
- `EVALUATOR_NOT_INJECTED`: the application service had no institutional engine.
- `RECORDED_DECISION_BYPASSES_INSTITUTIONAL_STACK`: the recorded payload contained
  no institutional stage result or trace.

The alternate-input limitation is retained and disclosed. DSI-002D1 does not
silently broaden a wiring-only milestone into a frozen-input migration.

## Governed Complete Path

The explicit governed path is:

1. validate DSI-002A/B/C/D signed lineage;
2. build the unchanged application input;
3. create recommendations;
4. construct the signed candidate population;
5. invoke institutional base decision exactly once;
6. invoke stress evaluation exactly once;
7. invoke trade-plan optimization exactly once;
8. produce the terminal institutional report;
9. preserve the existing portfolio allocation result;
10. serialize the institutional trace with the recorded decision.

`InstitutionalDecisionEngine.evaluate_with_trace` is the authoritative
orchestrator. Stress and trade-plan evaluators retain their existing fail-closed
early-return behavior when the base decision rejects a candidate. Such stages are
recorded as invoked and semantically not applicable, not omitted.

## Runtime Boundary

The institutional engine is available through constructor injection and is enabled
only when `governed_institutional_evaluation_enabled=True`. Enabling governed mode
without an engine fails closed. An empty governed candidate selection also fails
closed.

The default constructor does not invoke or serialize institutional evaluation.
Its payload remains byte-semantically identical to the signed DSI-002C baseline.
Production activation requires a separate policy and migration review.

## Baseline Renewal

The command creates append-only evidence:

- DSI-002D1 wiring repair certificate and source-contract artifacts;
- DSI-002B2 complete evaluator lineage and invocation inventory;
- DSI-002C2 complete-stack recorded decision baseline;
- DSI-002D2 complete-stack stage attribution.

The accepted DSI-002A/B/C/D artifacts are validated and never overwritten.
DSI-002D2 can be ready only when base, stress, trade-plan optimizer, terminal
institutional, and allocation stages are observed exactly once and attribution
fully reconciles.

For the signed BEL observation, the old recommendation remains `WATCHLIST`, while
the authoritative institutional terminal state is `REJECT` and allocation remains
`SKIP`. This is a legitimate newly observed complete-stack decision difference,
not a policy change or an attempt to force parity.

## CLI

```bash
poetry run python -m alpha benchmark \
  decision-superiority-complete-stack-baseline \
  --dsi002a-certificate <PATH> \
  --dsi002b-certificate <PATH> \
  --dsi002c-certificate <PATH> \
  --dsi002d-certificate <PATH> \
  --output <PATH>
```

The command validates the old signed chain, diagnoses the defect, runs the
governed application path, exports D1/B2/C2/D2 evidence, and prints every readiness
decision and governance flag.

## Integrity

Certificates bind their source commit, candidate identity, snapshot hash, report
hash, support-artifact hashes, and the complete governance-flag set. Validation
fails for missing flags, true flags, altered support files, substituted
certificates, invalid paths, report hash mismatch, or a non-ready certificate when
ready evidence is required.

RAW and ADJUSTED arms remain isolated. The signed population contains only RAW, so
the ADJUSTED comparison is reported as unavailable rather than inferred.

No synthetic recommendations, approvals, trades, outcomes, causal claims, economic
superiority claims, gate overrides, policy changes, live scoring, or active replay
integration are permitted.
