from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from alpha.historical_truth.adjustment_replay_admission_cli import (
    adjustment_replay_admission_certify,
)
from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.complete_corporate_action_cli import (
    complete_corporate_action_dataset,
)
from alpha.historical_truth.complete_security_dataset_cli import (
    complete_security_dataset_certify,
)
from alpha.historical_truth.corporate_action_price_cli import (
    corporate_action_price_certify,
)
from alpha.historical_truth.event_sourced_universe_cli import (
    event_sourced_universe_certify,
)
from alpha.historical_truth.foundation_readiness_cli import (
    tier_a_foundation_readiness,
)
from alpha.historical_truth.integrity import HistoricalTruthIntegrityAudit
from alpha.historical_truth.lifecycle_session_cli import (
    lifecycle_session_semantics_certify,
)
from alpha.historical_truth.pilot import (
    DEFAULT_CROSS_ERA_DATES,
    HistoricalBackfillPilot,
)
from alpha.historical_truth.point_in_time_identity_cli import (
    point_in_time_universe_certify,
)
from alpha.historical_truth.population import HistoricalPopulationEngine
from alpha.historical_truth.replay_eligibility_integrity_cli import (
    replay_eligibility_integrity_audit,
)
from alpha.historical_truth.resumable import HistoricalTruthWarehouse
from alpha.historical_truth.security_population_repair_cli import (
    security_population_repair,
)
from alpha.historical_truth.snapshots import PointInTimeSnapshotEngine
from alpha.historical_truth.special_session_recovery_cli import (
    session_calendar_build,
    special_session_candle_recover,
)
from alpha.historical_truth.special_session_snapshot_parity_cli import (
    special_session_snapshot_repair,
)

historical_truth_app = typer.Typer(
    help="Build and audit official historical market truth."
)

historical_truth_app.command("event-sourced-universe-certify")(
    event_sourced_universe_certify
)
historical_truth_app.command("corporate-action-price-certify")(
    corporate_action_price_certify
)
historical_truth_app.command("complete-security-dataset-certify")(
    complete_security_dataset_certify
)
historical_truth_app.command("security-population-repair")(security_population_repair)
historical_truth_app.command("lifecycle-session-semantics-certify")(
    lifecycle_session_semantics_certify
)
historical_truth_app.command("tier-a-foundation-readiness")(tier_a_foundation_readiness)
historical_truth_app.command("complete-corporate-action-dataset")(
    complete_corporate_action_dataset
)
historical_truth_app.command("adjustment-replay-admission-certify")(
    adjustment_replay_admission_certify
)


def _parse_date(value: str, option_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(
            "must use ISO format YYYY-MM-DD",
            param_hint=option_name,
        ) from exc


def _parse_range(start: str, end: str) -> tuple[date, date]:
    start_date = _parse_date(start, "--start")
    end_date = _parse_date(end, "--end")
    if start_date > end_date:
        raise typer.BadParameter(
            "must be on or before --end",
            param_hint="--start",
        )
    return start_date, end_date
