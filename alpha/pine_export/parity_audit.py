"""Canonical component-to-Pine parity audit."""

from __future__ import annotations

from decimal import Decimal

from alpha.pine_export.models import ComponentParity, ParityClass
from alpha.recommendation_intelligence.engines import EvidenceScoringEngine


def build_parity_audit() -> tuple[ComponentParity, ...]:
    """Build the audited mapping from current executable Alpha sources."""

    weights = EvidenceScoringEngine()._weights()
    components = (
        _component(
            "Price structure",
            "PriceVolumeSignalEngine",
            ("OHLCV", "support", "resistance", "DMA/EMA levels"),
            "Weighted price score: structure 28%, trend 20%, momentum 15%, "
            "breakout defence 12%, support 10%, close strength 8%, volatility 7%.",
            "1-200 bars depending on available moving averages",
            "At least two bars; 200 bars for complete long-term trend",
            weights["price_structure"],
            ("HH/HL=0.90", "LH/LL=0.10", "below support=0.15"),
            ParityClass.SEMANTICALLY_EQUIVALENT,
            "Alpha receives some levels from its data pipeline; Pine reconstructs "
            "levels from the chart symbol.",
        ),
        _component(
            "Volume confirmation",
            "PriceVolumeSignalEngine",
            ("OHLCV", "average volume"),
            "Volume score: expansion 20%, dry-up 12%, accumulation 24%, inverse "
            "distribution 16%, breakout confirmation 20%, inverse selloff 8%.",
            "20 bars by default",
            "20 bars for full average-volume context",
            weights["volume"],
            ("strong breakout volume >=1.5x", "selloff penalty >=0.70"),
            ParityClass.EXACT,
            "Chart volume may differ from Alpha warehouse volume or series history.",
        ),
        _component(
            "Trend alignment",
            "EvidenceScoringEngine._trend_alignment_score",
            ("price trend score", "indicator score", "DMA/EMA 20/50/200"),
            "70% price-derived trend score plus 30% supplied indicator trend score.",
            "20, 50 and 200 bars",
            "200 bars for complete alignment",
            weights["trend"],
            ("bullish >=0.60", "bearish <=0.40"),
            ParityClass.APPROXIMATED,
            "The externally supplied Alpha indicator score is unavailable; Pine uses "
            "the chart-derived DMA/EMA alignment score for both terms.",
        ),
        _component(
            "Relative strength",
            "EvidenceScoringEngine.assess",
            ("candidate benchmark_relative_strength", "optional benchmark symbol"),
            "Alpha consumes a normalized benchmark-relative-strength input.",
            "Provider-defined",
            "Unavailable without benchmark history",
            weights["relative_strength"],
            ("bullish >=0.60", "bearish <=0.40"),
            ParityClass.APPROXIMATED,
            "Pine uses a configurable symbol-return minus benchmark-return proxy; "
            "Alpha's upstream normalization is not reproduced.",
        ),
        _component(
            "Retracement quality",
            "EvidenceScoringEngine._price_volume_retracement_score",
            ("swing range", "DMA support", "Fibonacci", "volume evidence"),
            "Base retracement score receives +0.10 healthy, -0.25 bad, +0.10 "
            "volume dry-up and -0.30 heavy-selloff adjustments.",
            "Up to 60 bars for swings",
            "20 bars for volume context",
            weights["retracement"],
            ("38.2-50%=healthy", "below 61.8%=avoid cap", "below 78.6%=sell cap"),
            ParityClass.SEMANTICALLY_EQUIVALENT,
            "Confirmed chart swings replace Alpha's supplied point-in-time "
            "swing levels.",
        ),
        _component(
            "Candlestick confirmation",
            "CandlePatternEngine",
            ("OHLCV", "support/resistance", "retracement", "volume evidence"),
            "Context-aware engulfing, hammer, shooting-star, star, doji, "
            "inside/outside, "
            "pin and strong-close scoring.",
            "1-3 bars plus support context",
            "3 bars for star patterns",
            weights["candle"],
            ("doji body <=10% range", "volume confirmed >=1.2x"),
            ParityClass.EXACT,
            "Pattern formulas are reproducible; source candle adjustments can differ.",
        ),
        _component(
            "Breakout and setup",
            "TradeSetupEngine",
            ("price-volume assessment", "levels", "candle assessment"),
            "Detect Bull Flag, EMA Pullback, VCP, Momentum Continuation and hard "
            "bearish failures; hinted setup names are separately accepted upstream.",
            "20-60 bars",
            "60 bars for full level context",
            weights["breakout"],
            ("breakout volume >=0.60", "VCP dry-up >=0.60"),
            ParityClass.SEMANTICALLY_EQUIVALENT,
            "Cup & Handle and Flat Base are Pine research approximations because the "
            "current Python engine does not independently detect them.",
        ),
        _component(
            "Market regime",
            "EvidenceScoringEngine._regime_adjustment",
            ("point-in-time market regime", "setup category", "bearish evidence"),
            "Bull +2 or breakout +4; sideways -2 or breakout -4; bear -8 minus "
            "bearish evidence count.",
            "Externally supplied point-in-time state",
            "Unavailable in a single-symbol chart",
            weights["market_regime"],
            ("BULL", "SIDEWAYS", "BEAR"),
            ParityClass.UNAVAILABLE_IN_TRADINGVIEW,
            "An optional benchmark-only proxy is visibly labelled APPROXIMATED and is "
            "not Alpha's point-in-time market-state system.",
        ),
        _component(
            "Sector context",
            "EvidenceScoringEngine.assess",
            ("sector strength score", "point-in-time sector membership"),
            "Consumes Alpha's normalized sector-strength evidence.",
            "Cross-sectional",
            "Unavailable in a single-symbol strategy",
            weights["sector"],
            ("bullish >=0.60", "bearish <=0.40"),
            ParityClass.UNAVAILABLE_IN_TRADINGVIEW,
            "No hidden sector proxy is substituted. A manual neutral input is "
            "explicit.",
        ),
        _component(
            "Risk and volatility",
            "EvidenceScoringEngine._volatility_quality_score",
            ("OHLCV", "14-bar simple ATR", "candidate risk score"),
            "Average candidate risk quality and volatility quality; expanding=0.25, "
            "controlled=0.80, normal=0.60.",
            "15 bars",
            "15 bars for Alpha-compatible simple ATR",
            weights["risk"],
            ("range/ATR >2.5 expanding", "range/ATR <0.8 controlled"),
            ParityClass.SEMANTICALLY_EQUIVALENT,
            "Candidate-level risk quality is unavailable; Pine uses chart stop "
            "quality.",
        ),
        _component(
            "Recommendation verdict",
            "RecommendationScoringEngine._decision",
            ("final score",),
            "STRONG_BUY >=90, BUY >=75, WATCHLIST >=60, AVOID >=40, SELL below 40.",
            "Current bar after component warmup",
            "Maximum enabled component warmup",
            None,
            (">=90 STRONG_BUY", ">=75 BUY", ">=60 WATCHLIST", ">=40 AVOID"),
            ParityClass.EXACT,
            "Pine renders HOLD for WATCHLIST and STRONG_SELL for scores below 40 only "
            "when the requested single-verdict display vocabulary requires it.",
        ),
        _component(
            "Trade-plan construction",
            "TradePlanIntelligenceEngine and TradeSetupEngine",
            ("support", "swing low", "DMA", "ATR", "entry"),
            "Support/swing/DMA anchors, ATR-buffered stop, 2R, 3R and max(4R, 3ATR) "
            "targets; 2x ATR close-watermark trail.",
            "14-60 bars",
            "60 bars for full swing context",
            None,
            ("stop below entry", "target 1=2R", "target 2=3R"),
            ParityClass.SEMANTICALLY_EQUIVALENT,
            "TradingView's order simulator and chart precision can produce "
            "different fills.",
        ),
        _component(
            "Institutional approval",
            "InstitutionalDecisionEngine",
            ("adaptive evidence", "capacity", "portfolio", "live health", "trade plan"),
            "Requires quality verdict, confidence, historical edge, complete "
            "trade plan, "
            "reward/risk, capacity, live health and portfolio suitability.",
            "Cross-sectional and historical",
            "Requires Alpha ledgers and portfolio state",
            None,
            ("minimum score 85", "minimum reward/risk 2", "maximum stop distance 10%"),
            ParityClass.UNAVAILABLE_IN_TRADINGVIEW,
            "Only Pine-compatible static score, reward/risk, stop and setup "
            "filters are "
            "applied; adaptive, capacity, live and portfolio gates remain unavailable.",
        ),
        _component(
            "Forward outcome ordering",
            "RecommendationOutcomeEvaluator",
            ("future OHLCV", "frozen entry", "stop", "targets", "ATR trail"),
            "Trigger on bar high; stop wins same-bar stop/target conflict; then trail, "
            "highest target and 20-bar expiry.",
            "20 future bars by default",
            "Begins strictly after recommendation date",
            None,
            ("stop-first same bar", "2x ATR below highest close"),
            ParityClass.SEMANTICALLY_EQUIVALENT,
            "Pine bar execution timing differs from Alpha's frozen next-session "
            "evaluator.",
        ),
        _component(
            "Cross-sectional and learned systems",
            "Alpha decision, learning, Market DNA and allocation packages",
            ("universe", "ledger", "portfolio", "warehouse lineage"),
            "Candidate ranking, posterior learning, portfolio constraints and "
            "evidence lineage.",
            "Multi-symbol and longitudinal",
            "Not available to ordinary Pine strategies",
            None,
            (),
            ParityClass.EXCLUDED,
            "Explicitly excluded: no proxy is used and no ALPHA_EXACT label is "
            "permitted.",
        ),
    )
    return components


def parity_counts(
    components: tuple[ComponentParity, ...],
) -> dict[ParityClass, int]:
    """Return stable counts by parity class."""

    return {
        parity_class: sum(
            component.parity_class is parity_class for component in components
        )
        for parity_class in ParityClass
    }


def _component(
    name: str,
    symbol: str,
    inputs: tuple[str, ...],
    semantics: str,
    lookback: str,
    warmup: str,
    weight: Decimal | None,
    thresholds: tuple[str, ...],
    parity_class: ParityClass,
    difference: str,
) -> ComponentParity:
    source = (
        "alpha/performance_intelligence/outcomes.py"
        if symbol == "RecommendationOutcomeEvaluator"
        else "alpha/decision_intelligence/engine.py"
        if symbol == "InstitutionalDecisionEngine"
        else "alpha/recommendation_intelligence/engines.py"
    )
    return ComponentParity(
        component_name=name,
        python_source_file=source,
        python_symbol_or_class=symbol,
        input_data=inputs,
        formula_or_semantics=semantics,
        lookback=lookback,
        warmup_requirement=warmup,
        weight=weight,
        thresholds=thresholds,
        missing_data_behavior=(
            "Unavailable evidence remains visible and is not silently imputed."
        ),
        pine_reproducibility=(
            "Reproduced in Pine with the disclosed chart-data and execution boundary."
            if parity_class in {ParityClass.EXACT, ParityClass.SEMANTICALLY_EQUIVALENT}
            else "Not fully reproducible in an ordinary single-symbol Pine strategy."
        ),
        parity_class=parity_class,
        known_difference=difference,
        test_method=(
            "Python manifest/static checks plus documented TradingView fixture run."
        ),
    )
