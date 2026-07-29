# DSI-011 Conversational Research Lab

## Purpose

The Alpha Research Lab compiles bounded natural-language strategy requests into
immutable `ResearchExperimentSpec` objects. It never executes prose directly.
Registry validation is authoritative and no path accepts arbitrary Python, SQL,
shell commands, generated source, or unregistered formulas.

`PRODUCTION_INFLUENCE=false`. Experiments cannot promote a strategy or alter
recommendation, approval, allocation, execution, learning, or live policy.

## Launch

```bash
poetry run python -m alpha research data-contract
poetry run python -m alpha research chat
poetry run python -m alpha research ask \
  "Backtest RSI above 50, enter next session open and hold for 20 sessions."
```

Use `--database` when Historical Truth is outside the repository worktree and
`--root` to choose the immutable `.alpha/research` registry location.

## Certification Boundary

DSI-011 requests begin no earlier than 2016-01-01. The actual first session is
the first session on or after that date for which the complete adjusted-data
contract passes. "Latest", "to date", and similar phrases mean the latest fully
certified Historical Truth session, not the computer date.

Execution fails closed unless all of these are zero or reconciled:

- unresolved security identities;
- unresolved series intervals;
- unresolved corporate-action factors;
- mixed price-basis intervals;
- invalid adjusted OHLC rows;
- duplicate identity-session rows;
- missing adjusted security-session rows.

Alpha-signal and hybrid strategies also require frozen historical
recommendations. The lab never regenerates a past recommendation using current
code and presents it as contemporaneous evidence.

DSI-011A separates recorded historical signals, retrospective frozen replays,
and walk-forward replays. Each experiment records the selected source, and a
short partial replay cannot satisfy a full-range source contract. See
`DSI-011A_POST2016_EXECUTION.md` for the executable data and signal boundary.

## Canonical Engine

The runner extends `alpha/backtest` and sends every entry and exit fill through
`BrokerSimulator`. It uses whole shares, deterministic equal-weight sizing,
cash reconciliation, one open position per governed security identity, and an
immutable trade/equity/rejection ledger. The synthetic
`alpha.analysis.backtest` return proxy is not used.

## Typed Strategy

Every specification records:

- experiment and parent IDs;
- session ID;
- Alpha-signal, pure-technical, or hybrid mode;
- exact certified start and end sessions;
- point-in-time universe;
- typed entry expression tree;
- entry execution and expiry;
- stop, target, trailing, and holding rules;
- capital, sizing, and maximum positions;
- adjusted price basis;
- transaction-cost and slippage models;
- same-session ambiguity policy;
- parameter sweeps and output requirements.

Default capital is INR 1 crore. Maximum positions is 10. Sizing is equal weight.
Prices are fully adjusted. Fractional shares are disabled. Transaction costs
and slippage are `NONE`. Results are gross of all implementation frictions.

## Indicators

The versioned registry defines SMA, EMA, RSI, ATR, ADX, directional indicators,
MACD components, rate of change, stochastic, Williams %R, Bollinger bands and
width, historical volatility, volume averages and ratios, lookback highs and
lows, moving-average distance, 52-week distances, swing highs, and swing lows.

Every definition records source fields, default period, warm-up, output type,
close-time availability, adjusted price basis, and implementation version.
The executor rejects any registered definition that does not have a permanent
point-in-time calculation.

## Candle Rules

The registry contains deterministic single- and multi-session patterns,
including bullish/bearish candle, doji, hammer, engulfing, inside/outside bar,
marubozu, spinning top, wick rules, inside-bar breakout, and close in the top
20% of range. Pattern evidence is calculated from completed daily candles.
Close-derived patterns cannot execute at that candle's open.

## Logic

The typed expression tree supports `ALL`, `ANY`, `NOT`, and `N_OF_M`. It does
not use `eval`. Materially ambiguous phrases fail with unresolved fields and
registered alternatives.

## Entry, Stop, and Target Rules

Entry definitions include next valid open/close, delayed open, breakout above
signal high, percentage retracement, expiry, and revalidation. Stop definitions
include fixed percent, ATR, signal low, swing/support structure,
`STOP-STRUCTURAL-10D`, and percentage trailing. Multiple stops require an
explicit tighter, wider, first-triggered, or staged policy.

Targets include fixed percent, R multiple, ATR multiple, and staged target plus
runner. The canonical runner supports fixed stops/targets, staged trailing
activation, maximum holding exits, and forced boundary exits. Rules not yet
represented by the canonical broker fail validation instead of being simulated
approximately.

## Daily Fill Rules

- Gap below a stop: fill at the session open.
- Intraday stop touch: fill at the stop.
- Gap above a target: fill at the session open.
- Intraday target touch: fill at the target.
- Stop and target touched in one daily candle: record
  `INTRADAY_PATH_AMBIGUOUS`.

The default is `ASSUME_STOP_FIRST`. `ASSUME_TARGET_FIRST` is available only as
an explicit research alternative. Every report includes the ambiguous count.

## Sessions and Editing

Runs live under `.alpha/research/runs/ARL-NNNNNN`; sessions live under
`.alpha/research/sessions`; `registry.jsonl` is append-only. Every modification
creates a child experiment and a field-level diff. Earlier experiments are
never overwritten.

```bash
poetry run python -m alpha research show ARL-000001
poetry run python -m alpha research strategy ARL-000001
poetry run python -m alpha research trades ARL-000001
poetry run python -m alpha research explain ARL-000001
poetry run python -m alpha research rerun ARL-000001
poetry run python -m alpha research compare ARL-000001 ARL-000002
poetry run python -m alpha research sessions
```

## Sweeps

Sweeps create one deterministic child per combination. The default maximum is
100 children. The compiler reports the planned count and rejects larger
searches. Search limits do not select parameters based on future performance.

## Artifacts

Completed runs contain the specification, request, diff, data contract, run
manifest, summary, trades, equity and drawdown curves, annual/monthly returns,
breakdowns, ambiguous sessions, rejected entries, a standalone HTML report,
and a hash-bound certificate. Blocked runs retain the same input contracts and
their exact blockers.

## Limitations

DSI-011 uses daily OHLCV. It cannot establish intraday sequencing, queue
priority, spread, slippage, market impact, Level 2/3 order-book outcomes, or
unsupported historical fundamentals. Results exclude brokerage, STT, exchange
charges, GST, stamp duty, bid-ask spread, slippage, and market impact.

`RESULTS_ARE_GROSS_OF_COSTS=true`.
