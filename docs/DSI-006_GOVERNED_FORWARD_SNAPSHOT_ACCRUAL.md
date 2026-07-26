# DSI-006 Governed Forward Snapshot Accrual

## Purpose

DSI-006 operationalises the DSI-005 recommendation snapshot contract inside an
explicit research-only forward-shadow workflow. It captures future canonical
recommendation runs, retains their complete inputs and decisions, appends later
lifecycle evidence without mutation, and verifies that packages can be replayed
without mutable runtime state.

DSI-006 does not backfill the 1,330 historical candidates excluded by DSI-005.
It starts a prospective evidence population at the activation boundary.

`PRODUCTION_INFLUENCE=false`

## Prerequisite

DSI-006 is based on merge commit `411cb9f`, which merged the certified DSI-005
source and acceptance commits into `feature/recovery-foundation-v1`.

DSI-006 validates:

1. the complete DSI-005 certificate and its 27 bound artifacts;
2. the DSI-005 certified source commit in current ancestry;
3. each historical implementation hash against bytes read from the certified
   source commit.

The ordinary DSI-005 verifier remains strict against the current checkout.
DSI-006 uses historical commit validation because it legitimately extends the
shared application capture seam.

## Operating Modes

- `CAPTURE_DISABLED`
- `GOVERNED_FORWARD_SHADOW_CAPTURE`
- `SNAPSHOT_PACKAGE_VERIFY`
- `SNAPSHOT_REPLAY`
- `OUTCOME_EVENT_ACCRUAL`
- `DSI_COUNTERFACTUAL_REPLAY`
- `POPULATION_READINESS_AUDIT`

Default application execution remains `CAPTURE_DISABLED`.

Forward capture requires an explicit operator command, signed DSI-005
certificate, Historical Truth database, immutable snapshot root, and dedicated
research output root. Enabling application capture without an injected recorder
still fails closed.

## Capture Path

The operator reads one point-in-time Historical Truth session and executes:

```text
Historical Truth session
-> canonical DailyMarketReport analysis
-> IntelligenceInputBuilder
-> RecommendationEngine
-> InstitutionalDecisionEngine
-> portfolio construction
-> DSI-005 snapshot recorder
-> DSI-006 content-addressed repository
```

Every recommendation produced by the unchanged engine is retained. There is no
favourable-verdict filter. A genuine zero-recommendation session is valid and
is recorded separately from unavailable, inadmissible, or failed sessions.

## Repository Contract

The research repository contains:

```text
repository/
  packages/<package_sha256>.json
  events/<event_id>.json
  snapshot_index.csv
```

Packages and events are immutable. The index is deterministically rebuildable
from package bytes.

Publication uses:

1. package validation;
2. secret scan;
3. disk and permission preflight;
4. isolated temporary write;
5. canonical-byte and hash validation;
6. atomic publication;
7. deterministic index reconstruction.

An identical capture is an idempotent success. A different package for the same
candidate arm fails closed. No existing evidence is overwritten.

## Candidate Identity

DSI-006 retains:

- session ID;
- economic candidate ID;
- candidate-arm ID;
- recommendation-object ID;
- complete-stack baseline ID;
- recorded-plan ID;
- outcome-stream ID;
- package SHA-256.

Economic identity is based on security, decision date, and policy identity.
Price arm and recommendation fingerprint remain in candidate-arm identity.
RAW and ADJUSTED arms can therefore remain distinct packages while sharing one
economic candidate. Independent population counts use economic candidates,
never candidate-arm rows.

## Outcome Events

Lifecycle evidence is stored as one immutable, content-addressed event file.
Supported events include:

- plan recorded;
- entry pending;
- entry not triggered;
- entry triggered;
- position open;
- outcome pending;
- outcome completed;
- outcome invalidated;
- outcome correction recorded.

Corrections reference the superseded event. They do not delete or rewrite it.
Events before the recommendation date, unknown candidate arms, missing
predecessors, and conflicting terminal outcomes fail closed.

Initial capture appends only evidence available at that time: plan identity and
entry-pending state. It does not infer entry or attach future outcomes.

## Replay and DSI-002

Package replay reconstructs typed inputs and verifies:

- input parity;
- recommendation parity;
- fingerprint parity;
- institutional stage-trace parity;
- terminal decision parity;
- allocation parity;
- plan identity parity.

DSI-006 does not manufacture a DSI-002 condition-pass request. A package can be
fully replayable while remaining semantically ineligible for DSI-002
counterfactual evaluation. Mechanical snapshot replay is reported separately
from gate-value research. Economic gate value requires mature comparable
outcomes.

## Operational Controls

The implementation covers:

- stale temporary-file recovery;
- interrupted-write isolation;
- deterministic index rebuild;
- package and event inventory verification;
- duplicate-run idempotency;
- conflicting-run rejection;
- disk-space and permission preflight;
- unsupported schema rejection;
- source and policy lineage;
- secret scanning;
- path-traversal rejection;
- immutable retention;
- derived schema migration without original-byte deletion.

Governed packages are never deleted automatically.

## CLI

Capture one session:

```bash
poetry run python -m alpha benchmark \
  decision-superiority-forward-snapshot-capture \
  --session-date YYYY-MM-DD \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --historical-truth-snapshots <SNAPSHOT_ROOT> \
  --dsi005-certificate <DSI005_CERTIFICATE> \
  --output <RESEARCH_CAPTURE_ROOT>
```

Validate certification:

```bash
poetry run python -m alpha benchmark \
  decision-superiority-forward-snapshot-verify \
  --certificate <DSI006_CERTIFICATE> \
  --require-ready
```

Verify repository:

```bash
poetry run python -m alpha benchmark \
  decision-superiority-forward-repository-verify \
  --repository <RESEARCH_CAPTURE_ROOT>/repository
```

Append a sourced lifecycle event:

```bash
poetry run python -m alpha benchmark \
  decision-superiority-forward-outcome-event \
  --repository <REPOSITORY> \
  --candidate-arm-id <ID> \
  --event-type OUTCOME_PENDING \
  --observation-date YYYY-MM-DD \
  --effective-date YYYY-MM-DD \
  --source-lineage <SOURCE> \
  --source-hash <SHA256>
```

## Artifacts and Certification

DSI-006 emits deterministic source, activation, session, package, identity,
pairing, plan, event, replay, DSI-002 transfer, resilience, retention, safety,
population, concentration, readiness, reconciliation, and non-vacuity evidence.

The certificate binds all support artifacts, source hashes, the DSI-005
boundary, A-I readiness, governance flags, report hash, implementation defects,
point-in-time leakage, and unexplained divergence.

## Research Interpretation

A valid first run may contain:

- zero new candidates;
- no entries;
- no completed outcomes;
- no DSI-002 shadow approvals.

That result can establish operational readiness but cannot establish
profitability, economic superiority, gate value, or causal effects.

Research readiness increases only through independent prospective candidates
and genuinely matured comparable outcomes. Pending evidence is never treated as
zero or final.

## Governance

No recommendation, scoring, gate, approval, portfolio, execution, learning, or
live policy changed. Capture remains disabled by default. Production snapshot
writes remain disabled. The repository is research-only.

`PRODUCTION_INFLUENCE=false`
