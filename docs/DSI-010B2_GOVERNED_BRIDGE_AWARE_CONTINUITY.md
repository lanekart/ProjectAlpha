# DSI-010B2 Governed Bridge-Aware Continuity

## Purpose

DSI-010B2 closes a narrow identity-context defect in factor continuity
validation. DSI-010B1 certified 18 legacy rights reference prices, but the
continuity validator still selected candles only by event ISIN. The relevant
legacy candles preserve a missing ISIN, so the validator could not see them.

This milestone does not infer or backfill candle ISINs. It uses the permanent
DSI-010B1 dated identity bridge to govern each missing-ISIN candle separately.

## Separate Contracts

The implementation keeps four decisions separate:

1. **Reference-price certification** proves that one prior close belongs to the
   governed event identity.
2. **Continuity-context certification** proves that every selected ATR and
   action bar has governed identity and source provenance.
3. **Factor-continuity confirmation** applies the unchanged HTR-010B1B
   continuity thresholds to the governed context.
4. **Replay admission** remains a downstream, fail-closed decision.

A certified reference price does not certify adjacent bars, confirm a factor or
admit an event to replay.

## Candle Identity Hierarchy

A candle can enter a governed continuity context through:

- an exact event ISIN, exact series, valid prices and a source SHA-256; or
- a missing ISIN whose exact date is independently certified by the signed
  DSI-010B1 bridge with matching identity, symbol, series and event ISIN.

A non-empty different ISIN is rejected. Missing source hashes, non-positive
prices, duplicate dates, competing rows, symbol reuse, overlapping identities,
and unresolved symbol or series transitions fail closed.

## ATR and Action Sessions

The existing methodology is unchanged:

- retain at most 15 eligible prior bars;
- calculate ATR from the latest 14;
- require at least two prior bars;
- use no future or post-event bars in ATR;
- do not fill sessions or interpolate prices;
- use the first governed action session on or after the effective date.

Every selected missing-ISIN bar must independently pass the dated bridge. Bar
selection is independent of factor performance.

## Reference Consistency

The immediate prior candle must exactly match the DSI-010B1 factor provenance:

- reference date;
- reference close;
- symbol and series;
- source SHA-256;
- bridge contract ID;
- bridge report hash.

Any disagreement prevents a complete governed context.

## Empirical Result

The signed DSI-010B1 population contains 18 events. The genuine DSI-010B2 run
found:

- complete governed contexts: 18;
- confirmed factors: 17;
- implementation defects: 1 (`MURUDCERA`);
- insufficient contexts: 0;
- conflicting official evidence: 0.

The resulting full validation population is:

- `FACTOR_CONFIRMED_CORRECT_MARKET_GAP`: 252;
- `FACTOR_CONFLICTING_OFFICIAL_EVIDENCE`: 3;
- `FACTOR_INSUFFICIENT_EVIDENCE`: 399;
- `FACTOR_REQUIRES_REFERENCE_PRICE`: 50;
- `IMPLEMENTATION_DEFECT`: 1.

Rights factor states remain exactly 55 certified, 22 provisional and 28
missing terms. DSI-010B2 exposes rather than repairs the MURUDCERA factor
discontinuity.

## Downstream Consistency

HTR-010B1C and HTR-010B1E2 accept the same optional signed context provider.
HTR-010B1D, D1 and D2 retain the upstream governed context ID and bar
population. They cannot replace it with a different ISIN-only population or
override its unresolved outcome.

Legacy callers that do not supply signed bridge inputs retain the original
fail-closed behavior.

## CLI

Bridge-aware B1C:

```text
poetry run python -m alpha historical-truth \
  adjustment-replay-admission-certify \
  --htr009a2-output <SIGNED_HTR009A2> \
  --dsi010b1-output <SIGNED_DSI010B1> \
  [existing options]
```

Final certification:

```text
poetry run python -m alpha historical-truth \
  bridge-aware-continuity-certify \
  --database <DUCKDB> \
  --htr009a2-output <SIGNED_HTR009A2> \
  --htr010a3-output <HTR010A3> \
  --htr010b-output <HTR010B> \
  --htr010b1c-output <BRIDGE_AWARE_B1C> \
  --htr010b1e2-output <BRIDGE_AWARE_B1E2> \
  --dsi010b1-output <SIGNED_DSI010B1> \
  --output <OUTPUT>
```

## Artifacts

The certification emits:

- `bridge_aware_continuity_cases.json` and `.csv`;
- `bridge_aware_continuity_bar_ledger.json`;
- `bridge_aware_continuity_rejections.json`;
- `bridge_aware_continuity_summary.json`;
- `bridge_aware_continuity_source_manifest.json`;
- `bridge_aware_continuity_report.md`;
- `bridge_aware_continuity_certificate.json`.

The bar ledger contains enough price, source, identity-path and bridge
provenance data to reproduce every continuity metric.

## Remaining Blockers

Adjusted replay remains not ready. DSI-010B2 does not close:

- 21 complete-term rights events without a matching official interval;
- one explicit ISIN mismatch;
- 28 rights events with incomplete official terms;
- the wider insufficient-evidence population;
- three conflicting-official-evidence cases;
- the MURUDCERA factor-continuity defect.

No factor, canonical candle, threshold, strategy, gate, portfolio policy,
execution policy or recommendation behavior changed. No benchmark replay ran.

`FULL_BENCHMARK_REPLAYS=0`

`STOP_POLICY_AUTOMATIC_PROMOTION_ENABLED=false`

`PRODUCTION_INFLUENCE=false`
