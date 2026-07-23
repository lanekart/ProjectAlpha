# HTR-010B1E Bridge-Aware Admission Reconciliation

HTR-010B1E integrates the corrected HTR-010B1D2 factor dispositions into the governed adjustment-replay admission audit without changing official factors or production policy.

## Purpose

HTR-010B1D2 proved that factor quality and bridge certification are separate decisions. HTR-010B1E therefore:

- overlays B1D2 outcomes by exact canonical event ID;
- rejects duplicate, missing, or unmatched repair lineage;
- admits a factor only when factor quality is confirmed and its bridge is certified;
- keeps confirmed factors on uncertified ISIN or series bridges quarantined;
- validates same-session split and bonus groups using their diagnostic composite outcome;
- removes obsolete implementation-defect, orientation, and unexplained-transformation blockers;
- adds explicit bridge and insufficient-evidence blockers;
- converts every blocked admission interval into an economic quarantine range;
- recomputes quarantine census, economic weight, intervals, lookback safety, coverage, rejected evidence, and readiness;
- executes no benchmark replay.

## Admission semantics

- `ADJUSTED_REPLAY_CERTIFIED_TRADABILITY_PARTIAL`: confirmed factor on a certified stable or governed bridge.
- `BRIDGE_UNCERTIFIED_QUARANTINED`: factor quality is confirmed but the ISIN or series bridge is not certified.
- `INSUFFICIENT_EVIDENCE_QUARANTINED`: factor quality cannot be established from governed candle context.
- `FACTOR_UNKNOWN_QUARANTINED`, `FACTOR_AMBIGUOUS_QUARANTINED`, and identity-transition states retain their prior fail-closed semantics.

A confirmed factor never overrides an uncertified bridge.

## Economic-weight contract

Point evidence is insufficient for bridge risk. HTR-010B1E adds each blocked replay-admission interval to the quarantine census before calculating Tier A candle-row and identity-session weight. Post-event raw segments remain independently usable when their identity and price basis are governed.

## Governance invariants

- raw OHLCV remains immutable;
- official factors remain immutable;
- market-derived factor autocorrection is prohibited;
- mixed price bases remain prohibited;
- uncertified bridges remain excluded;
- no candidate, score, approval, stop, target, or production policy is changed;
- `FULL_BENCHMARK_REPLAYS=0`;
- `PRODUCTION_INFLUENCE=false`.
