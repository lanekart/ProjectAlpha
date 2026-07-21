"""Load governed replay identity and corporate-action artifacts."""

from __future__ import annotations

import ast
import csv
import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

from alpha.recovery.corporate_actions import (
    CorporateActionEvent,
    CorporateActionStatus,
    CorporateActionTimeline,
    CorporateActionType,
)
from alpha.recovery.security_timeline import (
    SecurityIdentityRecord,
    SecurityIdentityTimeline,
)

GOVERNED_INPUT_CONTRACT_VERSION = "HTR-005-inputs-v1.0.0"


@dataclass(frozen=True, slots=True)
class GovernedReplayInputManifest:
    """Immutable lineage for the HTR-002 and HTR-003 input artifacts."""

    identity_path: str
    corporate_action_path: str
    identity_sha256: str
    corporate_action_sha256: str
    identity_count: int
    corporate_action_count: int
    unresolved_action_ids: tuple[str, ...]
    security_ids: tuple[str, ...]
    contract_version: str = GOVERNED_INPUT_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.identity_count <= 0:
            raise ValueError("governed replay inputs require at least one identity")
        if self.corporate_action_count < 0:
            raise ValueError("corporate action count cannot be negative")
        _validate_sha256(self.identity_sha256, "identity artifact")
        _validate_sha256(self.corporate_action_sha256, "corporate action artifact")
        if not self.security_ids:
            raise ValueError("governed replay inputs require stable security IDs")
        if self.contract_version != GOVERNED_INPUT_CONTRACT_VERSION:
            raise ValueError("unsupported governed replay input contract")

    @property
    def manifest_sha256(self) -> str:
        """Return a deterministic digest over the input lineage manifest."""

        payload = self.as_dict(include_digest=False)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def as_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        """Return a stable JSON-compatible manifest payload."""

        payload = asdict(self)
        payload["unresolved_action_ids"] = list(self.unresolved_action_ids)
        payload["security_ids"] = list(self.security_ids)
        if include_digest:
            payload["manifest_sha256"] = self.manifest_sha256
        return payload


@dataclass(frozen=True, slots=True)
class GovernedReplayInputs:
    """Canonical identity and action timelines plus exact artifact lineage."""

    identities: SecurityIdentityTimeline
    actions: CorporateActionTimeline
    manifest: GovernedReplayInputManifest

    def __post_init__(self) -> None:
        if len(self.identities.records) != self.manifest.identity_count:
            raise ValueError("identity manifest count does not match loaded timeline")
        if len(self.actions.events) != self.manifest.corporate_action_count:
            raise ValueError(
                "corporate action manifest count does not match loaded timeline"
            )


def load_governed_replay_inputs(
    *,
    identity_path: Path,
    corporate_action_path: Path,
) -> GovernedReplayInputs:
    """Load HTR-002/003 artifacts and derive historical symbol continuity."""

    identity_rows = _read_records(identity_path, "identity")
    action_rows = _read_records(
        corporate_action_path,
        "corporate action",
        allow_empty=True,
    )
    actions = CorporateActionTimeline(_action_event(row) for row in action_rows)
    aliases = _action_aliases(actions.events)
    identities = SecurityIdentityTimeline(
        _identity_record(row, aliases=aliases) for row in identity_rows
    )
    unresolved = tuple(
        event.event_id
        for event in actions.events
        if event.status is CorporateActionStatus.UNRESOLVED
    )
    manifest = GovernedReplayInputManifest(
        identity_path=str(identity_path),
        corporate_action_path=str(corporate_action_path),
        identity_sha256=_file_sha256(identity_path),
        corporate_action_sha256=_file_sha256(corporate_action_path),
        identity_count=len(identities.records),
        corporate_action_count=len(actions.events),
        unresolved_action_ids=unresolved,
        security_ids=tuple(
            sorted({record.security_id for record in identities.records})
        ),
    )
    return GovernedReplayInputs(
        identities=identities,
        actions=actions,
        manifest=manifest,
    )


def _identity_record(
    row: Mapping[str, object],
    *,
    aliases: Mapping[str, tuple[str, ...]],
) -> SecurityIdentityRecord:
    security_id = _required_text(
        row,
        "security_id",
        fallback=_text(row.get("record_key")),
    )
    symbol = _required_text(row, "symbol")
    historical = set(_string_tuple(row.get("historical_symbols")))
    historical.update(aliases.get(security_id, ()))
    historical.discard(symbol.strip().upper())
    evidence_ids = _string_tuple(row.get("evidence_ids"))
    return SecurityIdentityRecord(
        security_id=security_id,
        symbol=symbol,
        exchange=_optional_text(row.get("exchange")),
        effective_from=_optional_date(
            row.get("effective_from") or row.get("listing_date")
        ),
        effective_to=_optional_date(
            row.get("effective_to") or row.get("delisting_date")
        ),
        historical_symbols=tuple(sorted(historical)),
        evidence_ids=evidence_ids,
        recovery_version=_text(row.get("recovery_version")) or "HTR-002-v1.0.0",
    )


def _action_event(row: Mapping[str, object]) -> CorporateActionEvent:
    action_type = CorporateActionType(_required_text(row, "action_type").upper())
    status = CorporateActionStatus(_required_text(row, "status").upper())
    effective = _required_date(row, "effective_date")
    announced = _optional_date(row.get("announced_at")) or effective
    return CorporateActionEvent(
        event_id=_required_text(row, "event_id"),
        security_id=_required_text(row, "security_id"),
        symbol=_required_text(row, "symbol").upper(),
        action_type=action_type,
        effective_date=effective,
        announced_at=announced,
        price_factor=_optional_decimal(row.get("price_factor")),
        volume_factor=_optional_decimal(row.get("volume_factor")),
        old_symbol=_optional_upper_text(row.get("old_symbol")),
        new_symbol=_optional_upper_text(row.get("new_symbol")),
        cash_amount=_optional_decimal(row.get("cash_amount")),
        ratio_numerator=_optional_decimal(row.get("ratio_numerator")),
        ratio_denominator=_optional_decimal(row.get("ratio_denominator")),
        status=status,
        confidence=_optional_decimal(row.get("confidence")) or Decimal("0"),
        evidence_ids=_string_tuple(row.get("evidence_ids")),
        source=_text(row.get("source")) or "corporate_action_artifact",
    )


def _action_aliases(
    events: Iterable[CorporateActionEvent],
) -> Mapping[str, tuple[str, ...]]:
    aliases: dict[str, set[str]] = defaultdict(set)
    for event in events:
        if event.action_type is not CorporateActionType.SYMBOL_CHANGE:
            continue
        for symbol in (event.symbol, event.old_symbol, event.new_symbol):
            if symbol:
                aliases[event.security_id].add(symbol.strip().upper())
    return {
        security_id: tuple(sorted(symbols))
        for security_id, symbols in sorted(aliases.items())
    }


def _read_records(
    path: Path,
    label: str,
    *,
    allow_empty: bool = False,
) -> tuple[Mapping[str, object], ...]:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()
    records: tuple[Mapping[str, object], ...]
    if suffix == ".csv":
        with path.open(encoding="utf-8", newline="") as handle:
            records = tuple(dict(row) for row in csv.DictReader(handle))
    elif suffix == ".jsonl":
        records = tuple(
            cast(Mapping[str, object], json.loads(line))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    elif suffix == ".json":
        records = _json_records(json.loads(path.read_text(encoding="utf-8")))
    else:
        raise ValueError(f"unsupported {label} artifact format: {path}")
    if not records and not allow_empty:
        raise ValueError(f"{label} artifact contains no records: {path}")
    if any(not isinstance(row, Mapping) for row in records):
        raise ValueError(f"{label} artifact must contain mapping records: {path}")
    return tuple(dict(row) for row in records)


def _json_records(payload: object) -> tuple[Mapping[str, object], ...]:
    if isinstance(payload, Mapping):
        nested = next(
            (
                payload.get(key)
                for key in ("records", "data", "canonical_preview", "timeline")
                if isinstance(payload.get(key), list)
            ),
            None,
        )
        payload = nested if nested is not None else [payload]
    if not isinstance(payload, list):
        raise ValueError("governed replay JSON artifact must contain a record list")
    if not all(isinstance(item, Mapping) for item in payload):
        raise ValueError("governed replay JSON artifact contains a non-record item")
    return tuple(cast(Mapping[str, object], item) for item in payload)


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, float) and value != value:
        return ()
    if isinstance(value, (tuple, list, set)):
        return tuple(sorted({str(item).strip() for item in value if str(item).strip()}))
    text = str(value).strip()
    if not text or text in {"[]", "()", "{}"}:
        return ()
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        try:
            decoded = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            decoded = text.replace("|", ",").replace(";", ",").split(",")
    if not isinstance(decoded, (tuple, list, set)):
        raise ValueError("artifact sequence field must contain a sequence")
    return tuple(sorted({str(item).strip() for item in decoded if str(item).strip()}))


def _required_text(
    row: Mapping[str, object],
    key: str,
    *,
    fallback: str = "",
) -> str:
    text = _text(row.get(key)) or fallback.strip()
    if not text:
        raise ValueError(f"governed replay artifact is missing {key}")
    return text


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _optional_text(value: object) -> str | None:
    text = _text(value)
    return text or None


def _optional_upper_text(value: object) -> str | None:
    text = _optional_text(value)
    return text.upper() if text else None


def _required_date(row: Mapping[str, object], key: str) -> date:
    value = _optional_date(row.get(key))
    if value is None:
        raise ValueError(f"governed replay artifact is missing {key}")
    return value


def _optional_date(value: object) -> date | None:
    text = _text(value)
    if not text:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(text[:10])


def _optional_decimal(value: object) -> Decimal | None:
    text = _text(value)
    if not text or text.lower() in {"none", "null", "nan"}:
        return None
    try:
        result = Decimal(text)
    except InvalidOperation as error:
        raise ValueError(f"invalid governed replay decimal value: {value!r}") from error
    if not result.is_finite():
        raise ValueError(f"invalid governed replay decimal value: {value!r}")
    return result


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_sha256(value: str, label: str) -> None:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{label} SHA-256 is invalid")


__all__ = [
    "GOVERNED_INPUT_CONTRACT_VERSION",
    "GovernedReplayInputManifest",
    "GovernedReplayInputs",
    "load_governed_replay_inputs",
]
