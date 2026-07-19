# Breakout Source-Gap Attribution Audit

## Purpose

The point-in-time breakout reference dataset contains 1,546 candidates. Only 889
records are reconstructable, so 57.50% readiness is not sufficient evidence by
itself. A ready-only performance study can overrepresent recent years, continuing
symbols, particular setups, and candidates for which the repository happened to
retain complete history.

This diagnostic consumes the immutable reconstruction records and repository source
evidence. It does not rebuild a reference, infer a missing bar, or use a later
outcome to repair historical evidence. `PRODUCTION_INFLUENCE` remains `false`.

## Source Inventory Finding

The canonical `daily_prices` store and the raw and extracted NSE archive caches all
begin on 2016-07-08. The caches are lineage for the canonical source, not independent
providers. They therefore cannot supply pre-boundary observations. No authoritative,
effective-dated corporate-action or listing-history dataset is joined to the
reconstruction source path.

The audit queries each record by its historical symbol and the unchanged previous
completed-session cutoff. It records the attempted query, repository-wide source
range, symbol-specific range, candidate-bar availability, normalization decision,
identity evidence, cutoff evidence, and provenance state.

## Gap Causes

Every unavailable record receives one primary cause and zero or more secondary
causes. The cause vocabulary distinguishes:

- archive absence, incomplete archives, partial lookback, and candidate-date absence
- multi-session gaps, invalid OHLCV, duplicates, and session/timezone mismatch
- unresolved identity, symbol changes, listing conflicts, and delisting conflicts
- corporate-action ambiguity and adjustment-mode conflict
- ambiguous decision cutoff, unsupported method, and incomplete provenance
- retrieval errors and implementation paths that failed to reach available evidence
- locally short trading history and a retained unknown fallback

`LEGITIMATELY_INSUFFICIENT_TRADING_HISTORY` may describe the observed local source
range. It becomes `LEGITIMATELY_UNRECOVERABLE` only when an authoritative listing
effective date proves that pre-listing bars cannot exist. A first local bar alone is
not enough; those cases remain `RECOVERY_UNCERTAIN`.

## Primary-Cause Precedence

Precedence is deterministic:

1. explicit source retrieval failure
2. unsupported reference method
3. ambiguous cutoff
4. identity, listing, or delisting failure
5. provenance failure
6. timezone/session or adjustment failure
7. corporate-action ambiguity
8. invalid-series detail, including duplicate-bar detail
9. evidence that an existing fallback, cache, boundary, symbol, or filter path was
   not used correctly
10. status-specific archive absence, incomplete source, missing sessions, or partial
    lookback
11. reconstruction implementation failure
12. unknown fallback

This ordering prevents a lower-level missing-bar symptom from hiding a proven
retrieval, identity, cutoff, or implementation failure. Secondary causes preserve
overlap without double-counting primary-cause totals.

## Source Path Dispositions

The audit keeps four questions separate:

- `TRUE_SOURCE_ABSENCE`: the inventoried repository source does not contain the
  required history.
- `AVAILABLE_SOURCE_NOT_REACHED`: evidence exists in an inventoried path but the
  reconstruction path did not reach it.
- `AVAILABLE_SOURCE_REJECTED_CORRECTLY`: the source was reached and failed an
  existing integrity rule.
- `AVAILABLE_SOURCE_REJECTED_INCORRECTLY`: valid evidence was filtered by an
  implementation path.

Correct rejection is not called recoverable merely to increase readiness.

## Recovery Classes

- `RECOVERABLE_EXISTING_SOURCE`: an existing authoritative repository source can be
  routed through the service.
- `RECOVERABLE_EXISTING_SOURCE_WITH_IDENTITY_REPAIR`: effective-dated identity must
  be repaired first.
- `RECOVERABLE_EXISTING_SOURCE_WITH_NORMALIZATION_REPAIR`: existing data requires a
  deterministic normalization repair without weakening exclusions.
- `RECOVERABLE_EXISTING_SOURCE_WITH_CUTOFF_RESOLUTION`: independent timestamp
  evidence can resolve the cutoff without changing cutoff policy.
- `REQUIRES_NEW_EXTERNAL_SOURCE`: the required OHLCV or corporate-action evidence is
  absent from all existing repository sources.
- `LEGITIMATELY_UNRECOVERABLE`: authoritative evidence proves that history cannot
  exist.
- `RECOVERY_UNCERTAIN`: the repository cannot yet prove either recovery or permanent
  absence.

Projected readiness is a deterministic scenario, not a promise. Only the four
existing-source recovery classes are added to a projection. No recovery is executed
by this milestone.

## Selection-Bias Method

Ready and unavailable candidates are compared using only fields already present at
the decision boundary:

- standardized mean differences for numeric fields
- total-variation distance and largest absolute proportion difference for categorical
  fields
- candidate-level inclusion probability and symbol-level inclusion rates
- symbol concentration using a Herfindahl-Hirschman index
- explicit year, regime, setup, score, breadth, continuity, and provider comparisons

Every comparison reports sample counts. Fields below the configured minimum sample
remain unavailable. Candidate rows are not treated as independent observations;
repeated-symbol concentration is reported explicitly.

Completed-outcome availability, forward return, target hits, and stop hits appear in
a separate post-candidate diagnostic section. They do not participate in cause
attribution, reconstruction, or recovery classification. Outcome divergence alone
does not establish causal selection bias.

The missingness mechanism is a deterministic diagnostic judgement, not a formal
proof. It can be `MCAR_PLAUSIBLE`, `MAR_OBSERVED_STRUCTURE`, `MNAR_RISK`,
`MIXED_MISSINGNESS`, or `INSUFFICIENT_TO_CLASSIFY`. Absence of a large observed
difference is not proof that the ready sample is representative.

## Validation Gate

Breakout performance tuning remains blocked when any of these conditions holds:

- material or severe observed ready-sample bias
- inadequate coverage across years, regimes, or major setup groups
- a material unresolved identity, continuity, or corporate-action population
- source gaps that leave historical periods structurally underrepresented
- insufficient effective sample after symbol concentration is considered

Restricted outcome validation is eligible for a later review only when observed bias
is immaterial, candidate and symbol coverage are adequate across time and regimes,
and reconstruction integrity remains green. This audit does not tune thresholds,
weights, approvals, entries, stops, targets, or production behavior.

## Commands

```bash
poetry run python -m alpha replay breakout-source-gap-audit
poetry run python -m alpha replay breakout-selection-bias
poetry run python -m alpha replay breakout-source-coverage
poetry run python -m alpha replay breakout-recovery-readiness
poetry run python -m alpha replay breakout-gap-sample --limit 30
```

All commands support applicable cause, recovery, provider, symbol, date, year,
minimum-sample, grouping, format, and output options. JSON and CSV exports require an
explicit output path and are sorted deterministically.

Supported groupings are `year`, `symbol`, `sector`, `provider`, `primary-cause`,
`secondary-cause`, `recovery-class`, `market-regime`, `setup-type`,
`entry-timing-state`, and `replay-version`.

External data acquisition is intentionally excluded. The audit reports what a new
source would need to provide but does not select, download, integrate, or license one.

## External Source Evaluation Status

The follow-on authoritative-source evaluation materializes the 608
`REQUIRES_NEW_EXTERNAL_SOURCE` and 49 `RECOVERY_UNCERTAIN` rows as immutable manifest
`breakout_external_source_evaluation_manifest_v1`. It evaluates official NSE,
broker, and serious specialist-vendor documentation while keeping documented claims
separate from observed coverage.

No provider has yet produced an approved observed sample. Exact candidate, symbol,
2016, renamed, delisted, corporate-action, and sufficient-lookback coverage remain
unavailable. Projected readiness and selection-bias reduction are not estimated. The
current evidence supports `MULTI_SOURCE_ARCHITECTURE_REQUIRED` and
`SOURCE_EVIDENCE_INSUFFICIENT`, not provider integration.

See [HISTORICAL_SOURCE_EVALUATION.md](HISTORICAL_SOURCE_EVALUATION.md) for the formal
data contract, official source documents, licensing analysis, deterministic sample,
scorecard, CLI commands, and next evidence gate.
