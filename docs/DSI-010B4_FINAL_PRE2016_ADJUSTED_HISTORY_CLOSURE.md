# DSI-010B4 — Final Pre-2016 Adjusted-History Closure

## Purpose

DSI-010B4 repairs the shared action-session selection defect found after
DSI-010B3 and certifies the remaining evidence boundary for the 2005–2015
adjusted-history dataset.

The work is research-only. It does not run a benchmark replay, change a
corporate-action factor from market-price behaviour, exclude a security or
period, or influence production.

## Corrected Action-Session Contract

The old implementation selected the market's first session on or after an
event date and then looked for the affected security only on that date. This
incorrectly rejected thinly traded or temporarily inactive securities.

The corrected contract searches chronologically for the first governed candle
for the event security and series. A candle is eligible only through:

1. an exact event-ISIN match;
2. a certified, effective-dated predecessor/successor ISIN transition; or
3. a missing ISIN supported by the permanent dated identity bridge.

The search ends at the first qualifying candle, the next material corporate
action, a governed identity boundary, official termination, or the end of
certified data. Dividends do not truncate a multiplicative-action search.

No arbitrary calendar-day limit is used. Explicit ISIN mismatches remain
rejected unless official transition evidence governs the exact date.

## Additional Shared Repairs

DSI-010B4 also:

- wires official ISIN and symbol transitions into the normal continuity build;
- preserves exact official symbol-change chains without symbol-only matching;
- calculates composite bonus-and-split factors from official terms;
- distinguishes exact official factors observed across stale,
  non-contemporaneous action windows from transformation defects;
- keeps rights reference-price certification separate from continuity
  confirmation; and
- preserves one governed candle population across downstream validation stages.

The official factor is never changed to improve observed continuity.

## Empirical Result

The DSI-010B3 residual population contained 172 events. DSI-010B4 resolved 106:

- 62 through security-specific action-session selection;
- 44 through official identity-transition wiring.

The final validation outcomes are:

| Outcome | Count |
| --- | ---: |
| `FACTOR_CONFIRMED_CORRECT_MARKET_GAP` | 631 |
| `FACTOR_INSUFFICIENT_EVIDENCE` | 41 |
| `FACTOR_REQUIRES_REFERENCE_PRICE` | 24 |
| `FACTOR_NON_MULTIPLICATIVE` | 8 |
| `FACTOR_CONFLICTING_OFFICIAL_EVIDENCE` | 1 |
| `IMPLEMENTATION_DEFECT` | 0 |

The 66 remaining cases require:

| Missing governed evidence | Count |
| --- | ---: |
| Fourteen governed pre-event bars | 31 |
| First governed action-session candle | 10 |
| Governed reference-price identity | 12 |
| Complete official equity-rights terms | 11 |
| Official effective-dated ISIN transition | 1 |
| Authoritative superseding official terms | 1 |

These are event-level evidence requirements, not broad diagnostic categories.
The machine-readable blocker ledger records every symbol, event ID, effective
date, and missing fact.

## Named Cases

`MURUDCERA`

The 2010 rights factor is confirmed as
`FACTOR_CONFIRMED_CORRECT_MARKET_GAP`. The complete official TERP contract is
retained. Residual action-session price movement is not misclassified as a
factor-orientation defect.

`TATAPOWER`

The 2011 split is confirmed. The 2014 rights event remains
`FACTOR_REQUIRES_REFERENCE_PRICE`. Existing official documents establish the
rights terms and the later ISIN, but do not establish the exact effective date
of the old-to-new ISIN transition required to govern the reference candle.

`HINDMOTOR`

The 2011 capital-reduction event remains
`FACTOR_CONFLICTING_OFFICIAL_EVIDENCE`. The acquired NSE resumption notice
establishes the new ISIN and resumption date, but does not prove which
conflicting capital-reduction terms supersede the other.

## Adjusted-History Boundary

The governed warehouse contains:

- 383,176 raw candle rows;
- 99,774 adjusted rows; and
- 349 mixed-price-basis intervals.

The raw-candle fingerprint remains:

```text
b63c00beb618a8b67996cdf0050d824b03d13512be6d79d2c8ffc67d73b1b50a
```

The 349 mixed intervals cannot be removed while their contributing factors or
identity contexts remain unresolved. No security-period was excluded to
improve readiness.

Therefore:

```text
ADJUSTED_REPLAY_READY=false
READINESS=RESIDUAL_OFFICIAL_EVIDENCE_REQUIRED
```

## CLI

```bash
poetry run python -m alpha historical-truth \
  final-pre2016-adjusted-history-closure-certify \
  --baseline-b1c-output <DSI-010B3-B1C> \
  --final-b1c-output <DSI-010B4-B1C> \
  --baseline-htr010b-output <DSI-010B3-HTR010B> \
  --final-htr010b-output <DSI-010B4-HTR010B> \
  --dsi010b1-output <DSI-010B1> \
  --output <OUTPUT>
```

The command emits deterministic before/after ledgers, resolution attribution,
remaining blockers, named-case results, the executive report, and the
adjusted-replay readiness certificate.

## Governance

```text
FULL_BENCHMARK_REPLAYS=0
STOP_POLICY_AUTOMATIC_PROMOTION_ENABLED=false
ADJUSTED_REPLAY_READY=false
PRODUCTION_INFLUENCE=false
```

Raw candles, official factors, recommendations, strategies, stops, approvals,
portfolio rules, execution rules, learning policy, and production behaviour
remain unchanged.
