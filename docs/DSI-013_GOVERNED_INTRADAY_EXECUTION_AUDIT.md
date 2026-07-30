# DSI-013 — Governed Daily-Selection Intraday-Execution Audit

## Objective

DSI-013 tests whether point-in-time intraday information improves execution for a
frozen daily Alpha candidate population. It does not search the full intraday
market and does not alter daily candidate selection, ranking, setup, regime,
stop, target, holding-period, or portfolio-contention policy.

The primary question is:

> Does a pre-registered five-minute entry mechanism improve net paired
> expectancy, drawdown, entry efficiency, and portfolio performance versus the
> existing next-session-open control after realistic costs?

## Data source and evidence status

The initial source is Upstox Historical Candle Data V3. It is broker-sourced
research evidence and must not be represented as official exchange historical
truth.

The frozen source boundary is:

- unit: `minutes`;
- interval: `5`;
- source availability boundary: January 2022 onward;
- governed comparison start: `2022-01-01`;
- governed comparison end: `2025-12-24`;
- timezone: `Asia/Kolkata`;
- regular NSE cash session: `09:15` through `15:30`;
- candidate-specific instrument and date windows only.

One-minute bars are not a discovery surface in DSI-013. They may be introduced
later only as pre-certified evidence for resolving within-bar stop/target
ambiguity for already shortlisted five-minute mechanisms.

## Credential handling

The Upstox access token is supplied by the operator at runtime. It is never
written to source manifests, cache files, certificates, reports, or logs.

The source cache stores:

- a credential-free request descriptor;
- the encoded request URL;
- retrieval timestamp;
- raw response bytes;
- raw response SHA-256;
- source and interval identity.

A partial cache, request mismatch, hash mismatch, or suspected secret leakage
fails closed.

## Identity contract

Instrument resolution requires an exact governed identity in the form
`nse:isin:<12-character ISIN>`. The source record must independently report:

- exchange `NSE`;
- segment `NSE_EQ`;
- the exact same ISIN;
- canonical instrument key `NSE_EQ|<ISIN>`;
- the source-reported cash-series type, such as `EQ` or `BE`.

BSE records, symbol-only matches, fuzzy names, alternate ISINs, derivatives,
and non-canonical instrument keys are not admissible. Multiple distinct
canonical keys for one ISIN are an identity blocker. Multiple NSE cash-series
records may share one canonical key; all observed source types are retained in
the identity ledger, and `EQ` is preferred only as the deterministic
representative row when it exists. A `BE`-only exact canonical record remains
admissible. Historical availability must still be proved by non-empty,
date-aligned candles that reconcile to the governed daily source.

## Source certification before strategy research

No entry mechanism may be evaluated until the intraday source layer certifies:

1. exact identity-to-instrument-key resolution;
2. five-minute timestamp alignment;
3. timezone and regular-session boundaries;
4. unique instrument/timestamp rows;
5. positive and internally possible OHLC values;
6. non-negative volume and open interest;
7. expected regular-session bar count and first/last bar boundaries;
8. daily-versus-intraday OHLCV reconciliation;
9. immutable raw-response and source-manifest lineage;
10. zero unresolved implementation defects.

Missing bars are not forward-filled. Symbol-only identity assumptions are not
permitted. Special sessions require separately governed session evidence rather
than being forced into the regular-session contract.

Source reconciliation is performed against the governed `RAW` daily candle,
not the adjusted strategy candle. All 75 regular-session five-minute bars must
be present. Open, high, low, and close must match within `₹0.011`; volume must
match exactly. The governed corporate-action factor path will be applied later
to admitted intraday bars so strategy replay and daily Alpha signals share one
price basis. A mismatch is retained as a source blocker rather than repaired by
vendor assumptions or inferred factors.

## Frozen candidate population

The acquisition planner reads only the hash-validated DSI-009 entry-fill
artifact. It admits successful `ENTRY-INCUMBENT-NEXT-OPEN` rows whose exact
entry session falls inside the 2022–2025 overlap and whose identity is an exact
NSE ISIN.

All control prices, stops, targets, folds, regimes, holding periods, signal
strengths, and liquidity evidence remain frozen. Identical identity/session
requests are downloaded once while every contributing signal remains separately
represented. Conflicting duplicate signals, missing required fields,
non-forward entry dates, non-ISIN identities, and out-of-window rows fail closed
or remain explicit exclusions.

## Pre-registered mechanisms

Exactly one control and four challengers are permitted:

- `ENTRY-NEXT-SESSION-OPEN`;
- `ENTRY-ORB15-BREAKOUT`;
- `ENTRY-VWAP-RECLAIM`;
- `ENTRY-FIRST-PULLBACK`;
- `ENTRY-CLOSING-CONTINUATION`.

There is no parameter tournament in DSI-013. A candidate that does not trigger a
challenger is `NOT_ENTERED`; it cannot silently inherit the control fill.

All challenger fills occur at the next five-minute bar open. Same-bar trigger
fills, fills at VWAP, fills at candle extremes, averaging down, repeated trigger
attempts, and same-day re-entry are prohibited.

## Execution and cost boundary

The audit must include:

- explicit brokerage and statutory charges;
- base spread/slippage assumptions;
- a pre-registered adverse-cost stress not used for selection;
- five-minute bar-volume and daily-ADV participation limits;
- conservative stop-first treatment when stop and target are both touched in
  the same five-minute bar unless separately certified one-minute evidence can
  determine order;
- unchanged daily portfolio and exit policy.

## Acceptance boundary

A challenger may be labelled
`READY_WITH_INTRADAY_EXECUTION_IMPROVEMENT_DESCRIPTIVE_ONLY` only when all
pre-registered source, return, drawdown, Calmar, profit-factor, cost-stress,
capacity, multiple-testing, chronological-fold, concentration, and deterministic
artifact gates pass.

Even then:

- `VALIDATED_STRATEGY=false`;
- `INTRADAY_LIVE_TRADING_ENABLED=false`;
- `AUTOMATIC_STRATEGY_PROMOTION_ENABLED=false`;
- `RECOMMENDATION_INFLUENCE=false`;
- `PORTFOLIO_POLICY_INFLUENCE=false`;
- `EXECUTION_INFLUENCE=false`;
- `LEARNING_MUTATION_ENABLED=false`;
- `PRODUCTION_INFLUENCE=false`.

## Current implementation boundary

The implemented source boundary now provides:

- typed source, policy, mechanism, bar, readiness, and result contracts;
- stable candidate-window request identities;
- Upstox V3 URL construction;
- injectable HTTPS transport;
- immutable raw-response caching without credential persistence;
- response parsing with IST and request-window enforcement;
- bar-level OHLCV validation;
- regular-session count and boundary validation;
- exact governed-ISIN resolution to canonical Upstox NSE cash-market keys;
- source cash-series retention;
- identity- and instrument-isolated session aggregation;
- governed raw-daily OHLCV reconciliation;
- signed DSI-009 candidate population and bounded request planning;
- fail-closed source-readiness certification with explicit precedence;
- nine deterministic support CSVs, an executive report, certificate payload
  digest, SHA-256 manifest, tamper detection, secret-leak checks, local-path
  checks, and optional ready-state enforcement;
- deterministic tests covering source parsing, cache integrity, identity and
  cash-series resolution, request planning, source readiness, blocked readiness,
  artifact round trips, and tamper detection.

The credential-safe local runner, governed raw-daily warehouse loader,
corporate-action transformation, entry mechanisms, paired attribution,
portfolio replay, final strategy certificate, and real-data acceptance remain
to be implemented. Until the source certificate is ready against genuine local
evidence, no intraday performance conclusion is permitted.

Every implementation slice must pass locked Ruff, Ruff format, strict MyPy,
focused unit tests, and all repository CI shards before work advances. The clean
source-validation boundary currently contains six DSI-013 modules, this
document, and four focused test files.
