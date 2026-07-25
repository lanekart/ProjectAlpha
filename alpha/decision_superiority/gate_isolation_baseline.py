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
        if not self.b5_present or not self.dsi001_present:
            raise ValueError(
                "baseline candidate must be present in B5 and DSI-001"
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


_PartialCandidateKey = tuple[str, str, str]


class FrozenBaselineReconstructor:
    """Join governed ledgers using canonical DSI-001 candidate identity."""

    def reconstruct(
        self,
        paths: FrozenBaselineSourcePaths,
    ) -> FrozenBaselinePopulation:
        b5 = _index_rows(paths.b5_candidate_ledger, "B5")
        dsi001 = _index_rows(paths.dsi001_candidate_ledger, "DSI001")
        b7 = _index_partial_rows(paths.b7_outcome_ledger, "B7")
        b10 = _index_partial_rows(paths.b10_decision_ledger, "B10")

        canonical_keys = set(dsi001)
        if set(b5) != canonical_keys:
            missing = sorted(canonical_keys - set(b5))
            extra = sorted(set(b5) - canonical_keys)
            raise GateIsolationBaselineError(
                "B5_IDENTITY_LINEAGE_MISMATCH:"
                f"missing={len(missing)}:extra={len(extra)}"
            )

        canonical_partial = _canonical_partial_identity_map(canonical_keys)
        _validate_partial_subset("B7", set(b7), set(canonical_partial))
        _validate_partial_subset("B10", set(b10), set(canonical_partial))

        candidates = tuple(
            self._candidate(
                key=key,
                b5=b5[key],
                b7=_optional_bridged_row(
                    source="B7",
                    candidate=key,
                    row=b7.get(_partial_key_from_candidate(key)),
                ),
                b10=_optional_bridged_row(
                    source="B10",
                    candidate=key,
                    row=b10.get(_partial_key_from_candidate(key)),
                ),
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
        b7: Mapping[str, str] | None,
        b10: Mapping[str, str] | None,
        dsi001: Mapping[str, str],
    ) -> FrozenBaselineCandidate:
        b7_row: Mapping[str, str] = {} if b7 is None else b7
        b10_row: Mapping[str, str] = {} if b10 is None else b10
        failures = _failure_codes(dsi001)
        b5_failures = _failure_codes(b5)
        if b5_failures and b5_failures != failures:
            raise GateIsolationBaselineError(
                f"GATE_FAILURE_LINEAGE_MISMATCH:{_key_text(key)}"
            )
        if _truthy(b10_row.get("point_in_time_leakage")):
            raise GateIsolationBaselineError(
                f"POINT_IN_TIME_LEAKAGE_DETECTED:{_key_text(key)}"
            )
        resolved = _truthy(
            dsi001.get("resolved_outcome") or b7_row.get("resolved_outcome")
        )
        realized_return = _decimal_or_none(
            dsi001.get("realized_return_pct")
            or b7_row.get("realized_return_pct")
            or b7_row.get("return_pct")
        )
        realized_r = _decimal_or_none(
            dsi001.get("realized_r") or b7_row.get("realized_r")
        )
        status = (
            b7_row.get("outcome_status")
            or dsi001.get("outcome_status")
            or ("RESOLVED" if resolved else "OUTCOME_UNAVAILABLE")
        )
        return FrozenBaselineCandidate(
            candidate=key,
            observed_failure_codes=failures,
            resolved_outcome=resolved,
            outcome_status=status,
            realized_return_pct=realized_return,
            realized_r=realized_r,
            b5_present=True,
            b7_present=b7 is not None,
            b10_present=b10 is not None,
            dsi001_present=True,
        )


def _index_rows(
    path: Path,
    source: str,
) -> dict[FrozenCandidateKey, dict[str, str]]:
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


def _index_partial_rows(
    path: Path,
    source: str,
) -> dict[_PartialCandidateKey, dict[str, str]]:
    if not path.is_file():
        raise GateIsolationBaselineError(f"{source}_LEDGER_MISSING:{path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = tuple(dict(row) for row in csv.DictReader(handle))
    result: dict[_PartialCandidateKey, dict[str, str]] = {}
    for row in rows:
        key = _partial_key_from_row(row, source)
        if key in result:
            raise GateIsolationBaselineError(
                f"{source}_DUPLICATE_CANDIDATE_IDENTITY:{'|'.join(key)}"
            )
        result[key] = row
    return result


def _canonical_partial_identity_map(
    canonical_keys: set[FrozenCandidateKey],
) -> dict[_PartialCandidateKey, FrozenCandidateKey]:
    result: dict[_PartialCandidateKey, FrozenCandidateKey] = {}
    for candidate in sorted(canonical_keys):
        key = _partial_key_from_candidate(candidate)
        existing = result.get(key)
        if (
            existing is not None
            and existing.input_fingerprint != candidate.input_fingerprint
        ):
            raise GateIsolationBaselineError(
                f"AMBIGUOUS_CANONICAL_IDENTITY:{'|'.join(key)}"
            )
        result[key] = candidate
    return result


def _validate_partial_subset(
    source: str,
    observed: set[_PartialCandidateKey],
    canonical: set[_PartialCandidateKey],
) -> None:
    extra = sorted(observed - canonical)
    if extra:
        raise GateIsolationBaselineError(
            f"{source}_IDENTITY_LINEAGE_MISMATCH:missing=0:extra={len(extra)}"
        )


def _optional_bridged_row(
    *,
    source: str,
    candidate: FrozenCandidateKey,
    row: Mapping[str, str] | None,
) -> dict[str, str] | None:
    if row is None:
        return None
    return _bridge_partial_row(
        source=source,
        candidate=candidate,
        row=row,
    )


def _bridge_partial_row(
    *,
    source: str,
    candidate: FrozenCandidateKey,
    row: Mapping[str, str],
) -> dict[str, str]:
    fingerprint = str(
        row.get("input_fingerprint") or row.get("fingerprint_key") or ""
    ).strip()
    if fingerprint and fingerprint != candidate.input_fingerprint:
        raise GateIsolationBaselineError(
            f"{source}_FINGERPRINT_MISMATCH:{_key_text(candidate)}"
        )
    bridged = dict(row)
    bridged["input_fingerprint"] = candidate.input_fingerprint
    return bridged


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


def _partial_key_from_row(
    row: Mapping[str, str],
    source: str,
) -> _PartialCandidateKey:
    key = (
        str(row.get("price_view") or "").strip().upper(),
        str(row.get("observed_on") or "").strip(),
        str(row.get("symbol") or "").strip().upper(),
    )
    if any(not value for value in key):
        raise GateIsolationBaselineError(f"{source}_INVALID_CANDIDATE_IDENTITY")
    return key


def _partial_key_from_candidate(
    candidate: FrozenCandidateKey,
) -> _PartialCandidateKey:
    return candidate.price_view, candidate.observed_on, candidate.symbol


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
    return tuple(sorted({str(item).strip() for item in parsed if str(item).strip()}))


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
