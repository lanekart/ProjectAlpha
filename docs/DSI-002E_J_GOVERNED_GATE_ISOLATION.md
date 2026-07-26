# DSI-002E-J Governed Gate-Isolation Research

## Purpose

DSI-002E-J measures the frozen mechanical consequences of passing exact observed
institutional gate conditions. It is diagnostic research only.

`PRODUCTION_INFLUENCE=false`.

The package does not change recommendation, institutional, stress, trade-plan,
allocation, portfolio, entry, execution, outcome, default, or live policy.

## Signed Boundary

The engine requires and validates the ready DSI-002D1, B2, C2, and D2
certificates. Candidate identity, snapshot identity, source commit, certificate
hashes, support artifacts, and D1-to-B2/C2/D2 bindings must agree.

The accepted candidate is the signed RAW BEL observation from 2026-07-26. The
ADJUSTED arm is unavailable and remains `UNKNOWN`; it is never inferred.

## E: Single-Condition Shadow Arms

The institutional engine exposes a governed research-only condition-pass seam.
The default evaluator calls the same implementation with an empty pass set, so
ordinary behavior is unchanged.

Each observed failed condition receives a stable identity:

```text
INSTITUTIONAL_BASE.<REASON_CODE>.<ORDINAL>
```

An eligible arm:

1. preserves the recommendation and candidate;
2. passes exactly one observed condition result;
3. invokes base, stress, and trade-plan stages once;
4. records every output;
5. reruns to prove determinism.

Composite evaluator rows remain
`MULTI_CONDITION_EVALUATOR_NOT_ISOLATABLE`. They are not silently passed.

## F: Exact Remediation Search

Eligible conditions are ordered by stable condition identity. The engine tests
every subset in cardinality order, including the empty baseline subset. It records
the state hash and target result for every subset.

Inclusion-minimal and minimum-cardinality sets are derived separately. No greedy
result is accepted as proof. A governed search limit emits
`SEARCH_SPACE_EXHAUSTED` and blocks minimality claims.

The primary target is terminal institutional approval after unchanged stress and
trade-plan evaluation.

## G: Downstream Funnel

Valid arms retain the authoritative institutional trace and existing allocation
result. The funnel records:

- institutional base decision;
- stress decision;
- trade-plan decision;
- terminal institutional state;
- allocation;
- portfolio eligibility;
- entry readiness;
- entry occurrence;
- trade formation.

No gate arm directly edits entry, stop, target, allocation, portfolio state, or
outcome. Zero approvals or trades are valid when every arm reconciles.

## H: Outcome Comparability

Outcomes are attached only after a shadow trade forms and exact plan, entry,
execution, identity, price-arm, and point-in-time lineage can be established.

When no unchanged-policy trade forms, comparability is
`COUNTERFACTUAL_PATH_UNOBSERVABLE`. Returns, expectancy, opportunity cost,
avoided-loss benefit, net gate value, and benchmark-relative value remain
`UNKNOWN`, never zero.

## I: Statistical Interpretation

The package separates arm rows from independent analytic units. Multiple arms for
one BEL candidate are dependent and do not create multiple economic samples.

Implemented controls include:

- Wilson intervals for valid proportions;
- deterministic bootstrap intervals where outcomes exist;
- Jaccard and conditional overlap;
- candidate and outcome reuse diagnostics;
- Benjamini-Hochberg and Holm adjustments for valid hypothesis families;
- explicit invalid-test and insufficient-sample states;
- deterministic robustness views.

No p-value is produced for the one-candidate dependent arm population.

## J: Reconciliation and Certification

The final package reconciles the signed candidate through failed conditions,
eligibility, single arms, exact subset search, sufficient sets, downstream
transitions, trades, comparable outcomes, and interpretation. Zero populations
carry explicit reason codes.

The final and E-I internal certificates bind:

- source commit and signed candidate;
- support artifact hashes;
- internal readiness;
- source and evaluator inventory;
- slice certificate hashes;
- population reconciliation;
- executive report;
- the exact complete set of false governance flags.

Public validation rejects missing or true governance flags, altered artifacts,
path traversal, certificate substitution, report-hash mismatch, and non-ready
evidence when ready status is required.

## CLI

```bash
poetry run python -m alpha benchmark \
  decision-superiority-gate-isolation-shadow \
  --dsi002d1-certificate <PATH> \
  --dsi002b2-certificate <PATH> \
  --dsi002c2-certificate <PATH> \
  --dsi002d2-certificate <PATH> \
  --output <PATH>
```

Verification:

```bash
poetry run python -m alpha benchmark \
  decision-superiority-gate-isolation-shadow-verify \
  --certificate <PATH> \
  --require-ready
```

## Interpretation Boundary

An internal shadow arm may mechanically reach an `ACCEPT` state. That is not a
real approval, policy recommendation, production mutation, or causal claim.
`COUNTERFACTUAL_APPROVAL_CLAIMED` therefore remains false.

With one signed candidate, the package can certify mechanics but cannot establish
reliable gate economic value. Larger signed populations and comparable completed
outcomes are required before inferential conclusions are supportable.
