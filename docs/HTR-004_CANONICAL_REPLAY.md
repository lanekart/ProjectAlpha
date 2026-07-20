# HTR-004 — Canonical Historical Replay

## Institutional objective

HTR-004 makes recovered security identity and corporate-action truth an enforced
boundary before historical prices reach replay, signal, decision, or portfolio
consumers. It does not change strategy policy, approval thresholds, or live
execution behavior.

## Canonical flow

1. Raw OHLCV enters through a governed frame adapter.
2. HTR-002 resolves the point-in-time security identity and canonical symbol.
3. HTR-003 applies only corporate actions announced and effective by replay
   `as_of`.
4. Unresolved identities and material corporate actions fail closed.
5. Raw and adjusted values, cumulative factors, event lineage, recovery version,
   and immutable hashes are preserved.
6. The consumer guard re-verifies the complete frame immediately before a
   downstream service can use it.

## Replay bar contract

`CanonicalReplayBar` preserves:

- stable `security_id`;
- raw and canonical symbols;
- `trading_date` and replay `as_of`;
- raw and adjusted OHLCV;
- cumulative price and volume factors;
- applied and unresolved corporate-action identifiers;
- replay readiness status; and
- recovery version.

A bar with unresolved material actions is `QUARANTINED` and cannot produce a
canonical signal or decision.

## Consumer frame contract

A consumer-ready pandas frame carries the adjusted OHLCV in the standard
`open`, `high`, `low`, `close`, and `volume` columns. It also carries explicit
raw and exact adjusted columns plus:

- `security_id`;
- `raw_symbol` and `canonical_symbol`;
- `replay_as_of`;
- cumulative adjustment factors;
- applied and unresolved event IDs;
- `replay_status`;
- `recovery_version`;
- `canonical_snapshot_sha256`;
- `canonical_frame_sha256`;
- `canonical_replay_enforced`; and
- `replay_contract_version`.

`CanonicalReplayConsumerGuard` verifies the contract, OHLCV invariants,
identity uniqueness, readiness, frame digest, and snapshot metadata immediately
before consumption. A mutated or partially governed frame is rejected.

## Immutable artifacts

### Snapshot repository

For each replay `as_of` date:

```text
<root>/<YYYY-MM-DD>/replay.jsonl
<root>/<YYYY-MM-DD>/manifest.json
```

The manifest records the date, bar count, recovery version, and snapshot SHA-256.
Writes are idempotent and conflicting rewrites are rejected.

### Decision-parity diagnostics

```text
replay_parity.csv
changed_decisions.csv
replay_parity_audit.json
replay_parity.md
```

These artifacts quantify adjusted-price, changed-signal, and changed-decision
impact without changing policy.

### Consumer attestations

```text
canonical_replay_attestations.json
canonical_replay_attestations.csv
canonical_replay_attestations.md
```

Each attestation records the trading date, replay `as_of`, consumed security IDs,
canonical symbols, snapshot digest, exact consumer-frame digest, recovery
versions, applied events, contract version, and a deterministic attestation
SHA-256.

## Governed backtest entrypoint

`GovernedReplayBacktestService` wraps the existing backtest application service.
Raw or persisted market frames are canonicalized before feature generation,
signals, orders, trades, or portfolio valuation. The returned
`GovernedReplayBacktestRun` couples the ordinary backtest result to every replay
attestation consumed during the run.

## CLI

Verify an immutable replay snapshot:

```bash
poetry run python -m alpha.recovery verify-snapshot \
  --root artifacts/canonical-replay \
  --as-of 2025-01-15 \
  --output artifacts/canonical-replay-verification
```

List available snapshots:

```bash
poetry run python -m alpha.recovery list-snapshots \
  --root artifacts/canonical-replay
```

`verify-snapshot` re-reads and hashes the stored bars, verifies the manifest, and
can emit `snapshot_verification.json` and `snapshot_verification.md`.

## No-lookahead and fail-closed rules

- A bar after replay `as_of` is rejected.
- A corporate action is invisible before its announcement and effective dates.
- Historical symbols resolve only inside their governed effective periods.
- Ambiguous or absent identities are rejected.
- Unresolved material actions quarantine affected prior bars.
- Quarantined bars cannot emit canonical evaluations.
- Canonical consumer frames are re-attested immediately before use.
- Snapshot or frame digest mismatches are rejected.

## Validation gates

```bash
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy alpha
poetry run pytest -q
```

HTR-004 is complete only after the full repository passes all four gates.
