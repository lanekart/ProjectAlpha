"""Generate Pine manifests from Alpha's executable source of truth."""

from __future__ import annotations

import json
import subprocess
from decimal import Decimal
from pathlib import Path

from alpha.decision_intelligence import engine as decision_engine
from alpha.pine_export.models import (
    ALPHA_SOURCE_OF_TRUTH,
    AUTONOMOUS_DEPLOYMENT,
    BROKER_ORDERING,
    NO_LOOKAHEAD,
    NO_MANUAL_POST_GENERATION_PATCHING,
    NO_NEW_STRATEGY_LOGIC,
    NO_REPAINTING,
    PRODUCTION_INFLUENCE,
    TRADINGVIEW_EXECUTION,
    TRADINGVIEW_IS_SECONDARY_VALIDATOR,
    PineExportConfig,
)
from alpha.pine_export.parity_audit import build_parity_audit
from alpha.recommendation_intelligence.engines import (
    EvidenceScoringEngine,
    RecommendationScoringEngine,
    TradeSetupEngine,
)
from alpha.recommendation_intelligence.models import TradeStrategyType
from alpha.version import __version__


class FrameworkManifestBuilder:
    """Extract stable strategy metadata from Alpha's current runtime classes."""

    def build(self) -> dict[str, object]:
        weights = EvidenceScoringEngine()._weights()
        return {
            "strategy_id": "alpha_current_framework",
            "framework_version": __version__,
            "source_commit": _source_commit(),
            "dataset_semantics": "TradingView chart data",
            "production_influence": PRODUCTION_INFLUENCE,
            "components": {name: str(weight) for name, weight in weights.items()},
            "verdict_mapping": _extract_verdict_mapping(),
            "setups": {
                "aliases": dict(sorted(TradeSetupEngine._ALIASES.items())),
                "categories": dict(sorted(TradeSetupEngine._CATEGORIES.items())),
                "pine_auto_detection": {
                    "BULL FLAG": "SEMANTICALLY_EQUIVALENT",
                    "EMA PULLBACK": "SEMANTICALLY_EQUIVALENT",
                    "VOLATILITY CONTRACTION PATTERN": "SEMANTICALLY_EQUIVALENT",
                    "FAILED BREAKOUT": "SEMANTICALLY_EQUIVALENT",
                    "TREND FAILURE": "SEMANTICALLY_EQUIVALENT",
                    "FLAT BASE": "APPROXIMATED",
                    "CUP & HANDLE": "APPROXIMATED",
                },
            },
            "trade_strategies": [strategy.value for strategy in TradeStrategyType],
            "approval_filters": {
                "minimum_historical_sample_count": (
                    decision_engine._MIN_APPROVAL_SAMPLE_COUNT
                ),
                "minimum_posterior_probability": str(
                    decision_engine._MIN_APPROVAL_POSTERIOR
                ),
                "minimum_expectancy_r": str(decision_engine._MIN_APPROVAL_EXPECTANCY),
                "minimum_deployment_score": str(decision_engine._MIN_DEPLOYMENT_SCORE),
                "maximum_stop_distance_percent": str(
                    decision_engine._MAX_DEPLOYMENT_STOP_DISTANCE
                ),
                "pine_boundary": (
                    "Only score, stop-distance, reward/risk and setup-state filters "
                    "are Pine-compatible."
                ),
            },
            "trade_plan": {
                "atr": "14-bar simple mean of true range",
                "support_lookback_bars": 60,
                "stop_models": [
                    "SUPPORT_BASED",
                    "SWING_LOW",
                    "ATR_BUFFERED_SUPPORT",
                    "MOVING_AVERAGE_INVALIDATION",
                    "SETUP_INVALIDATION",
                    "FIXED_PERCENT_COMPARATOR",
                ],
                "target_models": [
                    "2R",
                    "3R",
                    "4R_ATR_EXTENSION",
                    "PARTIAL_2R_3R_4R",
                ],
                "same_bar_policy": "STOP_FIRST_CONSERVATIVE",
                "trailing_stop": "2 x ATR below highest close after entry",
                "trend_reference": "20-DMA is not an active stop by default",
            },
            "timeframes": {
                "positional": {"chart": "D", "trend": "W", "structural": "M"},
                "swing": {
                    "chart": "240 or D",
                    "trend": "D or W",
                    "confirmation": "240",
                },
                "short_swing": {
                    "chart": "60 or 240",
                    "trend": "D",
                    "confirmation": "60",
                },
            },
            "holding_periods": {
                "MOMENTUM CONTINUATION": "5-15 trading days",
                "EMA PULLBACK": "7-20 trading days",
                "BULL FLAG": "5-12 trading days",
                "VOLATILITY CONTRACTION PATTERN": "10-30 trading days",
                "FLAT BASE": "15-45 trading days",
                "CUP & HANDLE": "20-60 trading days",
                "FAILED BREAKOUT": "exit / avoid immediately",
                "TREND FAILURE": "exit / avoid immediately",
            },
            "parity_limitations": [
                component.component_name
                for component in build_parity_audit()
                if component.parity_class.value
                in {"APPROXIMATED", "UNAVAILABLE_IN_TRADINGVIEW", "EXCLUDED"}
            ],
            "guardrails": {
                "PRODUCTION_INFLUENCE": PRODUCTION_INFLUENCE,
                "BROKER_ORDERING": BROKER_ORDERING,
                "AUTONOMOUS_DEPLOYMENT": AUTONOMOUS_DEPLOYMENT,
                "TRADINGVIEW_EXECUTION": TRADINGVIEW_EXECUTION,
                "NO_LOOKAHEAD": NO_LOOKAHEAD,
                "NO_REPAINTING": NO_REPAINTING,
                "NO_NEW_STRATEGY_LOGIC": NO_NEW_STRATEGY_LOGIC,
                "NO_MANUAL_POST_GENERATION_PATCHING": (
                    NO_MANUAL_POST_GENERATION_PATCHING
                ),
                "ALPHA_SOURCE_OF_TRUTH": ALPHA_SOURCE_OF_TRUTH,
                "TRADINGVIEW_IS_SECONDARY_VALIDATOR": (
                    TRADINGVIEW_IS_SECONDARY_VALIDATOR
                ),
            },
        }

    def parity_manifest(self) -> dict[str, object]:
        return {
            "framework_version": __version__,
            "source_commit": _source_commit(),
            "components": [item.as_dict() for item in build_parity_audit()],
            "tradingview_compilation": "MANUAL_VERIFICATION_REQUIRED",
        }

    def write(self, output_directory: Path) -> tuple[Path, Path, Path]:
        output_directory.mkdir(parents=True, exist_ok=True)
        framework_path = output_directory / "alpha_framework_manifest.json"
        parity_path = output_directory / "alpha_pine_parity_manifest.json"
        defaults_path = output_directory / "alpha_default_parameters.json"
        _write_json(framework_path, self.build())
        _write_json(parity_path, self.parity_manifest())
        _write_json(defaults_path, PineExportConfig().as_dict())
        return framework_path, parity_path, defaults_path


def _extract_verdict_mapping() -> list[dict[str, str]]:
    engine = RecommendationScoringEngine()
    boundaries: list[dict[str, str]] = []
    previous = ""
    for hundredths in range(0, 10001):
        score = Decimal(hundredths) / Decimal("100")
        decision = engine._decision(score).value
        if decision != previous:
            boundaries.append(
                {"minimum_score": _decimal_text(score), "decision": decision}
            )
            previous = decision
    return boundaries


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _source_commit() -> str:
    try:
        result = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"
    return result.stdout.strip() or "UNKNOWN"


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
