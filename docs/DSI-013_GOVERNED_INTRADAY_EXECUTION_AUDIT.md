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

## Source certification before strategy research

No entry mechanism may be evaluated until the intraday source layer certifies:

1. point-in-time identity-to-instrument-key resolution;
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

The first implementation slice provides:

- typed source, policy, mechanism, bar, readiness, and result contracts;
- stable candidate-window request identities;
- Upstox V3 URL construction;
- injectable HTTPS transport;
- immutable raw-response caching without credential persistence;
- response parsing with IST and request-window enforcement;
- bar-level OHLCV validation;
- regular-session count and boundary validation;
- deterministic unit tests for URL identity, parsing, cache reuse, secret
  exclusion, complete-session admission, and fail-closed defects.

The daily/intraday reconciliation layer, point-in-time instrument resolver,
entry mechanisms, paired attribution, portfolio replay, artifact certificate,
CLI runner, and real-data acceptance remain to be implemented. Until the source
certificate is ready, no intraday performance conclusion is permitted.

The source slice must pass locked Ruff, Ruff format, strict MyPy, focused unit
tests, and the complete repository CI shards before work advances to identity
resolution or strategy execution. The clean source-only validation boundary is
exactly the two DSI-013 modules, this document, and the focused source test file.
