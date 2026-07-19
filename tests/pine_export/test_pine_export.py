from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from alpha.pine_export.manifest_builder import FrameworkManifestBuilder
from alpha.pine_export.models import (
    NO_MANUAL_POST_GENERATION_PATCHING,
    NO_NEW_STRATEGY_LOGIC,
    PRODUCTION_INFLUENCE,
    ParityClass,
    PineExportConfig,
)
from alpha.pine_export.parity_audit import build_parity_audit
from alpha.pine_export.pine_renderer import PineRenderer, pine_safe_identifier
from alpha.pine_export.strategy_exporter import PineStrategyExporter
from alpha.pine_export.validation import PineStaticValidator
from alpha.recommendation_intelligence.engines import EvidenceScoringEngine

ROOT = Path(__file__).resolve().parents[2]


def test_canonical_weight_extraction_matches_runtime() -> None:
    manifest = FrameworkManifestBuilder().build()

    assert manifest["components"] == {
        name: str(weight) for name, weight in EvidenceScoringEngine()._weights().items()
    }
    assert manifest["components"] == {
        "price_structure": "0.20",
        "volume": "0.17",
        "trend": "0.15",
        "relative_strength": "0.13",
        "retracement": "0.10",
        "candle": "0.08",
        "breakout": "0.07",
        "market_regime": "0.05",
        "sector": "0.03",
        "risk": "0.02",
    }


def test_verdict_thresholds_are_extracted_from_runtime() -> None:
    manifest = FrameworkManifestBuilder().build()

    assert manifest["verdict_mapping"] == [
        {"minimum_score": "0", "decision": "SELL"},
        {"minimum_score": "40", "decision": "AVOID"},
        {"minimum_score": "60", "decision": "WATCHLIST"},
        {"minimum_score": "75", "decision": "BUY"},
        {"minimum_score": "90", "decision": "STRONG_BUY"},
    ]


def test_setup_and_trade_strategy_mapping_are_canonical() -> None:
    manifest = FrameworkManifestBuilder().build()
    setups = manifest["setups"]

    assert isinstance(setups, dict)
    assert setups["aliases"]["BULL_FLAG"] == "BULL FLAG"
    assert setups["aliases"]["CUP_AND_HANDLE"] == "CUP & HANDLE"
    assert setups["pine_auto_detection"]["FLAT BASE"] == "APPROXIMATED"
    assert manifest["trade_strategies"] == [
        "MOMENTUM_BREAKOUT",
        "PULLBACK_ENTRY",
        "AGGRESSIVE_ACCUMULATION",
        "RETEST_HOLD",
        "NO_TRADE",
    ]


def test_stop_target_and_holding_period_mapping() -> None:
    manifest = FrameworkManifestBuilder().build()
    trade_plan = manifest["trade_plan"]
    holding_periods = manifest["holding_periods"]

    assert isinstance(trade_plan, dict)
    assert "ATR_BUFFERED_SUPPORT" in trade_plan["stop_models"]
    assert "4R_ATR_EXTENSION" in trade_plan["target_models"]
    assert trade_plan["same_bar_policy"] == "STOP_FIRST_CONSERVATIVE"
    assert isinstance(holding_periods, dict)
    assert holding_periods["BULL FLAG"] == "5-12 trading days"
    assert holding_periods["CUP & HANDLE"] == "20-60 trading days"


def test_manifest_generation_is_stable_and_json_safe(tmp_path: Path) -> None:
    builder = FrameworkManifestBuilder()
    first = builder.build()
    second = builder.build()

    assert first == second
    paths = builder.write(tmp_path)
    assert len(paths) == 3
    for path in paths:
        assert json.loads(path.read_text(encoding="utf-8"))


def test_parity_audit_uses_all_required_classes() -> None:
    audit = build_parity_audit()
    classes = {component.parity_class for component in audit}

    assert set(ParityClass) == classes
    assert all(component.python_source_file for component in audit)
    assert all(component.test_method for component in audit)
    assert any(
        component.component_name == "Market regime"
        and component.parity_class is ParityClass.UNAVAILABLE_IN_TRADINGVIEW
        for component in audit
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Bull Flag", "Bull_Flag"),
        ("52-week high", "alpha_52_week_high"),
        ("***", "alpha_value"),
    ],
)
def test_pine_safe_identifiers(raw: str, expected: str) -> None:
    assert pine_safe_identifier(raw) == expected


def test_renderer_is_stable_and_applies_configuration() -> None:
    config = PineExportConfig(
        strategy="multi-timeframe-composite",
        timeframe="240",
        confirmation_timeframe="60",
        entry_threshold=Decimal("82.5"),
    )
    renderer = PineRenderer(ROOT)

    first = renderer.render(config)
    second = renderer.render(config)

    assert first == second
    assert "// ALPHA_DEFAULT_CHART_TIMEFRAME=240" in first
    assert 'input.timeframe("240", "Primary setup timeframe"' in first
    assert 'input.timeframe("60", "Confirmation timeframe"' in first
    assert 'input.float(82.5, "Entry score threshold"' in first

    institutional = renderer.render(
        PineExportConfig(
            strategy="institutional-composite",
            setup="BULL FLAG",
        )
    )
    assert 'input.string("BULL FLAG", "Setup selection"' in institutional


def test_exporter_writes_self_contained_strategy(tmp_path: Path) -> None:
    output = tmp_path / "institutional.pine"
    path = PineStrategyExporter(ROOT).export(
        PineExportConfig(strategy="institutional-composite"),
        output,
    )

    source = path.read_text(encoding="utf-8")
    assert path == output
    assert source.startswith("//@version=6")
    assert source.count("strategy(") == 1
    assert "DATA SOURCE: TRADINGVIEW" in source


def test_export_config_rejects_invalid_models() -> None:
    with pytest.raises(ValueError, match="setup"):
        PineExportConfig(setup="INVENTED")
    with pytest.raises(ValueError, match="stop_model"):
        PineExportConfig(stop_model="INVENTED")
    with pytest.raises(ValueError, match="target_model"):
        PineExportConfig(target_model="INVENTED")
    with pytest.raises(ValueError, match="entry_threshold"):
        PineExportConfig(entry_threshold=Decimal("101"))


def test_all_pine_sources_pass_static_validation() -> None:
    report = PineStaticValidator().validate_directory(ROOT / "tradingview")

    assert report.files_checked == 27
    assert report.passed
    assert report.issues == ()


def test_static_validation_rejects_future_access_and_python_values(
    tmp_path: Path,
) -> None:
    source = (
        "//@version=6\n"
        'indicator("Bad")\n'
        'x = request.security(syminfo.tickerid, "D", close, '
        "lookahead=barmerge.lookahead_on)\n"
        "y = None\n"
    )
    issues = PineStaticValidator().validate_source(tmp_path / "bad.pine", source)

    codes = {issue.code for issue in issues}
    assert "REPAINTING_CONSTRUCT" in codes
    assert "SECURITY_LOOKAHEAD_EXPLICIT" in codes
    assert "PYTHON_TOKEN" in codes


def test_fixture_inventory_covers_required_cases() -> None:
    payload = json.loads(
        (ROOT / "tradingview" / "fixtures" / "parity_cases.json").read_text(
            encoding="utf-8"
        )
    )
    identifiers = {case["id"] for case in payload["cases"]}

    assert {
        "rising_trend",
        "falling_trend",
        "sideways_range",
        "valid_breakout",
        "failed_breakout",
        "ema_pullback",
        "vcp_contraction",
        "bull_flag",
        "flat_base",
        "gap",
        "split_like_discontinuity",
        "volume_breakout",
        "low_volume_breakout",
        "support_stop",
        "atr_stop",
        "same_bar_stop_target",
        "higher_timeframe_confirmation",
        "incomplete_higher_timeframe_bar",
    } <= identifiers


def test_documentation_preserves_boundary_and_warning() -> None:
    suite = (ROOT / "docs" / "pine" / "ALPHA_PINE_RESEARCH_SUITE.md").read_text(
        encoding="utf-8"
    )
    protocol = (ROOT / "docs" / "pine" / "TRADINGVIEW_BACKTEST_PROTOCOL.md").read_text(
        encoding="utf-8"
    )
    limitations = (ROOT / "docs" / "pine" / "TRADINGVIEW_LIMITATIONS.md").read_text(
        encoding="utf-8"
    )

    assert "PRODUCTION_INFLUENCE=false" in suite
    assert "TRADINGVIEW_MANUAL_COMPILATION=USER_VERIFICATION_REQUIRED" in protocol
    assert "DATA SOURCE: TRADINGVIEW" in limitations
    assert "No output may be labelled `ALPHA_EXACT`" in limitations


def test_pine_suite_has_no_production_influence() -> None:
    assert PRODUCTION_INFLUENCE is False
    manifest = FrameworkManifestBuilder().build()
    assert manifest["production_influence"] is False
    assert manifest["guardrails"] == {
        "PRODUCTION_INFLUENCE": False,
        "BROKER_ORDERING": False,
        "AUTONOMOUS_DEPLOYMENT": False,
        "TRADINGVIEW_EXECUTION": False,
        "NO_LOOKAHEAD": True,
        "NO_REPAINTING": True,
        "NO_NEW_STRATEGY_LOGIC": True,
        "NO_MANUAL_POST_GENERATION_PATCHING": True,
        "ALPHA_SOURCE_OF_TRUTH": True,
        "TRADINGVIEW_IS_SECONDARY_VALIDATOR": True,
    }
    assert NO_NEW_STRATEGY_LOGIC is True
    assert NO_MANUAL_POST_GENERATION_PATCHING is True
