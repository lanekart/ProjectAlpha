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

## Certified Empirical Result

The clean 2005-2015 rebuild reduced the signed DSI-010B2 residual population
from 453 to 172 cases:

- 313 gross residual cases were closed;
- 32 previously confirmed cases were correctly moved to fail-closed after the
  first-governed-action-session contract rejected later, non-comparable prints;
- 281 cases were closed net;
- 525 factors are confirmed correct market gaps;
- 147 factors retain insufficient candle evidence;
- 24 factors require a governed reference price;
- 8 rights distributions are explicitly non-multiplicative;
- one HINDMOTOR event retains conflicting official evidence;
- zero implementation defects remain;
- zero admission intervals remain unresolved.

The original 28 missing-rights-term population is retained in its own ledger.
Eight equity factors are now certified and confirmed, four events are correctly
classified as non-multiplicative distributions, and 16 remain fail-closed.

The original 21 `NO_MATCHING_OFFICIAL_INTERVAL` cases are also retained
individually. Fourteen are now certified and confirmed; seven still require
governed reference identity evidence.

MURUDCERA is confirmed under the reusable official-term arithmetic and
close-restoration contract. TATAPOWER's 2014 rights event remains blocked
because official documents establish the old and later ISINs but do not yet
certify the effective transition date required by the identity contract.

## Remaining Evidence

The 172 remaining cases require:

- 137 canonical first-action-session candles;
- 10 complete fourteen-bar governed ATR windows;
- 11 complete official equity-rights term sets;
- 12 governed reference-price identity intervals;
- one effective-dated TATAPOWER ISIN transition;
- one authoritative superseding HINDMOTOR capital-reduction term document.

These are evidence absences, not unresolved implementation defects. The
adjusted dataset remains fail-closed with 349 mixed-price-basis intervals.

## Deterministic Artifacts

In addition to the before/after and blocker ledgers, the certificate exports
separate parser, identity-interval, continuity-context, conflict-adjudication,
transformation-repair, original missing-rights-term, original unmatched-
interval, and named-case ledgers in JSON and CSV.

Two clean-root acceptance rebuilds produced byte-identical results for all 161
governed non-database artifacts. DuckDB physical files differ only in storage
layout; all 14 governed tables are logically identical under bidirectional
`EXCEPT ALL`.

DSI-010B2 remains the immutable prior boundary. Its signed 39-case artifacts
and hashes are preserved; its fixed `55/22/28` rights-state assertion is not
weakened to accept the evolved DSI-010B3 population.

`FULL_BENCHMARK_REPLAYS=0`

`PRODUCTION_INFLUENCE=false`
