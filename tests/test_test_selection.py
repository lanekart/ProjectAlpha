from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path("scripts/select_tests.py")
_SPEC = importlib.util.spec_from_file_location("select_tests", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_historical_truth_change_selects_subsystem() -> None:
    targets = _MODULE.select_targets(
        ("alpha/historical_truth/official_bridge_reconciliation.py",)
    )

    assert "tests/historical_truth" in targets


def test_test_selection_infrastructure_selects_its_own_tests() -> None:
    targets = _MODULE.select_targets(("Makefile", "scripts/select_tests.py"))

    assert targets == ("tests/test_test_selection.py",)


def test_shared_contract_change_falls_back_to_full_suite() -> None:
    targets = _MODULE.select_targets(
        ("alpha/historical_truth/adjustment_replay_admission_models.py",)
    )

    assert targets == ("tests",)


def test_unknown_source_change_falls_back_to_full_suite() -> None:
    targets = _MODULE.select_targets(("alpha/unknown/new_module.py",))

    assert targets == ("tests",)
