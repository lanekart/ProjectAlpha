# Point-in-Time Breakout Reference Reconstruction

## Boundary

This dataset answers a narrow historical question: what resistance evidence could
Alpha genuinely have known when each replay candidate was observed?

It does not evaluate outcomes, profitability, AUC, thresholds, weights, approval
rules, entry timing, stops, or targets. `PRODUCTION_INFLUENCE=false` throughout.

## Authoritative Inputs

- Candidates: the immutable raw candidate rows in the Candidate Learning ledger.
- OHLCV: Alpha's canonical `data/ingestion.duckdb:daily_prices` table.
- Sessions: distinct persisted trading dates in that canonical price store. This
  handles weekends, exchange holidays, and missing calendar dates without pretending
  they were flat sessions.
- Identity: the date-specific membership row in the point-in-time analytical store.
  Current-only symbol mappings are not substituted when that evidence is absent.
- Adjustment mode: `RAW_UNADJUSTED` for both reference formation and candidate-price
  comparison.

The canonical price store does not retain a per-row upstream archive identifier.
Provenance therefore names the canonical Project Alpha dataset and hashes the exact
bar series used. It does not claim a more specific provider lineage than the stored
data can prove.

## Cutoff Rules

| Decision semantics | Last daily bar allowed |
| --- | --- |
| Proven pre-market | Previous completed session |
| Proven intraday | Previous completed session |
| Proven after close | Candidate session close |
| Legacy date-only | Previous completed session |
| Non-trading observation date | Previous completed session |
| Unproven date-only under strict ambiguity policy | No reconstruction |

Legacy replay `created_at` values at midnight are deterministic run markers, not
proof of an executable decision timestamp. The repository-wide default therefore
uses the conservative previous-session rule. Tests retain an explicit ambiguity mode
for datasets where even that policy is not accepted.

The final allowed bar is the observation bar. Resistance formation uses only earlier
bars. A right-confirmed swing is valid only when every confirmation bar precedes the
observation bar. Retest evidence is emitted only when the breakout and retest sequence
already exists inside the allowed source window.

## Reference Methods

`PRIOR_SWING_HIGH` finds the latest pivot with fixed left/right confirmation windows.
`RANGE_RESISTANCE` requires multiple highs within a deterministic tolerance cluster.
`ROLLING_HIGH` records the highest completed high in the configured prior window.

Different methods produce different immutable records. They are not collapsed into a
single generic level and are not ranked by future outcomes.

## Status Meaning

- `READY`: complete provenance and a formed reference.
- `REFERENCE_NOT_FORMED`: complete valid history, but no qualifying reference.
- `INSUFFICIENT_LOOKBACK` or `MISSING_BARS`: history cannot support reconstruction.
- `AMBIGUOUS_DECISION_CUTOFF`: the information boundary cannot be proven or safely
  constrained.
- `SYMBOL_IDENTITY_UNRESOLVED`: no date-specific instrument identity is available.
- `CORPORATE_ACTION_AMBIGUITY`: a material discontinuity lacks authoritative action
  evidence.
- `PROVENANCE_INCOMPLETE`: evidence exists but cannot be marked valid because lineage
  is incomplete.

Only `READY` supplies a resistance level to Breakout Intelligence.
`REFERENCE_NOT_FORMED` remains a valid historical finding but does not invent a level.
Every other status leaves the classifier at `INSUFFICIENT_EVIDENCE`.

## Corporate Actions

The store's raw representation is preserved. A known pre-candidate split inside the
lookback trims the input to post-split raw bars; sufficient post-split lookback is
still required. A post-candidate action is excluded. Cash-dividend events do not
trigger synthetic adjustment. Mixed adjustment modes are rejected.

This policy avoids the subtler look-ahead problem of applying today's retrospectively
adjusted history to an old decision without recording that limitation.

## Persistence And Determinism

The sidecar path is `.alpha/breakout_reference_dataset_v1.json`, configurable through
`ALPHA_BREAKOUT_REFERENCE_DATASET`. Original replay rows are never modified.

The stable key contains dataset version, candidate ID, reference method, and algorithm
version. Identical records are reused. A new algorithm version coexists with the old
record; `--force` can replace a conflicting same-version record only after integrity
checks pass. It never bypasses leakage or hash validation.

The semantic hash covers identity, cutoff, evidence, source checksums, configuration,
algorithm version, warnings, and exclusions. Operational timestamps are deliberately
non-semantic.

## Readiness Standard

`BREAKOUT_HISTORY_READY` requires at least 95% historically usable candidates,
complete provenance, zero material cutoff/identity blockers, and passing determinism,
leakage, series, and lineage audits. `REFERENCE_NOT_FORMED` counts as usable history
because it is a valid negative finding.

Conclusion precedence is cutoff ambiguity, symbol identity, provenance, major source
gaps, partial readiness, then not ready. Some reconstructable rows are never enough to
declare the dataset ready.

## Commands

```bash
poetry run python -m alpha replay breakout-reference-reconstruct --dry-run
poetry run python -m alpha replay breakout-reference-reconstruct
poetry run python -m alpha replay breakout-reference-readiness
poetry run python -m alpha replay breakout-reference-integrity
poetry run python -m alpha replay breakout-reference-provenance
poetry run python -m alpha replay breakout-reference-sample --limit 20
```

Filters include `--from-date`, `--to-date`, `--symbol`, `--candidate-id`,
`--replay-run-id`, `--reference-method`, `--minimum-lookback`, and `--limit` where
applicable. Text, deterministic JSON, and deterministic CSV exports are supported.

No performance conclusion is permitted until a separate outcome-validation milestone
uses this completed point-in-time evidence without changing its historical content.
