from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from alpha.pine_export.identifiers import (
    PINE_UNSAFE_IDENTIFIERS,
    build_identifier_map,
    rewrite_identifiers,
    sanitize_identifier,
    sanitize_source_identifiers,
)
from alpha.pine_export.models import PineExportConfig, PineValidationReport
from alpha.pine_export.pine_renderer import STRATEGY_FILES, PineRenderer
from alpha.pine_export.validation import PineStaticValidator

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "pine_export" / "fixtures"


@pytest.mark.parametrize(
    "identifier",
    [
        "range",
        "time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "strategy",
        "indicator",
        "plot",
        "table",
        "line",
        "label",
        "box",
        "map",
        "matrix",
        "array",
        "type",
        "method",
        "export",
        "import",
        "var",
        "varip",
        "if",
        "for",
        "while",
        "switch",
    ],
)
def test_required_reserved_and_unsafe_identifiers_are_sanitized(
    identifier: str,
) -> None:
    sanitized = sanitize_identifier(identifier)

    assert sanitized != identifier
    assert sanitized not in PINE_UNSAFE_IDENTIFIERS
    assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", sanitized)


def test_range_is_rewritten_readably_and_consistently() -> None:
    source = (
        "//@version=6\n"
        'indicator("Range fixture")\n'
        "range = high - low\n"
        "normalized = range == 0.0 ? 0.0 : close / range\n"
        "// range remains documentation\n"
        'labelText = "range remains text"\n'
    )

    rendered = sanitize_source_identifiers(source)

    assert "priceRange = high - low" in rendered
    assert "close / priceRange" in rendered
    assert "// range remains documentation" in rendered
    assert '"range remains text"' in rendered


def test_identifier_map_rejects_output_collision() -> None:
    with pytest.raises(ValueError, match="collision"):
        build_identifier_map(("range", "priceRange"))


def test_token_rewrite_does_not_modify_longer_identifiers() -> None:
    rewritten = rewrite_identifiers(
        "range = rangeValue + range\n",
        {"range": "priceRange"},
    )

    assert rewritten == "priceRange = rangeValue + priceRange\n"


def test_reported_reserved_range_failure_is_reproduced() -> None:
    path = FIXTURES / "reserved_range.pine.txt"
    issues = PineStaticValidator().validate_source(
        path,
        path.read_text(encoding="utf-8"),
    )

    assert "UNSAFE_IDENTIFIER" in {issue.code for issue in issues}


def test_reported_detached_comparison_failure_is_reproduced() -> None:
    path = FIXTURES / "detached_comparison.pine.txt"
    issues = PineStaticValidator().validate_source(
        path,
        path.read_text(encoding="utf-8"),
    )
    codes = {issue.code for issue in issues}

    assert "DANGLING_EXPRESSION" in codes
    assert "BARE_EXPRESSION_FRAGMENT" in codes


def test_validator_detects_structural_source_defects(tmp_path: Path) -> None:
    source = (
        "//@version=6\n"
        'indicator("Defects")\n'
        "duplicate = 1.0\n"
        "duplicate = 2.0\n"
        "missing := 3.0\n"
        "unknownType = na\n"
        "broken = (close + high\n"
    )
    issues = PineStaticValidator().validate_source(tmp_path / "bad.pine", source)
    codes = {issue.code for issue in issues}

    assert "DUPLICATE_GLOBAL_IDENTIFIER" in codes
    assert "UNDECLARED_REASSIGNMENT" in codes
    assert "NA_TYPE_REQUIRED" in codes
    assert "UNBALANCED_DELIMITER" in codes


def test_validator_detects_byte_and_container_defects(tmp_path: Path) -> None:
    path = tmp_path / "bad.pine"
    path.write_bytes(
        b'\xef\xbb\xbf```pine\r\n//@version=6\r\nindicator("Bad")\r\n```\r\n'
    )

    result = PineStaticValidator().validate_file(path)
    codes = {issue.code for issue in result.issues}

    assert "UTF8_BOM" in codes
    assert "LINE_ENDINGS" in codes
    assert "MARKDOWN_FENCE" in codes
    assert "PINE_VERSION" in codes
    assert "INVISIBLE_CHARACTER" in codes


def test_generated_import_is_rejected_as_not_self_contained(tmp_path: Path) -> None:
    path = tmp_path / "generated" / "bad.pine"
    source = '//@version=6\nimport owner/AlphaCore/1 as core\nindicator("Imported")\n'

    issues = PineStaticValidator().validate_source(path, source)

    assert "GENERATED_IMPORT" in {issue.code for issue in issues}


def test_strict_mode_treats_static_warning_as_failure(tmp_path: Path) -> None:
    source = "//@version=6\n" + 'indicator("Large")\n' + "//" + "x" * 100_100
    result = PineStaticValidator().validate_source_result(
        tmp_path / "large.pine",
        source,
    )
    report = PineValidationReport(files=(result,))

    assert report.passed
    assert not report.strict_passed
    assert report.as_dict(strict=True)["status"] == "FAIL"


def test_all_generated_variants_are_clean_and_self_contained() -> None:
    generated = ROOT / "tradingview" / "generated"
    files = tuple(sorted(generated.glob("*.pine")))

    assert len(files) == len(STRATEGY_FILES) == 6
    for path in files:
        raw = path.read_bytes()
        source = raw.decode("utf-8")
        assert raw.startswith(b"//@version=6")
        assert not raw.startswith(b"\xef\xbb\xbf")
        assert b"\r" not in raw
        assert "```" not in source
        assert not re.search(r"(?m)^\s*import\s+", source)


def test_every_strategy_renders_deterministically() -> None:
    renderer = PineRenderer(ROOT)

    for strategy in STRATEGY_FILES:
        config = PineExportConfig(strategy=strategy)
        assert renderer.render(config) == renderer.render(config)


def test_institutional_regressions_and_smoke_defaults_are_fixed() -> None:
    source = (
        ROOT / "tradingview" / "generated" / "Alpha_03_Institutional_Composite.pine"
    ).read_text(encoding="utf-8")

    assert "priceRange = swingHigh - swingLow" in source
    assert "swingRange" not in source
    assert not re.search(r"\brange\b", source)
    assert (
        'aggressiveAccumulationSignal = strategyType == "AGGRESSIVE_ACCUMULATION"'
    ) in source
    assert not re.search(r"(?m)^\s*>=\s*$", source)
    assert 'timestamp("01 Jan 2017 00:00 +0000")' in source
    assert 'timestamp("31 Dec 2021 23:59 +0000")' in source


def test_all_time_inputs_use_constant_timestamp_strings() -> None:
    for path in (ROOT / "tradingview").rglob("*.pine"):
        source = path.read_text(encoding="utf-8")
        assert re.search(r"input\.time\(timestamp\(\d", source) is None


def test_runtime_smoke_configuration_is_exact() -> None:
    payload = json.loads(
        (
            ROOT / "tradingview" / "generated" / "alpha_runtime_smoke_config.json"
        ).read_text(encoding="utf-8")
    )

    assert payload == {
        "chart_timeframe": "1D",
        "confirmed_bars_only": True,
        "end_date": "2021-12-31",
        "long_only": True,
        "market_regime_proxy": False,
        "pyramiding": 0,
        "script": "Alpha_03_Institutional_Composite.pine",
        "sector_proxy": False,
        "start_date": "2017-01-01",
        "structural_timeframe": "1M",
        "symbol": "NSE:RELIANCE",
        "trend_timeframe": "1W",
    }


def test_machine_report_contains_one_record_per_file() -> None:
    report = PineStaticValidator().validate_directory(ROOT / "tradingview")
    payload = report.as_dict(strict=True)

    assert payload["files_checked"] == 27
    assert payload["status"] == "PASS"
    assert len(payload["files"]) == 27
    assert all(
        set(item) == {"errors", "file", "metrics", "status", "warnings"}
        for item in payload["files"]
    )


def test_documented_hardening_boundary_is_present() -> None:
    hardening = (ROOT / "docs" / "pine" / "PINE_V6_COMPILATION_HARDENING.md").read_text(
        encoding="utf-8"
    )
    checklist = (
        ROOT / "docs" / "pine" / "TRADINGVIEW_MANUAL_COMPILATION_CHECKLIST.md"
    ).read_text(encoding="utf-8")
    limitations = (ROOT / "docs" / "pine" / "KNOWN_PINE_LIMITATIONS.md").read_text(
        encoding="utf-8"
    )
    compilation_report = (
        ROOT / "docs" / "pine" / "PINE_COMPILATION_REPORT.md"
    ).read_text(encoding="utf-8")

    assert "NO_NEW_STRATEGY_LOGIC=true" in hardening
    assert "NO_MANUAL_POST_GENERATION_PATCHING=true" in hardening
    assert "TRADINGVIEW_MANUAL_COMPILATION" in checklist
    assert "USER_VERIFICATION_REQUIRED" in checklist
    assert "64 plot counts" in limitations
    assert "PINE_STATIC_VALIDATION=PASS" in compilation_report
    assert "No TradingView compilation or runtime pass is" in compilation_report


def test_export_config_rejects_non_finite_or_unsafe_values() -> None:
    with pytest.raises(ValueError, match="finite"):
        PineExportConfig(entry_threshold=Decimal("NaN"))
    with pytest.raises(ValueError, match="characters"):
        PineExportConfig(timeframe='D")\nplot(close)')
