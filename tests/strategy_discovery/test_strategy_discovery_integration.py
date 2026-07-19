from __future__ import annotations

from alpha.application.strategy_discovery_cli import strategy_app
from alpha.research.diagnostic_registry import default_diagnostic_registry
from alpha.strategy_discovery.models import (
    CURRENT_PRODUCTION_POLICY,
    PRODUCTION_INFLUENCE,
)


def test_all_strategy_cli_commands_are_registered() -> None:
    names = {command.name for command in strategy_app.registered_commands}

    assert names == {
        "discover",
        "walk-forward",
        "evaluate",
        "robustness",
        "leaderboard",
        "publish-shadow-candidate",
        "discovery-report",
    }


def test_strategy_discovery_registers_with_ird_as_plugin() -> None:
    registry = default_diagnostic_registry(discover_plugins=False)

    assert "strategy-discovery-generalisation" in registry.plugin_ids


def test_production_policy_is_frozen_and_influence_is_false() -> None:
    assert CURRENT_PRODUCTION_POLICY == "APPROVAL_POLICY_V1"
    assert PRODUCTION_INFLUENCE is False
