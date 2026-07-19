# Alpha Pine Parity Audit

## v1.0.1 Compilation Hardening

Compilation hardening changes identifier safety, source formatting, validation,
and Pine-compatible declaration syntax only. It does not change component
weights, thresholds, setup formulas, trade-plan formulas, or parity classes.

All six generated variants are self-contained and are regenerated from their
checked-in source files. Manual edits to generated files are prohibited.

See `PINE_V6_COMPILATION_HARDENING.md` and
`TRADINGVIEW_MANUAL_COMPILATION_CHECKLIST.md` for the generation and verification
boundary.

## Audit Scope

This audit was performed against executable Project Alpha source, not historic
design notes. The machine-readable record is
`tradingview/manifests/alpha_pine_parity_manifest.json`; it contains every
required field for each component:

`component_name`, `python_source_file`, `python_symbol_or_class`, `input_data`,
`formula_or_semantics`, `lookback`, `warmup_requirement`, `weight`,
`thresholds`, `missing_data_behavior`, `pine_reproducibility`, `parity_class`,
`known_difference`, and `test_method`.

## Canonical Sources Audited

| Concern | Python source | Canonical symbol |
|---|---|---|
| Price, volume, structure, breakout | `alpha/recommendation_intelligence/engines.py` | `PriceVolumeSignalEngine` |
| Candles | same | `CandlePatternEngine` |
| Setup detection and lifecycle | same | `TradeSetupEngine` |
| Evidence score and weights | same | `EvidenceScoringEngine` |
| Recommendation score and verdict | same | `RecommendationScoringEngine` |
| Entry, stop, targets, invalidation | same | `TradePlanIntelligenceEngine` and `TradeSetupEngine` |
| Strategy playbooks | same | `TradeStrategyType` helpers |
| Institutional approval | `alpha/decision_intelligence/engine.py` | `InstitutionalDecisionEngine` |
| Forward outcome ordering | `alpha/performance_intelligence/outcomes.py` | `RecommendationOutcomeEvaluator` |

The source commit is recorded by the generated manifest. The package version is
read from `alpha.version.__version__`.

## Detailed Mapping

### Price Structure

- Inputs: OHLCV, support/resistance, and available 20/50/200 DMA/EMA values.
- Formula: structure 28%, trend 20%, momentum 15%, breakout defence 12%,
  support 10%, close strength 8%, volatility 7%.
- Lookback/warmup: two bars minimum; up to 200 for complete trend evidence.
- Thresholds: HH/HL 0.90, LH/LL 0.10, below support 0.15.
- Missing data: Alpha scores available averages only; Pine does the same.
- Parity: `SEMANTICALLY_EQUIVALENT`.
- Difference: chart-reconstructed levels replace some supplied Alpha levels.
- Test: rising, falling, sideways, support, and breakout fixtures.

### Volume Confirmation

- Inputs: OHLCV and 20-bar average volume.
- Formula: expansion 20%, dry-up 12%, accumulation 24%, inverse distribution
  16%, breakout confirmation 20%, inverse selloff 8%.
- Thresholds: strong breakout volume 1.5x; heavy breakdown volume 1.3x;
  high-volume down day 1.5x.
- Missing data: neutral ratio until the moving average is available.
- Weight: 17%.
- Parity: `EXACT` formula, subject to provider volume differences.
- Test: volume breakout, weak breakout, and selloff fixtures.

### Trend Alignment

- Inputs: Alpha price trend and upstream indicator score.
- Formula: 70% price trend plus 30% indicator trend.
- Lookback/warmup: 20/50/200 bars.
- Weight: 15%.
- Parity: `APPROXIMATED` because Pine has no upstream Alpha indicator score;
  chart DMA/EMA alignment is used and disclosed.

### Relative Strength

- Inputs: normalized Alpha benchmark-relative-strength evidence.
- Weight: 13%; bullish at 0.60, bearish at 0.40.
- Parity: `APPROXIMATED`.
- Difference: Pine uses a configurable 63-bar asset return minus benchmark
  return proxy. This is not Alpha's upstream normalization.

### Retracement Quality

- Inputs: swing range, DMA/Fibonacci support, dry-up, and selloff evidence.
- Formula adjustment: +0.10 healthy, -0.25 bad, +0.10 dry-up, -0.30 selloff.
- Thresholds: 38.2-50% healthy, below 61.8% score cap, below 78.6% sell cap.
- Lookback: up to 60 bars; weight 10%.
- Parity: `SEMANTICALLY_EQUIVALENT` because chart-confirmed swings replace
  Alpha's supplied point-in-time swing levels.

### Candle Confirmation

- Inputs: one to three OHLCV bars plus price/volume context.
- Patterns: engulfing, hammer, shooting star, morning/evening star, doji,
  inside/outside bar, pin bar, and strong close.
- Thresholds: doji body at most 10% of range; volume confirmation at 1.2x.
- Weight: 8%.
- Parity: `EXACT` formulas, subject to source candle adjustments.

### Breakout and Setup

- Canonical automatic setups: Bull Flag, EMA Pullback, VCP, Momentum
  Continuation, Failed Breakout, Trend Failure, and related hard bearish forms.
- Bull Flag requires uptrend, constructive structure, healthy retracement,
  dry-up at least 0.55, and retracement score at least 0.60.
- VCP requires resistance, controlled volatility, dry-up at least 0.60, and
  price score at least 0.55.
- Weight: 7%; typical lookback 20-60 bars.
- Parity: `SEMANTICALLY_EQUIVALENT` for canonical automatic setups.
- `APPROXIMATED`: Cup & Handle and Flat Base. Python accepts those as upstream
  hints but does not currently detect them independently.

### Market Regime

- Inputs: Alpha point-in-time market state, setup type, and bearish count.
- Adjustment: bull +2 or breakout +4; sideways -2 or breakout -4; bear -8
  minus bearish evidence count.
- Weight: 5%.
- Parity: `UNAVAILABLE_IN_TRADINGVIEW`.
- Optional benchmark mode is explicitly `APPROXIMATED`, not a substitute for
  Alpha breadth, universe, or persisted market-state evidence.

### Sector Context

- Inputs: point-in-time membership and cross-sectional sector strength.
- Weight: 3%.
- Parity: `UNAVAILABLE_IN_TRADINGVIEW`; no hidden proxy is substituted.

### Risk and Volatility

- Inputs: 14-bar simple mean of true range and candidate risk quality.
- Thresholds: current range/ATR above 2.5 is expanding risk; below 0.8 is
  controlled; scores are 0.25, 0.80, and 0.60 otherwise.
- Weight: 2%.
- Parity: `SEMANTICALLY_EQUIVALENT`; candidate-level risk evidence is replaced
  with visible chart stop quality.

### Verdict Mapping

- `STRONG_BUY`: score at least 90.
- `BUY`: score at least 75.
- `WATCHLIST`: score at least 60.
- `AVOID`: score at least 40.
- `SELL`: score below 40.
- Parity: `EXACT` boundaries. The requested Pine display maps WATCHLIST to HOLD
  and uses SELL/STRONG_SELL for its single-verdict vocabulary.

### Trade Plan and Outcomes

- Entry trigger: resistance/prior high and setup-specific confirmation.
- Stop: support, swing, DMA, and ATR-buffered structure, always below long entry.
- Targets: 2R, 3R, and max(4R, 3 ATR extension).
- Trail: 2 ATR below highest close after entry.
- 20-DMA: trend/invalidation reference, not an active stop by default.
- Forward ordering: entry on high touch, stop first on a same-bar conflict,
  trailing stop, highest target, then 20-bar expiry.
- Parity: `SEMANTICALLY_EQUIVALENT`; TradingView's fill engine remains
  authoritative for its own test.

### Institutional and Cross-Sectional Systems

Static Pine-compatible filters include score, reward/risk, stop distance, setup
state, and volume confirmation. The following are unavailable or excluded:

- full-market and simultaneous candidate ranking;
- point-in-time historical universe and survivorship-safe screening;
- point-in-time sector ranking and proprietary breadth;
- Market DNA and IRD;
- adaptive ledger calibration, posterior probability, and expectancy;
- liquidity/capacity and live-feed health;
- institutional portfolio allocation, exposure, and correlation constraints;
- corporate-action evidence lineage and warehouse confidence.

Parity is `UNAVAILABLE_IN_TRADINGVIEW` or `EXCLUDED`. No hidden proxy replaces
these systems, and no result may be labelled `ALPHA_EXACT`.
