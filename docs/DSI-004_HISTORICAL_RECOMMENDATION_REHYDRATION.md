# DSI-004 Historical Recommendation Rehydration

## Purpose

DSI-004 determines which DSI-003 historical candidates can be represented by
authentic canonical recommendation objects. It does not fill missing fields,
apply present-day defaults to historical rows, relax a gate, change a
threshold, or create a synthetic trade.

`PRODUCTION_INFLUENCE=false`.

## Governing Boundary

A historical candidate summary is not a recommendation object. Exact DSI-002
counterfactual replay requires the complete object that produced the
institutional candidate, including nested evidence, setup, trade-plan,
metadata, policy, and fingerprint state.

Only these classes are admission eligible:

- `EXACT_FROZEN_OBJECT`;
- `EXACT_SERIALISED_OBJECT_REHYDRATED`;
- `CANONICAL_POINT_IN_TIME_RECONSTRUCTION_PARITY_PROVEN`.

Partial objects and summary rows remain excluded.

## Source Chain

The command validates the signed DSI-003 certificate and every bound support
artifact. DSI-003 certificate hashes remain authoritative for upstream sources
that were intentionally not copied into its portable acceptance directory.
The locally required DSI-002A, renewed B2/C2/D1/D2, and final DSI-002
certificates are resolved by exact SHA-256. Ambiguous, substituted, or missing
required local evidence fails closed.

The DSI-002A frozen snapshot is independently loaded through the accepted
frozen-policy loader. Candidate identity and snapshot identity must match the
renewed complete-stack baseline.

## A-K Sequence

### A: Recommendation Contract

The engine recursively inventories the actual `RecommendationReport` dataclass
and every nested dataclass. Each field records its type, enum domain,
required/null status, producer, source hash, point-in-time source, policy
dependency, serialization behavior, and historical ambiguity.

### B: Input Sufficiency

Every DSI-003 economic candidate is checked against the required input
inventory. Missing candles, policies, metadata, or historical semantics remain
missing. RAW and ADJUSTED arms are never substituted for each other.

### C: Exact Object Recovery

The DSI-002C2 output payload is retained as an authoritative historical
recommendation summary. It is not mislabelled as a full
`RecommendationReport`, so it is not independently admission eligible.

### D-E: Reconstruction and Parity

BEL has a complete signed DSI-002A input snapshot and governed source lineage.
The real recommendation and institutional engines reconstruct it twice.
Admission requires:

- deterministic canonical serialization;
- exact recommendation summary parity;
- exact full-object fingerprint parity under the DSI-002 hash contract;
- exact institutional candidate, base, stress, optimizer, terminal, and
  allocation parity.

No other DSI-003 candidate currently has sufficient frozen inputs.

### F-G: Population and Complete Stack

The admitted population is reconciled against all 1,331 DSI-003 economic
candidates. Every exclusion remains in the ledger. The admitted object runs
through all six canonical complete-stack stages exactly once.

### H-I: DSI-002 Transfer and Outcomes

The accepted DSI-002 gate-isolation engine is reused directly. DSI-004 does not
fork a simplified counterfactual evaluator. Single-condition arms, exact
subset search, downstream transitions, and comparability rows retain the
original DSI-002 semantics.

No unchanged-policy shadow trade formed. Opportunity cost, avoided-loss
benefit, and net gate value therefore remain `UNKNOWN`.

### J-K: Interpretation and Certification

One admitted candidate supports mechanical transferability only. It does not
support statistical, economic, causal, or policy conclusions.

## Readiness

The accepted empirical result is:

- A: `READY_FOR_GOVERNED_RECOMMENDATION_REHYDRATION`;
- B: `READY_WITH_PARTIAL_INPUT_COVERAGE`;
- C: `BLOCKED_BY_NO_VALID_SERIALISED_OBJECTS`;
- D: `READY_WITH_PARTIAL_CANONICAL_RECONSTRUCTION`;
- E: `READY_WITH_RESTRICTED_RECONSTRUCTION_METHODS`;
- F: `READY_WITH_PARTIAL_REHYDRATED_POPULATION`;
- G: `READY_WITH_PARTIAL_COMPLETE_STACK_BASELINE`;
- H: `READY_WITH_ZERO_SHADOW_APPROVALS`;
- I: `READY_WITH_NO_COMPARABLE_SHADOW_OUTCOMES`;
- J: `READY_FOR_MECHANICAL_TRANSFERABILITY_ONLY`;
- K: `READY_FOR_MECHANICAL_REHYDRATION_RESEARCH_ONLY`.

The blocked C state is preserved. DSI-004 does not weaken exact-object
requirements merely to increase population size.

## CLI

Run:

```bash
poetry run python -m alpha benchmark \
  decision-superiority-historical-recommendation-rehydration \
  --dsi003-certificate <PATH> \
  --output <PATH>
```

Verify:

```bash
poetry run python -m alpha benchmark \
  decision-superiority-historical-recommendation-rehydration-verify \
  --certificate <OUTPUT>/dsi004_rehydration_certificate.json \
  --require-ready
```

## Artifacts

The bundle contains one certificate, twenty-eight CSV ledgers, and one
executive report. Every support artifact is hash-bound and path constrained.
Equivalent runs at the same source commit are byte-identical.

Portable evidence contains no machine-local absolute paths. The public
validator also checks the bound implementation source hashes and rejects
source drift.

## Known Limitations

- Only BEL has complete frozen recommendation inputs.
- No full historical serialised `RecommendationReport` was recovered.
- The DSI-002C2 payload is an authoritative summary, not a full object.
- The other 1,330 economic candidates cannot be reconstructed without
  inventing fields or using present-day defaults.
- No shadow approval, allocation, entry, trade, or comparable outcome exists.
- Statistical and economic gate-value claims are prohibited.

## Governance

No production recommendation, approval, allocation, execution, learning,
replay, or policy path is modified. Rehydrated objects are research artifacts
only and are never written to production ledgers.

`PRODUCTION_INFLUENCE=false`.
