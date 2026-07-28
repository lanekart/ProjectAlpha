from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import duckdb
import pytest
from typer.testing import CliRunner

from alpha.historical_truth.cli import historical_truth_app
from alpha.historical_truth.complete_corporate_action_engine import (
    adjusted_replay_readiness,
    canonicalize_events,
    cumulative_factors,
    derive_factors,
    map_factor_state,
    normalize_action,
)
from alpha.historical_truth.complete_corporate_action_exports import (
    CompleteCorporateActionArtifactExporter,
)
from alpha.historical_truth.complete_corporate_action_models import (
    PRODUCTION_INFLUENCE,
    CompleteCorporateActionReport,
    FactorState,
    GovernedActionType,
    ReplayReadiness,
)
from alpha.historical_truth.corporate_action_price_models import (
    ActionAdmissionState,
    AdjustmentFactorState,
    CorporateActionEvent,
    CorporateActionType,
    EvidenceConfidence,
)

IDENTITY = "nse:isin:INE000A01001"


def _action(**changes: object) -> CorporateActionEvent:
    action = CorporateActionEvent(
        action_id="raw:one",
        exchange="NSE",
        governed_identity_id=IDENTITY,
        symbol="ALPHA",
        series="EQ",
        isin="INE000A01001",
        action_type=CorporateActionType.SPLIT,
        purpose="Face Value Split From Rs 10 To Rs 5",
        announcement_date=date(2020, 1, 1),
        record_date=date(2020, 1, 10),
        ex_date=date(2020, 1, 9),
        effective_date=date(2020, 1, 9),
        old_face_value=10.0,
        new_face_value=5.0,
        ratio_numerator=None,
        ratio_denominator=None,
        cash_amount=None,
        rights_price=None,
        old_quantity=None,
        new_quantity=None,
        predecessor_identity=None,
        successor_identity=None,
        price_adjustment_required=True,
        adjustment_factor_state=AdjustmentFactorState.DERIVED_FROM_OFFICIAL_TERMS,
        adjustment_factor=0.5,
        source_id="official:2020",
        source_location="https://www.nseindia.com/official",
        admission_state=ActionAdmissionState.ADMITTED,
        confidence_state=EvidenceConfidence.HIGH,
    )
    return replace(action, **changes)


def _join(state: str = "JOIN_READY_TRADABILITY_PARTIAL") -> dict[str, object]:
    return {
        "identity_key": IDENTITY,
        "symbol": "ALPHA",
        "state": state,
        "admitted_to_certified_join": True,
    }


@pytest.mark.parametrize(
    ("action_type", "purpose", "expected"),
    [
        (CorporateActionType.SPLIT, "split", GovernedActionType.SPLIT),
        (CorporateActionType.BONUS, "bonus", GovernedActionType.BONUS),
        (CorporateActionType.RIGHTS, "rights", GovernedActionType.RIGHTS),
        (
            CorporateActionType.DIVIDEND,
            "Interim Dividend",
            GovernedActionType.DIVIDEND_INTERIM,
        ),
        (
            CorporateActionType.DIVIDEND,
            "Special Dividend",
            GovernedActionType.DIVIDEND_SPECIAL,
        ),
        (CorporateActionType.MERGER, "merger", GovernedActionType.MERGER),
        (CorporateActionType.DEMERGER, "demerger", GovernedActionType.DEMERGER),
        (
            CorporateActionType.SCHEME_OF_ARRANGEMENT,
            "scheme",
            GovernedActionType.SCHEME_OF_ARRANGEMENT,
        ),
        (
            CorporateActionType.UNKNOWN_ACTION,
            "Annual General Meeting",
            GovernedActionType.OTHER_NON_ADJUSTING_EVENT,
        ),
        (
            CorporateActionType.UNKNOWN_ACTION,
            "Unclassified economic event",
            GovernedActionType.UNKNOWN_ACTION,
        ),
    ],
)
def test_event_normalization(
    action_type: CorporateActionType,
    purpose: str,
    expected: GovernedActionType,
) -> None:
    assert (
        normalize_action(_action(action_type=action_type, purpose=purpose)) is expected
    )


def test_parallel_series_are_one_event_with_explicit_applicability() -> None:
    eq = _action()
    be = replace(eq, action_id="raw:two", series="BE")

    events, duplicates, rejected = canonicalize_events((eq, be), {IDENTITY: _join()})

    assert len(events) == 1
    assert events[0]["series_applicability"] == ["BE", "EQ"]
    assert len(duplicates) == 1
    assert len(rejected) == 1


def test_bounded_identity_assignment_remains_explicit() -> None:
    events, _, _ = canonicalize_events(
        (_action(),), {IDENTITY: _join("JOIN_READY_BOUNDED_MEMBERSHIP")}
    )

    assert events[0]["admission_state"] == "ADMITTED_BOUNDED_IDENTITY"
    assert events[0]["assignment_method"] == "OFFICIAL_ISIN_INTERVAL"


def test_no_symbol_only_identity_assignment() -> None:
    action = _action(governed_identity_id=None)

    with pytest.raises(KeyError):
        canonicalize_events((action,), {IDENTITY: _join()})


def test_non_adjusting_information_has_no_factor_requirement() -> None:
    action = _action(
        action_type=CorporateActionType.UNKNOWN_ACTION,
        purpose="Annual General Meeting",
        adjustment_factor_state=AdjustmentFactorState.UNKNOWN,
    )

    assert (
        map_factor_state(action, normalize_action(action))
        is FactorState.FACTOR_NOT_REQUIRED
    )


def test_merger_is_non_multiplicative() -> None:
    action = _action(action_type=CorporateActionType.MERGER)

    assert (
        map_factor_state(action, normalize_action(action))
        is FactorState.FACTOR_NOT_MULTIPLICATIVE
    )


def test_bonus_of_separate_dvr_security_is_non_multiplicative() -> None:
    action = _action(
        action_type=CorporateActionType.BONUS,
        purpose="Bonus 1 Dvr : 10 Eq Share",
        adjustment_factor_state=AdjustmentFactorState.AMBIGUOUS,
        adjustment_factor=None,
    )

    assert (
        map_factor_state(action, normalize_action(action))
        is FactorState.FACTOR_NOT_MULTIPLICATIVE
    )


@pytest.mark.parametrize(
    "purpose",
    [
        "Sch Of Agmt- Bonus Deb1:1",
        "Bonus Preference Shares 21:1",
    ],
)
def test_bonus_of_separate_security_is_non_multiplicative(purpose: str) -> None:
    action = _action(
        action_type=CorporateActionType.BONUS,
        purpose=purpose,
        adjustment_factor_state=AdjustmentFactorState.AMBIGUOUS,
        adjustment_factor=None,
    )

    assert (
        map_factor_state(action, normalize_action(action))
        is FactorState.FACTOR_NOT_MULTIPLICATIVE
    )


def test_rights_factor_uses_governed_prior_close(tmp_path: Path) -> None:
    database = tmp_path / "source.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "CREATE TABLE daily_candle(symbol VARCHAR, series VARCHAR, "
            "trading_date DATE, close_price DOUBLE)"
        )
        connection.execute(
            "INSERT INTO daily_candle VALUES ('ALPHA','EQ','2020-01-08',100)"
        )
    rights = _action(
        action_type=CorporateActionType.RIGHTS,
        purpose="Rights 1:1 at Rs 50",
        ratio_numerator=1.0,
        ratio_denominator=1.0,
        rights_price=50.0,
        adjustment_factor=None,
    )
    canonical, _, _ = canonicalize_events((rights,), {IDENTITY: _join()})

    factors = derive_factors(database, canonical, {rights.action_id: rights})

    assert factors[0]["price_factor"] == pytest.approx(0.75)
    assert factors[0]["factor_state"] == "FACTOR_PROVISIONAL_REFERENCE_PRICE"


def test_rights_without_reference_price_remains_unknown(tmp_path: Path) -> None:
    database = tmp_path / "source.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "CREATE TABLE daily_candle(symbol VARCHAR, series VARCHAR, "
            "trading_date DATE, close_price DOUBLE)"
        )
    rights = _action(
        action_type=CorporateActionType.RIGHTS,
        purpose="Rights 1:1 at Rs 50",
        ratio_numerator=1.0,
        ratio_denominator=1.0,
        rights_price=50.0,
        adjustment_factor=None,
    )
    canonical, _, _ = canonicalize_events((rights,), {IDENTITY: _join()})

    factors = derive_factors(database, canonical, {rights.action_id: rights})

    assert factors[0]["price_factor"] is None
    assert factors[0]["factor_state"] == "FACTOR_UNKNOWN_MISSING_TERMS"


def test_cumulative_factor_stops_at_unknown_boundary() -> None:
    factors = (
        {
            "factor_id": "one",
            "identity_key": IDENTITY,
            "effective_date": "2020-01-01",
            "price_factor": 0.5,
            "quantity_factor": 2.0,
            "factor_state": "FACTOR_DERIVED_OFFICIAL_TERMS",
        },
        {
            "factor_id": "two",
            "identity_key": IDENTITY,
            "effective_date": "2021-01-01",
            "price_factor": None,
            "quantity_factor": None,
            "factor_state": "FACTOR_UNKNOWN_MISSING_TERMS",
        },
    )

    rows = cumulative_factors(factors)

    assert rows[0]["backward_cumulative_price_factor"] == 0.5
    assert rows[1]["backward_cumulative_price_factor"] is None
    assert rows[1]["forward_cumulative_price_factor"] is None


def test_unknown_factors_are_quarantined_not_applied_as_one() -> None:
    readiness = adjusted_replay_readiness(
        (),
        (
            {
                "identity_key": IDENTITY,
                "factor_state": "FACTOR_UNKNOWN_MISSING_TERMS",
            },
        ),
        ({"quarantined": True},),
        "raw-hash",
    )

    assert readiness["state"] == (
        ReplayReadiness.CONDITIONALLY_READY_FOR_ADJUSTED_REPLAY_INTEGRATION.value
    )
    assert readiness["unknown_factor_applied_as_one"] is False


def test_artifacts_are_deterministic_and_complete(tmp_path: Path) -> None:
    report = CompleteCorporateActionReport(
        contract_version="HTR-010B-v1.0.0",
        adjustment_policy_version="policy",
        production_influence=False,
        start_date=date(2016, 1, 1),
        end_date=date(2026, 7, 20),
        source_completeness=(),
        raw_event_census=(),
        canonical_events=(),
        event_lineage=(),
        duplicate_groups=(),
        rejected_events=(),
        adjustment_factors=(),
        cumulative_factors=(),
        identity_transitions=(),
        price_basis_intervals=(),
        adjusted_candle_summary=(),
        price_continuity=(),
        false_signal_contamination=(),
        identity_coverage_matrix=(),
        ytd_2026={"final_state": "YTD_PARTIAL_NOT_FULL_YEAR"},
        replay_readiness={
            "state": "READY_FOR_ADJUSTED_REPLAY_INTEGRATION",
            "blockers": [],
            "quarantined_identity_count": 0,
            "quarantined_interval_count": 0,
        },
        certification={},
        source_checksums=(),
        raw_candle_fingerprint="raw-hash",
        report_sha256="report-hash",
    )
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_paths = CompleteCorporateActionArtifactExporter().export(report, first)
    CompleteCorporateActionArtifactExporter().export(report, second)

    assert len(first_paths) == 36
    assert (first / "htr010b_certification.md").read_bytes() == (
        second / "htr010b_certification.md"
    ).read_bytes()
    executive = json.loads(
        (first / "htr010b_executive_report.json").read_text(encoding="utf-8")
    )
    assert executive["full_benchmark_replays"] == 0
    assert executive["production_influence"] is False


def test_cli_exposes_complete_dataset_command() -> None:
    result = CliRunner().invoke(
        historical_truth_app, ["complete-corporate-action-dataset", "--help"]
    )

    assert result.exit_code == 0
    assert "--verify-only" in result.output
    assert "--only-mixed-basis" in result.output


def test_production_influence_is_false() -> None:
    assert PRODUCTION_INFLUENCE is False
