# Autonomous Decision and Evidence Loop

## Purpose

The Autonomous Decision and Evidence Loop is an at-least-once, scheduler-driven
research operation. It generates fresh Alpha decisions, freezes every outcome,
maintains policy-isolated shadow lifecycles, marks all markable decisions daily,
publishes matured trade outcomes to the Closed Learning Loop, and builds separate
`FORWARD_OBSERVED` Market DNA cohorts.

It never places broker orders, deploys capital, mutates production policy, or promotes
a research hypothesis automatically.

`PRODUCTION_INFLUENCE=false`.

## Operating Model

An external scheduler invokes:

```text
poetry run python -m alpha autonomous tick
```

The command may be invoked repeatedly after market close. Internal schedule slots use
deterministic IDs, so duplicate invocations return the completed result without
duplicating decisions or evidence. A practical operating schedule is every 15 minutes
after the configured close; the internal registry decides whether a slot is due.

The default bootstrap creates:

- universe `CANONICAL_ALPHA_UNIVERSE` from Alpha's canonical runtime population;
- schedule `WEEKDAY_POST_CLOSE` at 15:45 Asia/Kolkata, Monday through Friday;
- isolated policy cohort `APPROVAL_POLICY_V1`;
- 20-bar decision markout horizon;
- maximum data age of three calendar days;
- virtual capital of INR 1,000,000.

Bootstrap is configuration only. It does not create a background process or execute a
decision run.

## Registered Universes

Canonical and explicit-symbol universes are immutable, versioned records. Explicit
universes constrain the analysis rows before recommendation and allocation engines run;
they are not post-processing filters.

```text
poetry run python -m alpha autonomous register-universe \
  --id LIQUID_LARGE_CAPS \
  --source EXPLICIT_SYMBOLS \
  --symbols RELIANCE,TCS,INFY \
  --version universe-v1
```

Schedules reference an existing universe and freeze their policy cohort, local trigger,
freshness requirement, capital assumption, and markout horizon.

```text
poetry run python -m alpha autonomous register-schedule \
  --id LARGE_CAP_POST_CLOSE \
  --universe LIQUID_LARGE_CAPS \
  --time 15:45 \
  --timezone Asia/Kolkata \
  --weekdays 0,1,2,3,4 \
  --policy APPROVAL_POLICY_V1 \
  --markout-horizon-bars 20
```

Changing a universe or schedule requires a new ID or version. Existing definitions are
never edited in place.

## Run Stages

Every deterministic schedule slot has an append-only, hash-chained stage journal:

1. `STARTED`
2. `DECISIONS_FROZEN`
3. `SHADOW_UPDATED`
4. `MARKED_TO_MARKET`
5. `OUTCOMES_PUBLISHED`
6. `DNA_UPDATED`
7. `DRIFT_EVALUATED`
8. `HYPOTHESES_ROUTED`
9. `COMPLETED`

Unexpected exceptions append `FAILED`. A later invocation resumes from completed
checkpoints. All underlying stores are idempotent, and the loop uses an operating lock
plus atomic file replacement to prevent concurrent scheduler workers from interleaving
writes.

## Frozen Decisions

Every recommendation is permanently classified as one of:

- `APPROVED_TRADE`
- `NO_TRADE`
- `RISK_BLOCKED`
- `REJECTED`
- `DATA_BLOCKED`

The artifact preserves schedule, universe, recommendation ID, timestamp, observed
market date, symbol, verdict, reference price, approved virtual deployment, policy
version, exact reasons, point-in-time feature snapshot, evidence hashes, and an
immutable artifact hash.

If the runtime produces no recommendation, the loop still freezes a universe-level
`DATA_BLOCKED`/no-trade artifact. Stale, future-dated, non-live, explicitly incomplete,
or price-unavailable inputs cannot create a shadow trade.

## Two Outcome Contracts

### Shadow Trade Outcomes

Approved BUY decisions use the existing Forward Validation engine. Entry, stop,
targets, trailing stop, invalidation, expiry, cash, positions, and portfolio valuations
remain append-only and policy isolated. These actual simulated lifecycle outcomes are
published to CLL only with their true state: pending, active, exited, expired, or not
triggered.

### Decision Markouts

Every decision with a valid reference price receives one immutable close/high/low mark
for every available later bar. The markout resolves only after the frozen horizon. It
measures what happened after the decision and is explicitly not realized shadow P/L.

Decision markouts make no-trade, risk-blocked, and rejected opportunities measurable.
Unavailable prices remain unresolved and are counted as missing data; they are not
silently inferred.

## Forward-Observed DNA

Matured decision markouts update five exclusive evidence cohorts:

- `FORWARD_OBSERVED_WINNERS`
- `FORWARD_OBSERVED_LOSERS`
- `FORWARD_OBSERVED_CATASTROPHIC_LOSSES`
- `FORWARD_OBSERVED_MISSED_OPPORTUNITIES`
- `FORWARD_OBSERVED_REJECTED_OPPORTUNITIES`

Flat and unresolved decisions are not forced into a DNA cohort. The registry accepts
only the typed `FORWARD_OBSERVED` evidence class. Reconstructed Market DNA remains in
its existing, separate registry.

Current fixed predicates are:

- approved trade return above 1%: winner;
- approved trade return at or below -1%: loser;
- approved trade return at or below -25%: catastrophic loss;
- no-trade or risk-blocked return above 1%: missed opportunity;
- rejected return above 1%: rejected opportunity.

These are version-one research definitions, not production thresholds.

## Drift and Learning

The existing CLL measures confidence calibration, recommendation-score and feature
drift, sector mix, timing, precision, expectancy, and strategy health. The autonomous
loop adds DNA-cohort prevalence drift using guarded chronological segments.

Unresolved outcomes may contribute to input-distribution monitoring but never to
observed success, realized expectancy, calibration success, or final DNA cohorts.

## Governed Hypothesis Pipeline

Evidence-linked improvement hypotheses enter this fixed state machine:

```text
STRATEGY_LAB_PENDING
  -> WALK_FORWARD_PENDING
  -> SHADOW_VALIDATION_PENDING
  -> HUMAN_APPROVAL_REQUIRED
  -> HUMAN_APPROVED
```

Any failed validation produces `REJECTED`. A gate cannot be skipped. Each pass requires
an immutable external evidence artifact, explanation, timestamp, and actor. The
autonomous actor is prohibited from recording human approval.

`HUMAN_APPROVED` is still only a research-governance record. This package has no API
for changing recommendation thresholds, approval policy, allocation, or execution.

## Commands

```text
poetry run python -m alpha autonomous bootstrap
poetry run python -m alpha autonomous register-universe ...
poetry run python -m alpha autonomous register-schedule ...
poetry run python -m alpha autonomous tick
poetry run python -m alpha autonomous run --schedule WEEKDAY_POST_CLOSE
poetry run python -m alpha autonomous status
poetry run python -m alpha autonomous journal
poetry run python -m alpha autonomous dna
poetry run python -m alpha autonomous drift
poetry run python -m alpha autonomous hypotheses
poetry run python -m alpha autonomous validate ...
poetry run python -m alpha autonomous approve ...
poetry run python -m alpha autonomous export --json loop.json --csv loop.csv
```

## Failure Behavior

| Condition | Behavior |
|---|---|
| Missing or stale decision data | Freeze `DATA_BLOCKED`; create no new shadow trade |
| Runtime/provider exception | Freeze reason and continue maintenance of prior evidence |
| Missing later bars | Leave decision unresolved; report missing data |
| Duplicate scheduler call | Return existing completed slot; insert nothing |
| Crash after append | Resume from immutable checkpoint; append methods deduplicate |
| Registry hash conflict | Stop the run and append a fail-closed event |
| Reconstructed DNA presented to forward registry | Reject the payload |
| Validation gate skipped | Reject the transition |
| Autonomous human approval | Reject the transition |

## Persistence and Observability

Default registry:

```text
.alpha/autonomous_loop/registry.json
```

It can be overridden with `ALPHA_AUTONOMOUS_LOOP_REGISTRY` or CLI path options. JSON
and CSV exports retain schedules, hash-chained run events, decisions, marks,
resolutions, forward DNA, drift assessments, hypotheses, and validation events.

IRD registers `autonomous-decision-evidence-loop` and reports completed runs, frozen
decisions, resolved decisions, forward DNA maturity, and the unresolved-evidence
bottleneck.

## Production Boundary

The package composes existing analysis and research systems. It does not import broker
order APIs, expose an execution command, write production policy, or deploy capital.

- Broker orders: disabled
- Automatic capital deployment: disabled
- Automatic policy mutation: disabled
- Automatic hypothesis promotion: disabled
- Production influence: false

