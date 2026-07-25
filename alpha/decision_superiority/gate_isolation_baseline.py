"""Frozen baseline reconstruction for DSI-002 gate isolation."""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from alpha.decision_superiority.gate_isolation_models import FrozenCandidateKey


class GateIsolationBaselineError(ValueError):
    """Raised when governed baseline lineage cannot be reconciled."""


@dataclass(frozen=True, slots=True)
class FrozenBaselineCandidate:
    """One fully reconciled point-in-time baseline candidate."""

    candidate: FrozenCandidateKey
    observed_failure_codes: tuple[str, ...]
    resolved_outcome: bool
    outcome_status: str
    realized_return_pct: Decimal | None
    realized_r: Decimal | None
    b5_present: bool
    b7_present: bool
    b10_present: bool
    dsi001_present: bool

    def __post_init__(self) -> None:
        if (
            tuple(sorted(set(self.observed_failure_codes)))
            != self.observed_failure_codes
        ):
            raise ValueError("observed_failure_codes must be unique and sorted")
        if not self.outcome_status.strip():
            raise ValueError("outcome_status cannot be empty")
        if not all(
            (
                self.b5_present,
                self.b7_present,
                self.b10_present,
                self.dsi001_present,
            )
        ):
            raise ValueError(
                "baseline candidate must be present in every governed source"
            )
        if self.resolved_outcome and self.realized_return_pct is None:
            raise ValueError("resolved outcome requires realized_return_pct")


@dataclass(frozen=True, slots=True)
class FrozenBaselinePopulation:
    """Deterministically ordered candidate population and parity diagnostics."""

    candidates: tuple[FrozenBaselineCandidate, ...]
    raw_candidate_count: int
    adjusted_candidate_count: int
    raw_adjusted_identity_mismatch_count: int

    def __post_init__(self) -> None:
        keys = tuple(item.candidate for item in self.candidates)
        if keys != tuple(sorted(keys)):
            raise ValueError("baseline candidates must be deterministically sorted")
        if len(set(keys)) != len(keys):
            raise ValueError("baseline candidate identities must be unique")
        if self.raw_adjusted_identity_mismatch_count < 0:
            raise ValueError("identity mismatch count cannot be negative")


@dataclass(frozen=True, slots=True)
class FrozenBaselineSourcePaths:
    """Selected bound ledgers used to reconstruct DSI-002 baseline state."""

    b5_candidate_ledger: Path
    b7_outcome_ledger: Path
    b10_decision_ledger: Path
    dsi001_candidate_ledger: Path


class FrozenBaselineReconstructor:
    """Join governed ledgers using the exact frozen candidate identity."""

    def reconstruct(
        self,
        paths: FrozenBaselineSourcePaths,
    ) -> FrozenBaselinePopulation:
        b5 = _index_rows(paths.b5_candidate_ledger, "B5")
        b7 = _index_rows(paths.b7_outcome_ledger, "B7")
        b10 = _index_rows(paths.b10_decision_ledger, "B10")
        dsi001 = _index_rows(paths.dsi001_candidate_ledger, "DSI001")

        populations = {
            "B5": set(b5),
            "B7": set(b7),
            "B10": set(b10),
            "DSI001": set(dsi001),
        }
        canonical_keys = populations["DSI001"]
        for source, keys in populations.items():
            if keys != canonical_keys:
                missing = sorted(canonical_keys - keys)
                extra = sorted(keys - canonical_keys)
                raise GateIsolationBaselineError(
                    f"{source}_IDENTITY_LINEAGE_MISMATCH:"
                    f"missing={len(missing)}:extra={len(extra)}"
                )

        candidates = tuple(
            self._candidate(
                key=key,
                b5=b5[key],
                b7=b7[key],
                b10=b10[key],
                dsi001=dsi001[key],
            )
            for key in sorted(canonical_keys)
        )
        raw = {
            item.candidate for item in candidates if item.candidate.price_view == "RAW"
        }
        adjusted = {
            item.candidate
            for item in candidates
            if item.candidate.price_view == "ADJUSTED"
        }
        raw_core = {_arm_neutral_key(key) for key in raw}
        adjusted_core = {_arm_neutral_key(key) for key in adjusted}
        mismatch_count = len(raw_core ^ adjusted_core)
        return FrozenBaselinePopulation(
            candidates=candidates,
            raw_candidate_count=len(raw),
            adjusted_candidate_count=len(adjusted),
            raw_adjusted_identity_mismatch_count=mismatch_count,
        )

    def _candidate(
        self,
        *,
        key: FrozenCandidateKey,
        b5: Mapping[str, str],
        b7: Mapping[str, str],
        b10: Mapping[str, str],
        dsi001: Mapping[str, str],
    ) -> FrozenBaselineCandidate:
        failures = _failure_codes(dsi001)
        b5_failures = _failure_codes(b5)
        if b5_failures and b5_failures != failures:
            raise GateIsolationBaselineError(
                f"GATE_FAILURE_LINEAGE_MISMATCH:{_key_text(key)}"
            )
        if _truthy(b10.get("point_in_time_leakage")):
            raise GateIsolationBaselineError(
                f"POINT_IN_TIME_LEAKAGE_DETECTED:{_key_text(key)}"
            )
        resolved = _truthy(dsi001.get("resolved_outcome") or b7.get("resolved_outcome"))
        realized_return = _decimal_or_none(
            dsi001.get("realized_return_pct")
            or b7.get("realized_return_pct")
            or b7.get("return_pct")
        )
        realized_r = _decimal_or_none(dsi001.get("realized_r") or b7.get("realized_r"))
        status = b7.get("outcome_status") or (
            "RESOLVED" if resolved else "OUTCOME_UNAVAILABLE"
        )
        return FrozenBaselineCandidate(
            candidate=key,
            observed_failure_codes=failures,
            resolved_outcome=resolved,
            outcome_status=status,
            realized_return_pct=realized_return,
            realized_r=realized_r,
            b5_present=True,
            b7_present=True,
            b10_present=True,
            dsi001_present=True,
        )


def _index_rows(path: Path, source: str) -> dict[FrozenCandidateKey, dict[str, str]]:
    if not path.is_file():
        raise GateIsolationBaselineError(f"{source}_LEDGER_MISSING:{path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = tuple(dict(row) for row in csv.DictReader(handle))
    result: dict[FrozenCandidateKey, dict[str, str]] = {}
    for row in rows:
        key = _candidate_key(row, source)
        if key in result:
            raise GateIsolationBaselineError(
                f"{source}_DUPLICATE_CANDIDATE_IDENTITY:{_key_text(key)}"
            )
        result[key] = row
    return result


def _candidate_key(row: Mapping[str, str], source: str) -> FrozenCandidateKey:
    values = {
        "price_view": str(row.get("price_view") or "").strip().upper(),
        "observed_on": str(row.get("observed_on") or "").strip(),
        "symbol": str(row.get("symbol") or "").strip().upper(),
        "input_fingerprint": str(
            row.get("input_fingerprint") or row.get("fingerprint_key") or ""
        ).strip(),
    }
    try:
        return FrozenCandidateKey(**values)
    except (TypeError, ValueError) as exc:
        raise GateIsolationBaselineError(
            f"{source}_INVALID_CANDIDATE_IDENTITY:{exc}"
        ) from exc


def _failure_codes(row: Mapping[str, str]) -> tuple[str, ...]:
    value = str(
        row.get("failure_codes")
        or row.get("rejection_codes")
        or row.get("default_rejection_codes")
        or ""
    ).strip()
    if not value:
        return ()
    parsed: object
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = [item.strip() for item in value.replace("|", ",").split(",")]
    if not isinstance(parsed, list):
        raise GateIsolationBaselineError("FAILURE_CODES_NOT_A_LIST")
    codes = tuple(sorted({str(item).strip() for item in parsed if str(item).strip()}))
    return codes


def _decimal_or_none(value: str | None) -> Decimal | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise GateIsolationBaselineError(f"INVALID_DECIMAL:{text}") from exc


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _arm_neutral_key(key: FrozenCandidateKey) -> tuple[str, str, str]:
    return key.observed_on, key.symbol, key.input_fingerprint


def _key_text(key: FrozenCandidateKey) -> str:
    return "|".join(
        (key.price_view, key.observed_on, key.symbol, key.input_fingerprint)
    )


__all__ = [
    "FrozenBaselineCandidate",
    "FrozenBaselinePopulation",
    "FrozenBaselineReconstructor",
    "FrozenBaselineSourcePaths",
    "GateIsolationBaselineError",
]
