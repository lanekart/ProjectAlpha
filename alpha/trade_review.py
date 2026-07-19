from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

_ZERO = Decimal("0")
_TWO = Decimal("0.01")
DEFAULT_USER_TRADE_JOURNAL_PATH = Path(".alpha/user_trade_journal.json")


@dataclass(frozen=True, slots=True)
class LiveTradeReview:
    symbol: str
    trade_quality: str
    risk_reward_ratio: Decimal | None
    risk_percent: Decimal | None
    target_return_percent: Decimal | None
    synopsis: str
    warnings: tuple[str, ...]
    next_actions: tuple[str, ...]
    entry_discipline: str
    stop_placement: str
    chased: bool
    invalidation_review: str


@dataclass(frozen=True, slots=True)
class UserTradeJournalRecord:
    trade_id: str
    reviewed_at: datetime
    symbol: str
    entry: Decimal
    stop: Decimal
    target: Decimal
    quantity: Decimal | None
    thesis: str | None
    alpha_entry: Decimal | None
    alpha_stop: Decimal | None
    alpha_target: Decimal | None
    invalidation_respected: bool | None
    review: LiveTradeReview

    def as_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "reviewed_at": self.reviewed_at.isoformat(),
            "symbol": self.symbol,
            "entry": str(self.entry),
            "stop": str(self.stop),
            "target": str(self.target),
            "quantity": _text(self.quantity),
            "thesis": self.thesis,
            "alpha_entry": _text(self.alpha_entry),
            "alpha_stop": _text(self.alpha_stop),
            "alpha_target": _text(self.alpha_target),
            "invalidation_respected": self.invalidation_respected,
            "review": _review_dict(self.review),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> UserTradeJournalRecord:
        return cls(
            trade_id=str(payload["trade_id"]),
            reviewed_at=datetime.fromisoformat(str(payload["reviewed_at"])),
            symbol=str(payload["symbol"]),
            entry=Decimal(str(payload["entry"])),
            stop=Decimal(str(payload["stop"])),
            target=Decimal(str(payload["target"])),
            quantity=_decimal_or_none(payload.get("quantity")),
            thesis=_optional_text(payload.get("thesis")),
            alpha_entry=_decimal_or_none(payload.get("alpha_entry")),
            alpha_stop=_decimal_or_none(payload.get("alpha_stop")),
            alpha_target=_decimal_or_none(payload.get("alpha_target")),
            invalidation_respected=payload.get("invalidation_respected"),
            review=_review_from_dict(payload["review"]),
        )


class UserTradeJournalRepository:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = resolve_user_trade_journal_path(path)

    def save(self, record: UserTradeJournalRecord) -> None:
        existing = {item.trade_id: item for item in self.load()}
        existing[record.trade_id] = record
        self._write(tuple(existing.values()))

    def load(self) -> tuple[UserTradeJournalRecord, ...]:
        if not self.path.exists():
            return ()
        raw = self.path.read_text(encoding="utf-8").strip()
        if not raw:
            return ()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return ()
        records = payload.get("trades", [])
        if not isinstance(records, list):
            return ()
        return tuple(
            sorted(
                (
                    UserTradeJournalRecord.from_dict(record)
                    for record in records
                    if isinstance(record, dict)
                ),
                key=lambda record: (record.reviewed_at, record.symbol),
            )
        )

    def _write(self, records: tuple[UserTradeJournalRecord, ...]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"trades": [record.as_dict() for record in records]}
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


class LiveTradeReviewEngine:
    def review(
        self,
        *,
        symbol: str,
        entry: Decimal,
        stop: Decimal,
        target: Decimal,
        quantity: Decimal | None = None,
        thesis: str | None = None,
        alpha_entry: Decimal | None = None,
        alpha_stop: Decimal | None = None,
        alpha_target: Decimal | None = None,
        invalidation_respected: bool | None = None,
    ) -> LiveTradeReview:
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol cannot be empty")
        if entry <= _ZERO:
            raise ValueError("entry must be positive")
        if stop >= entry:
            raise ValueError("stop must be below entry for a long trade")
        if target <= entry:
            raise ValueError("target must be above entry for a long trade")
        risk = entry - stop
        reward = target - entry
        risk_reward = (reward / risk).quantize(_TWO, rounding=ROUND_HALF_UP)
        risk_percent = (risk / entry * Decimal("100")).quantize(
            _TWO,
            rounding=ROUND_HALF_UP,
        )
        target_return = (reward / entry * Decimal("100")).quantize(
            _TWO,
            rounding=ROUND_HALF_UP,
        )
        chased = _chased(entry=entry, alpha_entry=alpha_entry)
        entry_discipline = _entry_discipline(chased=chased, alpha_entry=alpha_entry)
        stop_placement = _stop_placement(stop=stop, alpha_stop=alpha_stop)
        invalidation_review = _invalidation_review(invalidation_respected)
        warnings = _warnings(
            risk_reward=risk_reward,
            risk_percent=risk_percent,
            thesis=thesis,
            chased=chased,
            stop_placement=stop_placement,
        )
        quality = _quality(
            risk_reward=risk_reward,
            risk_percent=risk_percent,
            chased=chased,
            invalidation_respected=invalidation_respected,
        )
        position_risk = (
            (risk * quantity).quantize(_TWO, rounding=ROUND_HALF_UP)
            if quantity is not None
            else None
        )
        synopsis = (
            f"{normalized_symbol} trade quality is {quality}. Entry {entry}, "
            f"stop {stop}, target {target}, reward/risk {risk_reward}R"
        )
        if position_risk is not None:
            synopsis += f", position risk {position_risk}"
        synopsis += (
            f". Entry discipline is {entry_discipline.lower()}; "
            f"stop placement is {stop_placement.lower()}."
        )
        return LiveTradeReview(
            symbol=normalized_symbol,
            trade_quality=quality,
            risk_reward_ratio=risk_reward,
            risk_percent=risk_percent,
            target_return_percent=target_return,
            synopsis=synopsis,
            warnings=warnings,
            next_actions=_next_actions(warnings=warnings),
            entry_discipline=entry_discipline,
            stop_placement=stop_placement,
            chased=chased,
            invalidation_review=invalidation_review,
        )

    def journal_record(
        self,
        *,
        symbol: str,
        entry: Decimal,
        stop: Decimal,
        target: Decimal,
        quantity: Decimal | None = None,
        thesis: str | None = None,
        alpha_entry: Decimal | None = None,
        alpha_stop: Decimal | None = None,
        alpha_target: Decimal | None = None,
        invalidation_respected: bool | None = None,
        reviewed_at: datetime | None = None,
    ) -> UserTradeJournalRecord:
        timestamp = _normalize_datetime(reviewed_at or datetime.now(tz=UTC))
        review = self.review(
            symbol=symbol,
            entry=entry,
            stop=stop,
            target=target,
            quantity=quantity,
            thesis=thesis,
            alpha_entry=alpha_entry,
            alpha_stop=alpha_stop,
            alpha_target=alpha_target,
            invalidation_respected=invalidation_respected,
        )
        return UserTradeJournalRecord(
            trade_id=_trade_id(review.symbol, timestamp),
            reviewed_at=timestamp,
            symbol=review.symbol,
            entry=entry,
            stop=stop,
            target=target,
            quantity=quantity,
            thesis=_optional_text(thesis),
            alpha_entry=alpha_entry,
            alpha_stop=alpha_stop,
            alpha_target=alpha_target,
            invalidation_respected=invalidation_respected,
            review=review,
        )


def render_live_trade_review(review: LiveTradeReview) -> tuple[str, ...]:
    lines = [
        "Live Trade Review",
        f"Symbol: {review.symbol}",
        f"Trade Quality: {review.trade_quality}",
        f"Entry Discipline: {review.entry_discipline}",
        f"Stop Placement: {review.stop_placement}",
        f"Chased: {'Yes' if review.chased else 'No'}",
        f"Invalidation: {review.invalidation_review}",
        f"Reward/Risk: {_metric(review.risk_reward_ratio)}R",
        f"Risk %: {_metric(review.risk_percent)}",
        f"Target Return %: {_metric(review.target_return_percent)}",
        f"Synopsis: {review.synopsis}",
        "Warnings:",
    ]
    lines.extend(f"- {warning}" for warning in review.warnings or ("none",))
    lines.append("Next Actions:")
    lines.extend(f"- {action}" for action in review.next_actions)
    return tuple(lines)


def render_user_trade_journal(
    records: tuple[UserTradeJournalRecord, ...],
) -> tuple[str, ...]:
    lines = ["User Trade Journal", f"Trades Reviewed: {len(records)}"]
    if not records:
        lines.append("- none")
        return tuple(lines)
    for index, record in enumerate(records, start=1):
        lines.append(f"{index}. {record.symbol} — {record.review.trade_quality}")
        lines.append(f"   Reviewed: {record.reviewed_at.date().isoformat()}")
        lines.append(
            f"   Entry/Stop/Target: {record.entry} / {record.stop} / {record.target}"
        )
        lines.append(f"   Reward/Risk: {_metric(record.review.risk_reward_ratio)}R")
        lines.append(f"   Entry Discipline: {record.review.entry_discipline}")
        lines.append(f"   Stop Placement: {record.review.stop_placement}")
    return tuple(lines)


def render_user_trade_journal_summary(
    records: tuple[UserTradeJournalRecord, ...],
) -> tuple[str, ...]:
    high = sum(1 for record in records if record.review.trade_quality == "HIGH")
    medium = sum(1 for record in records if record.review.trade_quality == "MEDIUM")
    low = sum(1 for record in records if record.review.trade_quality == "LOW")
    chased = sum(1 for record in records if record.review.chased)
    average_rr = _average(
        tuple(
            record.review.risk_reward_ratio
            for record in records
            if record.review.risk_reward_ratio is not None
        )
    )
    return (
        "User Trade Journal Summary",
        f"Trades Reviewed: {len(records)}",
        f"High Quality: {high}",
        f"Medium Quality: {medium}",
        f"Low Quality: {low}",
        f"Chased Trades: {chased}",
        f"Average Reward/Risk: {_metric(average_rr)}R",
    )


def resolve_user_trade_journal_path(path: Path | str | None = None) -> Path:
    if path is not None:
        return Path(path)
    configured = os.environ.get("ALPHA_USER_TRADE_JOURNAL")
    if configured:
        return Path(configured)
    return DEFAULT_USER_TRADE_JOURNAL_PATH


def _warnings(
    *,
    risk_reward: Decimal,
    risk_percent: Decimal,
    thesis: str | None,
    chased: bool,
    stop_placement: str,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if risk_reward < Decimal("2"):
        warnings.append(
            "Reward/risk is below 2R; trade needs a better entry or target."
        )
    if risk_percent > Decimal("8"):
        warnings.append("Stop distance is wide; position size should be reduced.")
    if thesis is None or not thesis.strip():
        warnings.append("Trade thesis was not provided.")
    if chased:
        warnings.append("Entry appears chased versus Alpha's planned entry.")
    if stop_placement == "LOOSER_THAN_ALPHA":
        warnings.append("Stop is looser than Alpha's planned invalidation.")
    return tuple(warnings)


def _quality(
    *,
    risk_reward: Decimal,
    risk_percent: Decimal,
    chased: bool,
    invalidation_respected: bool | None,
) -> str:
    if invalidation_respected is False:
        return "LOW"
    if risk_reward >= Decimal("3") and risk_percent <= Decimal("6") and not chased:
        return "HIGH"
    if risk_reward >= Decimal("2") and risk_percent <= Decimal("8"):
        return "MEDIUM"
    return "LOW"


def _entry_discipline(*, chased: bool, alpha_entry: Decimal | None) -> str:
    if alpha_entry is None:
        return "NOT_COMPARED"
    return "CHASED" if chased else "DISCIPLINED"


def _stop_placement(*, stop: Decimal, alpha_stop: Decimal | None) -> str:
    if alpha_stop is None:
        return "NOT_COMPARED"
    if stop < alpha_stop:
        return "LOOSER_THAN_ALPHA"
    if stop > alpha_stop:
        return "TIGHTER_THAN_ALPHA"
    return "ALIGNED"


def _chased(*, entry: Decimal, alpha_entry: Decimal | None) -> bool:
    if alpha_entry is None or alpha_entry <= _ZERO:
        return False
    return entry > alpha_entry * Decimal("1.02")


def _invalidation_review(value: bool | None) -> str:
    if value is None:
        return "Not assessed yet."
    if value:
        return "User respected the invalidation."
    return "User did not respect the invalidation."


def _next_actions(*, warnings: tuple[str, ...]) -> tuple[str, ...]:
    actions = ["Track whether price respects the stop and reaches target zones."]
    if warnings:
        actions.append("Review warnings before adding or holding full size.")
    actions.append("Exit if the original invalidation level is breached.")
    return tuple(actions)


def _metric(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


def _average(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return (sum(values, _ZERO) / Decimal(len(values))).quantize(
        _TWO,
        rounding=ROUND_HALF_UP,
    )


def _trade_id(symbol: str, timestamp: datetime) -> str:
    return f"{symbol}|{timestamp.isoformat()}"


def _review_dict(review: LiveTradeReview) -> dict[str, Any]:
    return {
        "symbol": review.symbol,
        "trade_quality": review.trade_quality,
        "risk_reward_ratio": _text(review.risk_reward_ratio),
        "risk_percent": _text(review.risk_percent),
        "target_return_percent": _text(review.target_return_percent),
        "synopsis": review.synopsis,
        "warnings": list(review.warnings),
        "next_actions": list(review.next_actions),
        "entry_discipline": review.entry_discipline,
        "stop_placement": review.stop_placement,
        "chased": review.chased,
        "invalidation_review": review.invalidation_review,
    }


def _review_from_dict(payload: dict[str, Any]) -> LiveTradeReview:
    return LiveTradeReview(
        symbol=str(payload["symbol"]),
        trade_quality=str(payload["trade_quality"]),
        risk_reward_ratio=_decimal_or_none(payload.get("risk_reward_ratio")),
        risk_percent=_decimal_or_none(payload.get("risk_percent")),
        target_return_percent=_decimal_or_none(payload.get("target_return_percent")),
        synopsis=str(payload["synopsis"]),
        warnings=tuple(str(item) for item in payload.get("warnings", ())),
        next_actions=tuple(str(item) for item in payload.get("next_actions", ())),
        entry_discipline=str(payload.get("entry_discipline", "NOT_COMPARED")),
        stop_placement=str(payload.get("stop_placement", "NOT_COMPARED")),
        chased=bool(payload.get("chased", False)),
        invalidation_review=str(payload.get("invalidation_review", "Not assessed.")),
    )


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "DEFAULT_USER_TRADE_JOURNAL_PATH",
    "LiveTradeReview",
    "LiveTradeReviewEngine",
    "UserTradeJournalRecord",
    "UserTradeJournalRepository",
    "render_live_trade_review",
    "render_user_trade_journal",
    "render_user_trade_journal_summary",
    "resolve_user_trade_journal_path",
]
