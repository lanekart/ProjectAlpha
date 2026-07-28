# DSI-010B3 Full Residual Corporate-Action Closure

DSI-010B3 is a research-only closure contract. It compares the signed DSI-010B2
factor-validation population with a rebuilt governed result and attributes only
actual transitions out of unresolved states.

The contract preserves four separate questions:

1. Were official terms parsed and retained?
2. Is the event identity and reference price certified?
3. Does a complete, point-in-time candle context exist?
4. Does the factor pass the unchanged continuity contract?

A case is not resolved merely because a new label exists. It leaves the work
queue only when its validation outcome leaves the unresolved set. Remaining
cases name the missing action-session candle, ATR history, reference/identity
evidence, superseding official terms, or engine repair.

## Readiness

`ADJUSTED_REPLAY_CERTIFIED` requires:

- no unresolved factor-validation outcome;
- no unresolved admission interval;
- no mixed-price-basis interval;
- identical baseline and final event populations.

Otherwise the result is fail-closed. Missing securities or periods are never
silently excluded.

## Command

```text
poetry run python -m alpha historical-truth \
  residual-corporate-action-closure-certify \
  --baseline-b1c-output <SIGNED_DSI010B2_B1C> \
  --final-b1c-output <DSI010B3_B1C> \
  --baseline-htr010b-output <SIGNED_DSI010B2_HTR010B> \
  --final-htr010b-output <DSI010B3_HTR010B> \
  --official-source-root <IMMUTABLE_ADDITIONAL_OFFICIAL_SOURCES> \
  --output <OUTPUT>
```

The command emits deterministic JSON, CSV, Markdown, and a hash-bound readiness
certificate. Raw candles, factors, and upstream evidence are read-only.

`FULL_BENCHMARK_REPLAYS=0`

`PRODUCTION_INFLUENCE=false`
