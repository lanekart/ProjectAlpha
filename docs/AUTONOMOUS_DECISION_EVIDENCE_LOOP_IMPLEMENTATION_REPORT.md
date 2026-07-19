# Autonomous Decision and Evidence Loop Implementation Report

## Scope

Project Alpha now has a scheduler-driven, fail-closed research operating loop under
`alpha/autonomous_loop/`. The loop composes the existing recommendation, forward
validation, Closed Learning Loop, Market DNA, Strategy Lab, walk-forward, and shadow
validation systems without granting any of them new production authority.

`PRODUCTION_INFLUENCE=false`.

## Delivered Behavior

- Immutable, versioned universe and schedule registration.
- Deterministic schedule-slot IDs and idempotent retries.
- Frozen approved, rejected, no-trade, risk-blocked, and data-blocked decisions.
- Policy-isolated forward-validation lifecycles for eligible virtual trades.
- Daily point-in-time marks for every decision with an available reference price.
- Fixed-horizon decision resolution without treating unresolved evidence as final.
- Publication of matured shadow outcomes to the Closed Learning Loop.
- Separate `FORWARD_OBSERVED` DNA cohorts for winners, losers, catastrophic losses,
  missed opportunities, and rejected opportunities.
- Calibration, feature, timing, concept, and forward-DNA drift evaluation.
- Evidence-linked hypotheses with mandatory Strategy Lab, walk-forward, shadow, and
  explicit human-approval gates.
- Append-only, hash-chained run journals; atomic registry writes; and a process lock.
- Deterministic JSON and CSV audit exports.
- Institutional Research Director diagnostic registration.

## Safety Boundaries

- No broker order API is imported or called.
- No command deploys real or unattended capital.
- Production policy is never edited in place.
- Human approval is an immutable research event, not a policy deployment action.
- Forward and reconstructed evidence have different typed stores and cannot be mixed.
- Stale, incomplete, future-dated, unavailable, or non-live decision data freezes a
  `DATA_BLOCKED` artifact and creates no new shadow position.
- Missing future prices leave decisions unresolved and visible as missing data.

## CLI

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

## Isolated Acceptance Run

An isolated non-demo run was executed for the deterministic schedule slot
`2026-07-18T11:00:00+00:00`. NSE archive DNS was unavailable in the restricted test
environment. The loop therefore completed fail-closed with:

```text
Run ID: autonomous-799bc026c9abb75d02c8
Status: FAILED_CLOSED
Decisions Frozen: 1
Decision: DATA_BLOCKED / NO_TRADE
Shadow Events: 0
Daily Marks Inserted: 0
Decisions Resolved: 0
Missing Data: 1
```

Re-executing the identical slot returned `ALREADY_COMPLETED` with unchanged decision,
event, and hypothesis counts. The frozen reason retains the provider failure while the
normal CLI remains concise.

## Tests

The deterministic autonomous-loop test suite covers:

- schedule due-time and stable run-ID generation;
- immutable registry conflict detection;
- deterministic snapshot retry hashes;
- stale-data blocking;
- daily marks and horizon resolution;
- unresolved missing-data behavior;
- all five forward DNA cohorts and reconstructed-evidence rejection;
- guarded DNA drift;
- evidence-linked hypothesis generation;
- validation ordering and autonomous-approval prohibition;
- explicit human approval as research evidence only;
- fail-closed restart idempotency;
- CLI bootstrap, status, and exports;
- IRD plugin discovery and policy isolation.

## Operations

The external scheduler should invoke `autonomous tick` at least once after each
registered close. Repeated invocations are safe. Operators should monitor non-zero
missing-data counts, stale last-completed slots, unresolved-decision growth, failed run
events, and validation queues. Recovery is always a retry of the same schedule slot;
frozen artifacts must never be manually edited or deleted.

## Quality Gates

```text
poetry run pytest
1665 passed in 178.19s

poetry run ruff check .
All checks passed!

poetry run mypy alpha
Success: no issues found in 484 source files

poetry build
Built alpha-1.3.0.dev0.tar.gz
Built alpha-1.3.0.dev0-py3-none-any.whl
```

## Production Influence

Broker orders: disabled. Automatic capital deployment: disabled. Automatic production
policy mutation: disabled. Automatic research promotion: disabled.

`PRODUCTION_INFLUENCE=false`.
