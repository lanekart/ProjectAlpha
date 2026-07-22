# HTR-010B Complete Corporate-Action and Price-Basis Dataset

## Purpose

HTR-010B builds a candidate-independent corporate-action census and governed
price-basis assessment for the 3,711 Tier A NSE equity identities admitted by
HTR-010A3. It covers 2016-01-01 through the common evidence cutoff of
2026-07-20. It does not change Alpha recommendations, replay, scoring,
approval, stops, allocation, or production policy.

`PRODUCTION_INFLUENCE=false`

## Identity Contract

The HTR-010A3 governed identity is authoritative. Official ISIN is the primary
join key; bounded membership and governed predecessor/successor relationships
remain explicit. Symbol-only joins are prohibited. The output retains source
symbol and series, including legitimate parallel series, but one canonical
identity event cannot create duplicate factors merely because the source
repeats it across applicable series.

Events outside the admitted Tier A identity population are not silently
promoted. Rejected parser evidence remains in the rejected-evidence artifact.
Every canonical event retains its raw official record IDs and source checksum
lineage.

## Event and Duplicate Policy

The governed taxonomy separates splits, bonuses, rights, dividend subtypes,
capital changes, reorganisations, identity transitions, buybacks, partly-paid
events, non-adjusting information events, and unknown actions. Structured NSE
fields and the existing versioned parser are used before controlled
normalisation. Original text and the normalisation reason are always retained.

Repeated records with the same governed identity, effective date, event type,
and official purpose form one canonical event. Parallel-series applicability
is retained. Duplicate raw rows remain in lineage and are never deleted.
Conflicting or insufficient terms remain explicit rather than being guessed.

## Adjustment Policy

The policy version is `HTR-010B-ADJUSTMENT-v1.0.0`.

- Splits, consolidations, bonuses, and supported face-value changes use
  reciprocal price and quantity factors derived from official terms.
- Rights use TERP only when ratio, subscription price, and a governed prior
  close exist. Such factors are provisional because the market reference price
  is not an official action term.
- Ordinary, interim, final, and special dividends are retained but are not
  applied to the price-only technical series in this version. A future
  total-return view must remain separate.
- Mergers, amalgamations, demergers, schemes, and spin-offs are identity or
  non-comparable economic transitions unless official terms establish a valid
  single-factor continuity treatment.
- Unknown, ambiguous, conflicting, invalid, and non-multiplicative factors are
  never represented as zero or one. Cumulative factors become unavailable at
  the first unresolved material boundary.

## Price-Basis Views

Canonical raw OHLCV remains immutable. HTR-010B writes a sidecar DuckDB file in
the output directory. It contains governed diagnostic tables and Tier A
adjusted rows copied from the already-versioned HTR-009B calculation only after
HTR-010A3 identity admission is applied. The canonical warehouse is attached
read-only and fingerprinted before and after the run.

Each Tier A identity receives an interval state such as raw/no-action,
certified backward-adjusted, mixed basis, factor unknown, or identity-transition
boundary. Unknown and mixed intervals are quarantined from certified replay
integration.

Forward adjustment and total-return semantics are defined by the policy but
are not fabricated where governed data is unavailable. Their absence is
reported as a limitation.

## Continuity and Contamination

Material events with adjacent observations are assessed using raw and adjusted
gaps, ATR-normalised gaps, volume change, and false breakout/breakdown risk.
Results distinguish restored continuity, improved continuity, residual market
movement, suspected factor error, missing adjacent observations, and
non-comparable reorganisations. A residual gap is not automatically treated as
an incorrect factor.

The contamination inventory reports dataset-level exposure for ATR, moving
averages, relative strength, retracement, Fibonacci, support/resistance,
returns, and MFE/MAE. It does not join to Alpha candidates.

## Point-in-Time Semantics

Four concepts remain separate:

1. The market cannot know an action before its announcement.
2. Economic continuity starts no earlier than the effective/ex date.
3. A backward research transform may restate earlier prices for continuity.
4. The event itself cannot become a predictive feature before it was known.

Future replay integration should use rolling as-of transforms for signal
formation. Fully backward-adjusted research views may be used for continuity
analysis only under an explicit transformation contract. HTR-010B does not
integrate either view into replay.

## Certification and Readiness

The identity coverage matrix reports source, parser, identity, event-type,
factor, adjusted-row, continuity, and price-basis coverage separately.
`NO_MATERIAL_ACTIONS_FOUND` is assigned only when the yearly official source
slices are present and parsed.

Readiness can be ready, conditionally ready, or not ready. Conditional readiness
permits explicitly quarantined rights factors and non-comparable reorganisations.
It never permits ambiguous identity assignment, applying an unknown factor as
one, future leakage, silent mixed basis, or raw-candle mutation.

## CLI

```bash
poetry run python -m alpha historical-truth complete-corporate-action-dataset \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --root alpha_data \
  --htr010a3-output artifacts/htr010a3_tier_a_foundation_readiness \
  --start 2016-01-01 \
  --end 2026-07-20 \
  --output artifacts/htr010b_complete_corporate_action_dataset \
  --refresh-sources
```

Use `--verify-only` to reuse checksum-verified immutable sources without
network access. Diagnostic filters affect only the displayed selection count;
they never restrict acquisition, normalisation, or certification.

## Artifacts and Limitations

The command writes 36 deterministic JSON, CSV, and Markdown artifacts plus the
sidecar diagnostic database. Large adjusted candle rows stay in the sidecar.
The 2026 report is explicitly year-to-date. Source-file availability does not
prove that the exchange family contains every possible issuer filing or every
historical transition notice. Unknown source semantics and unsupported
economic terms remain unknown.

No benchmark replay is run. No active replay table or production path reads the
new sidecar.
