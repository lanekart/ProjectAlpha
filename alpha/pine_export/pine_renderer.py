"""Deterministic rendering of self-contained Pine strategy sources."""

from __future__ import annotations

import re
from pathlib import Path

from alpha.pine_export.identifiers import (
    sanitize_identifier,
    sanitize_source_identifiers,
)
from alpha.pine_export.models import PineExportConfig

STRATEGY_FILES: dict[str, str] = {
    "component-audit": "Alpha_01_Component_Audit.pine",
    "setup-comparator": "Alpha_02_Setup_Comparator.pine",
    "institutional-composite": "Alpha_03_Institutional_Composite.pine",
    "multi-timeframe-composite": "Alpha_04_Multi_Timeframe_Composite.pine",
    "risk-exit-lab": "Alpha_05_Risk_Exit_Lab.pine",
    "combination-lab": "Alpha_06_Strategy_Combination_Lab.pine",
}


class PineRenderer:
    """Render a checked-in strategy with transparent configuration overrides."""

    def __init__(self, repository_root: Path | None = None) -> None:
        self.repository_root = repository_root or Path(__file__).resolve().parents[2]

    def render(self, config: PineExportConfig) -> str:
        filename = STRATEGY_FILES.get(config.strategy)
        if filename is None:
            supported = ", ".join(sorted(STRATEGY_FILES))
            raise ValueError(
                f"unsupported strategy {config.strategy!r}; choose one of: {supported}"
            )
        source_path = self.repository_root / "tradingview" / "strategies" / filename
        source = source_path.read_text(encoding="utf-8").replace("\r\n", "\n")
        source = source.replace("\r", "\n")
        source = sanitize_source_identifiers(source)
        replacements = {
            "ALPHA_DEFAULT_CHART_TIMEFRAME": config.timeframe,
            "ALPHA_DEFAULT_CONFIRMATION_TIMEFRAME": config.confirmation_timeframe,
            "ALPHA_DEFAULT_SETUP": config.setup,
            "ALPHA_DEFAULT_STOP_MODEL": config.stop_model,
            "ALPHA_DEFAULT_TARGET_MODEL": config.target_model,
            "ALPHA_DEFAULT_ENTRY_THRESHOLD": format(
                config.entry_threshold.normalize(), "f"
            ),
        }
        for key, value in replacements.items():
            source = _replace_export_setting(source, key, value)
        source = _replace_string_input(
            source,
            "Primary setup timeframe",
            config.timeframe,
        )
        source = _replace_string_input(
            source,
            "Confirmation timeframe",
            config.confirmation_timeframe,
        )
        source = _replace_string_input(source, "Setup selection", config.setup)
        source = _replace_string_input(source, "Stop model", config.stop_model)
        source = _replace_string_input(source, "Target model", config.target_model)
        source = _replace_numeric_input(
            source,
            "Entry score threshold",
            format(config.entry_threshold.normalize(), "f"),
        )
        return source.rstrip("\n") + "\n"


def pine_safe_identifier(value: str) -> str:
    """Convert external names to deterministic Pine-safe identifiers."""

    return sanitize_identifier(value)


def _replace_export_setting(source: str, key: str, value: str) -> str:
    pattern = re.compile(
        rf"^(// {re.escape(key)}=).*$",
        flags=re.MULTILINE,
    )
    if pattern.search(source) is None:
        return source
    return pattern.sub(rf"\g<1>{value}", source)


def _replace_string_input(source: str, label: str, value: str) -> str:
    pattern = re.compile(
        rf'(input\.(?:string|timeframe)\()"[^"]*"(, "{re.escape(label)}")'
    )
    return pattern.sub(rf'\g<1>"{value}"\g<2>', source)


def _replace_numeric_input(source: str, label: str, value: str) -> str:
    pattern = re.compile(
        rf'(input\.float\()[0-9]+(?:\.[0-9]+)?(, "{re.escape(label)}")'
    )
    return pattern.sub(rf"\g<1>{value}\g<2>", source)
