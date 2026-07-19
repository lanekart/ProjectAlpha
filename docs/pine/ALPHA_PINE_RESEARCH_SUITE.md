# Alpha Pine Research Suite v1.0

## Purpose

The suite independently tests the Pine-compatible part of Project Alpha on
TradingView chart data. It does not replace Alpha's Python logic, Market Truth
Engine, replay, approval policy, adaptive learning, or portfolio controls.

## Architecture

1. `FrameworkManifestBuilder` extracts weights, verdict boundaries, setup
   aliases, strategy enums, and approval constants from executable Alpha code.
2. The parity audit classifies each component as `EXACT`,
   `SEMANTICALLY_EQUIVALENT`, `APPROXIMATED`,
   `UNAVAILABLE_IN_TRADINGVIEW`, or `EXCLUDED`.
3. Modular Pine v6 libraries document reusable formulas.
4. Six self-contained scripts permit TradingView use without publishing private
   libraries.
5. The exporter applies explicit research configuration and writes deterministic
   source under `tradingview/generated/`.
6. Static validation checks version headers, declarations, permanent warnings,
   required controls, prohibited future-data constructs, and generated values.

## Scripts

| Script | Purpose |
|---|---|
| Alpha 01 Component Audit | Inspect raw, normalized, and weighted evidence without trading. |
| Alpha 02 Setup Comparator | Compare Bull Flag, EMA Pullback, VCP, bearish failures, and disclosed approximations. |
| Alpha 03 Institutional Composite | Test the Pine-compatible decision, setup, trade-plan, and static approval sequence. |
| Alpha 04 Multi-Timeframe Composite | Test completed monthly, weekly, daily, 4H, and optional 1H evidence. |
| Alpha 05 Risk and Exit Lab | Compare stop, target, partial exit, trail, structure, and time-exit models. |
| Alpha 06 Strategy Combination Lab | Manually test enabled component and setup combinations. |

The Component Dashboard and Trade Plan Overlay are indicators and do not place
Strategy Tester orders.

## Canonical Weights

The exporter reads the weights from
`EvidenceScoringEngine._weights()` at manifest-generation time:

| Evidence | Weight |
|---|---:|
| Price structure | 20% |
| Volume confirmation | 17% |
| Trend alignment | 15% |
| Relative strength | 13% |
| Retracement quality | 10% |
| Candle confirmation | 8% |
| Breakout/setup | 7% |
| Market regime | 5% |
| Sector | 3% |
| Risk/volatility | 2% |

## Research Configurations

| Profile | Chart | Trend | Structural | Confirmation | Intended horizon |
|---|---|---|---|---|---|
| Positional | Daily | Weekly | Monthly | Daily/4H | Weeks to months |
| Swing | 4H or Daily | Daily/Weekly | Weekly/Monthly | 4H | Days to weeks |
| Short swing | 1H or 4H | Daily | Weekly | 1H | One to several days |

No intraday-scalping strategy is introduced.

## Commands

```text
poetry run python -m alpha pine audit
poetry run python -m alpha pine manifest
poetry run python -m alpha pine export --strategy institutional-composite
poetry run python -m alpha pine export --strategy multi-timeframe-composite --timeframe D --confirmation-timeframe 240
poetry run python -m alpha pine validate
poetry run python -m alpha pine report
```

Supported exporter strategy IDs are `component-audit`, `setup-comparator`,
`institutional-composite`, `multi-timeframe-composite`, `risk-exit-lab`, and
`combination-lab`.

## Status Contract

```text
PRODUCTION_INFLUENCE=false
BROKER_ORDERING=false
AUTONOMOUS_DEPLOYMENT=false
TRADINGVIEW_EXECUTION=false
NO_LOOKAHEAD=true
NO_REPAINTING=true
ALPHA_SOURCE_OF_TRUTH=true
TRADINGVIEW_IS_SECONDARY_VALIDATOR=true
```

Successful local tests may establish `PYTHON_GENERATION_TESTS=PASS` and
`PINE_STATIC_VALIDATION=PASS`. Only a person compiling each script in
TradingView may advance
`TRADINGVIEW_MANUAL_COMPILATION=USER_VERIFICATION_REQUIRED` and
`TRADINGVIEW_RUNTIME_SMOKE_TEST=USER_VERIFICATION_REQUIRED`.
