from decimal import Decimal

import pytest

from alpha.portfolio import (
    CashReserveConstraint,
    ConstraintSet,
    OptimizationInput,
    OptimizationResult,
    PositionLimitConstraint,
    SectorLimitConstraint,
    TurnoverConstraint,
)


def test_optimization_result_is_immutable_value_object() -> None:
    result = OptimizationResult(
        target_weights={"AAPL": Decimal("0.50")},
        success=True,
        cash_weight=Decimal("0.50"),
    )

    assert result.invested_weight == Decimal("0.50")
    assert result.total_weight == Decimal("1.00")
    assert not result.has_violations

    with pytest.raises(TypeError):
        result.target_weights["MSFT"] = Decimal("0.50")  # type: ignore[index]


def test_position_limit_constraint_reports_violation() -> None:
    constraint = PositionLimitConstraint(max_weight=Decimal("0.30"))

    violations = constraint.validate(
        target_weights={"AAPL": Decimal("0.40")},
        current_weights={},
        sector_by_symbol={},
        cash_weight=Decimal("0"),
    )

    assert len(violations) == 1
    assert violations[0].constraint_name == "position_limit"


def test_sector_limit_constraint_reports_violation() -> None:
    constraint = SectorLimitConstraint(max_weight=Decimal("0.50"))

    violations = constraint.validate(
        target_weights={
            "AAPL": Decimal("0.30"),
            "MSFT": Decimal("0.30"),
        },
        current_weights={},
        sector_by_symbol={
            "AAPL": "Technology",
            "MSFT": "Technology",
        },
        cash_weight=Decimal("0.40"),
    )

    assert len(violations) == 1
    assert violations[0].constraint_name == "sector_limit"


def test_turnover_constraint_reports_violation() -> None:
    constraint = TurnoverConstraint(max_turnover=Decimal("0.10"))

    violations = constraint.validate(
        target_weights={"AAPL": Decimal("0.80")},
        current_weights={"AAPL": Decimal("0.40")},
        sector_by_symbol={},
        cash_weight=Decimal("0.20"),
    )

    assert len(violations) == 1
    assert violations[0].constraint_name == "turnover_limit"


def test_cash_reserve_constraint_reports_violation() -> None:
    constraint = CashReserveConstraint(min_cash_weight=Decimal("0.10"))

    violations = constraint.validate(
        target_weights={"AAPL": Decimal("0.95")},
        current_weights={},
        sector_by_symbol={},
        cash_weight=Decimal("0.05"),
    )

    assert len(violations) == 1
    assert violations[0].constraint_name == "cash_reserve"


def test_constraint_set_collects_all_violations() -> None:
    constraint_set = ConstraintSet(
        constraints=(
            PositionLimitConstraint(max_weight=Decimal("0.30")),
            CashReserveConstraint(min_cash_weight=Decimal("0.10")),
        )
    )

    violations = constraint_set.validate(
        target_weights={"AAPL": Decimal("0.95")},
        current_weights={},
        sector_by_symbol={},
        cash_weight=Decimal("0.05"),
    )

    assert len(violations) == 2


def test_optimization_input_rejects_empty_universe() -> None:
    with pytest.raises(ValueError):
        OptimizationInput(universe=())


def test_optimization_input_rejects_duplicate_symbols() -> None:
    with pytest.raises(ValueError):
        OptimizationInput(universe=("AAPL", "AAPL"))
