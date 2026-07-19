from __future__ import annotations

import csv
import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path

from alpha.canonical_integrity_audit.models import (
    CANONICAL_POLICY_ID,
    LEGACY_DATASET_VERSION,
    CanonicalTradeEvent,
    FrozenPolicyManifest,
)
from alpha.canonical_universe_audit.models import CandidateOutcomeRecord
from alpha.provenance import (
    APPROVAL_POLICY_VERSION,
    ENTRY_TIMING_ENGINE_VERSION,
    RECOMMENDATION_ENGINE_VERSION,
    TRADE_PLAN_ENGINE_VERSION,
)

DEFAULT_ACU_DIRECTORY = Path(".alpha/acu/ALPHA_CANONICAL_v1.0")


def frozen_policy_manifest(*, source_commit: str | None = None) -> FrozenPolicyManifest:
    return FrozenPolicyManifest(
        policy_id=CANONICAL_POLICY_ID,
        source_commit=source_commit or _source_commit(),
        weights={
            "breakout_setup": "0.07",
            "candle_pattern": "0.08",
            "market_regime": "0.05",
            "price_structure": "0.20",
            "relative_strength": "0.13",
            "retracement": "0.10",
            "risk_volatility": "0.02",
            "sector_strength": "0.03",
            "trend_alignment": "0.15",
            "volume_confirmation": "0.17",
        },
        thresholds={
            "avoid": "40",
            "buy": "75",
            "sell": "below 40",
            "strong_buy": "90",
            "watchlist": "60",
        },
        setup_versions=(RECOMMENDATION_ENGINE_VERSION, "trade-setup-intelligence-v1"),
        entry_timing_version=ENTRY_TIMING_ENGINE_VERSION,
        trade_plan_version=TRADE_PLAN_ENGINE_VERSION,
        approval_policy_version=APPROVAL_POLICY_VERSION,
        outcome_definition_version="acu-stop-first-60-bar-v1",
        dataset_version=LEGACY_DATASET_VERSION,
        mte_provider_version="LEGACY_DATASET/PROVISIONAL",
    )


def load_canonical_events(
    directory: Path | str = DEFAULT_ACU_DIRECTORY,
) -> tuple[CanonicalTradeEvent, ...]:
    root = Path(directory)
    rankings = _csv_rows(root / "candidate_rankings.csv")
    gates = _csv_rows(root / "gate_attribution.csv")
    primary_gate = {
        (row["observed_on"], row["symbol"].upper()): row["gate_code"]
        for row in gates
        if row.get("primary", "").lower() == "true"
    }
    events = []
    for row in rankings:
        observed_on = date.fromisoformat(row["observed_on"])
        symbol = row["symbol"].upper()
        gate = primary_gate.get((row["observed_on"], symbol), "PASSED")
        events.append(
            CanonicalTradeEvent(
                candidate_id=f"{observed_on.isoformat()}|{symbol}",
                symbol=symbol,
                observed_on=observed_on,
                score=_decimal(row.get("score")),
                setup=row.get("setup_type", "UNKNOWN") or "UNKNOWN",
                setup_state=row.get("setup_stage", "UNKNOWN") or "UNKNOWN",
                strategy=row.get("setup_type", "UNKNOWN") or "UNKNOWN",
                entry=_decimal(row.get("entry_price")),
                stop=_decimal(row.get("initial_stop")),
                targets=(_decimal(row.get("target_1")), None, None),
                final_signal=row.get("final_signal", "UNKNOWN") or "UNKNOWN",
                final_gate=gate,
                rejection_reason=None if gate == "PASSED" else gate,
            )
        )
    return tuple(sorted(events, key=lambda item: (item.symbol, item.observed_on)))


def load_acu_outcomes(
    directory: Path | str = DEFAULT_ACU_DIRECTORY,
) -> tuple[CandidateOutcomeRecord, ...]:
    path = Path(directory) / "opportunity_capacity.json"
    if not path.exists():
        return ()
    import json
    from typing import cast

    decoded = cast(object, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(decoded, dict) or not isinstance(decoded.get("outcomes"), list):
        return ()
    rows = []
    for value in decoded["outcomes"]:
        if not isinstance(value, dict):
            continue
        realized_return = value.get("realized_return_pct")
        realized_r = value.get("realized_r")
        holding = value.get("holding_period_days")
        won = value.get("won")
        rows.append(
            CandidateOutcomeRecord(
                observed_on=date.fromisoformat(str(value["observed_on"])),
                symbol=str(value["symbol"]),
                entered=bool(value["entered"]),
                completed=bool(value["completed"]),
                won=won if isinstance(won, bool) else None,
                realized_return_pct=(
                    None if realized_return is None else Decimal(str(realized_return))
                ),
                realized_r=None if realized_r is None else Decimal(str(realized_r)),
                holding_period_days=None if holding is None else int(str(holding)),
                exit_reason=str(value["exit_reason"]),
                evidence_note=str(value["evidence_note"]),
            )
        )
    return tuple(rows)


def failed_runtime_dates(
    directory: Path | str = DEFAULT_ACU_DIRECTORY,
) -> tuple[date, ...]:
    rows = _csv_rows(Path(directory) / "daily_opportunities.csv")
    return tuple(
        date.fromisoformat(row["observed_on"])
        for row in rows
        if row.get("runtime_status") != "SUCCESS"
    )


def acu_funnel(directory: Path | str = DEFAULT_ACU_DIRECTORY) -> dict[str, int]:
    rows = _csv_rows(Path(directory) / "opportunity_capacity.csv")
    if not rows:
        return {}
    row = rows[0]
    keys = (
        "canonical_runtime_failure_days",
        "scored_candidates",
        "total_approval_candidates",
        "total_institutional_approvals",
        "total_portfolio_eligible",
    )
    return {key: int(row.get(key, "0") or "0") for key in keys}


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


def _csv_rows(path: Path) -> tuple[dict[str, str], ...]:
    if not path.exists():
        return ()
    with path.open(encoding="utf-8", newline="") as handle:
        return tuple(dict(row) for row in csv.DictReader(handle))


def _decimal(value: str | None) -> Decimal | None:
    if value is None or not value.strip():
        return None
    return Decimal(value)


__all__ = [
    "DEFAULT_ACU_DIRECTORY",
    "acu_funnel",
    "failed_runtime_dates",
    "frozen_policy_manifest",
    "load_acu_outcomes",
    "load_canonical_events",
]
