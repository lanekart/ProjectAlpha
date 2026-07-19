from __future__ import annotations

from alpha.strategy_lab.models import EntryRule, StopRule, StrategyTemplate, TargetRule


class StrategyTemplateRegistry:
    """Registry of interpretable strategy templates permitted in the MVP lab."""

    def __init__(self) -> None:
        self._templates = _templates()
        ids = tuple(item.template_id for item in self._templates)
        if len(ids) != len(set(ids)):
            raise ValueError("strategy template ids must be unique")

    @property
    def templates(self) -> tuple[StrategyTemplate, ...]:
        return self._templates


def _templates() -> tuple[StrategyTemplate, ...]:
    standard_entries = (
        EntryRule.RECORDED_REFERENCE,
        EntryRule.NEXT_SESSION_OPEN,
        EntryRule.NEXT_SESSION_CLOSE,
        EntryRule.PREFERRED_ENTRY,
        EntryRule.AGGRESSIVE_ENTRY,
        EntryRule.CONFIRMATION_ENTRY,
        EntryRule.BREAKOUT_ENTRY,
        EntryRule.LIMIT_ENTRY_ZONE,
    )
    standard_stops = tuple(StopRule)
    standard_targets = tuple(TargetRule)
    rows = (
        (
            "single-indicator",
            "Single Indicator Threshold",
            "SINGLE_INDICATOR",
            1,
            False,
        ),
        ("two-indicator", "Two Indicator Conjunction", "CONJUNCTION", 2, False),
        ("three-indicator", "Three Indicator Conjunction", "CONJUNCTION", 3, False),
        ("weighted-score", "Weighted Score", "WEIGHTED_SCORE", 3, False),
        ("setup-specific", "Setup Specific", "SETUP_SPECIFIC", 3, False),
        ("entry-timing", "Entry Timing Specific", "ENTRY_TIMING", 3, False),
        ("price-only", "Price Only", "PRICE_STRUCTURE", 1, False),
        ("price-volume", "Price Plus Volume", "PRICE_VOLUME", 2, False),
        ("trend-rs", "Trend Plus Relative Strength", "TREND_RS", 2, False),
        ("support-breakout", "Support Resistance Breakout", "BREAKOUT", 3, False),
        ("retracement", "Pullback and Retracement", "RETRACEMENT", 3, False),
        ("trade-plan", "Trade Plan Quality", "TRADE_PLAN", 3, False),
        ("raw-approval", "Raw Approval Policy", "RAW_RECORDED_APPROVAL", 3, True),
        ("approval-v1", "APPROVAL_POLICY_V1", "APPROVAL_POLICY_V1", 3, True),
        ("recommendation-score", "Recommendation Score", "SCORE_THRESHOLD", 1, True),
        ("no-trade", "No Trade", "NO_TRADE", 0, True),
        ("broad-benchmark", "Broad Benchmark", "BROAD_BENCHMARK", 0, True),
    )
    return tuple(
        StrategyTemplate(
            template_id=template_id,
            name=name,
            family=family,
            description=f"Interpretable {name.lower()} research template.",
            maximum_components=maximum,
            supported_entry_rules=standard_entries,
            supported_stop_rules=standard_stops,
            supported_target_rules=standard_targets,
            benchmark=benchmark,
        )
        for template_id, name, family, maximum, benchmark in rows
    )


__all__ = ["StrategyTemplateRegistry"]
