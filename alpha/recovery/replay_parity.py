"""Deterministic parity diagnostics for raw and canonical replay outputs."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from .canonical_replay import CanonicalReplayBar, CanonicalReplayStatus

ReplayKey = tuple[str, date]
_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


@dataclass(frozen=True, slots=True)
class ReplayEvaluation:
    """Signal and decision emitted for one historical replay observation."""

    security_id: str
    trading_date: date
    signal: str
    decision: str

    def __post_init__(self) -> None:
        if not self.security_id.strip():
            raise ValueError("security_id must not be empty")
        if not self.signal.strip():
            raise ValueError("signal must not be empty")
        if not self.decision.strip():
            raise ValueError("decision must not be empty")

    @property
    def key(self) -> ReplayKey:
        return self.security_id, self.trading_date


@dataclass(frozen=True, slots=True)
class ReplayParityRow:
    """Raw-versus-canonical comparison for one replay observation."""

    security_id: str
    trading_date: date
    raw_symbol: str
    canonical_symbol: str
    raw_close: Decimal
    adjusted_close: Decimal
    price_change_percent: Decimal | None
    price_changed: bool
    raw_signal: str
    canonical_signal: str | None
    signal_changed: bool | None
    raw_decision: str
    canonical_decision: str | None
    decision_changed: bool | None
    replay_status: CanonicalReplayStatus
    applied_event_ids: tuple[str, ...]
    unresolved_event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReplayParityAudit:
    """Summary of corporate-action impact on replay signals and decisions."""

    bars_examined: int
    bars_ready: int
    bars_quarantined: int
    bars_price_changed: int
    signals_changed: int
    decisions_changed: int
    securities_affected: tuple[str, ...]
    signal_parity_percent: Decimal
    decision_parity_percent: Decimal
    governed_replay_ready: bool


@dataclass(frozen=True, slots=True)
class ReplayParityResult:
    """Complete deterministic parity result and its summary audit."""

    rows: tuple[ReplayParityRow, ...]
    audit: ReplayParityAudit


class ReplayParityAnalyzer:
    """Compare downstream outputs before and after canonical adjustment."""

    def analyze(
        self,
        bars: Iterable[CanonicalReplayBar],
        raw_evaluations: Iterable[ReplayEvaluation],
        canonical_evaluations: Iterable[ReplayEvaluation],
    ) -> ReplayParityResult:
        ordered_bars = tuple(
            sorted(
                bars,
                key=lambda item: (
                    item.trading_date,
                    item.security_id,
                    item.raw_symbol,
                ),
            )
        )
        bar_index = _index_bars(ordered_bars)
        raw_index = _index_evaluations(raw_evaluations, label="raw")
        canonical_index = _index_evaluations(
            canonical_evaluations,
            label="canonical",
        )
        bar_keys = set(bar_index)
        if set(raw_index) != bar_keys:
            raise ValueError("raw evaluations must exactly match replay bars")
        ready_keys = {
            key
            for key, bar in bar_index.items()
            if bar.status is CanonicalReplayStatus.READY
        }
        if set(canonical_index) != ready_keys:
            raise ValueError(
                "canonical evaluations must exactly match replay-ready bars"
            )

        rows = tuple(
            self._compare_bar(
                bar,
                raw_index[(bar.security_id, bar.trading_date)],
                canonical_index.get((bar.security_id, bar.trading_date)),
            )
            for bar in ordered_bars
        )
        return ReplayParityResult(rows=rows, audit=_build_audit(rows))

    @staticmethod
    def _compare_bar(
        bar: CanonicalReplayBar,
        raw: ReplayEvaluation,
        canonical: ReplayEvaluation | None,
    ) -> ReplayParityRow:
        price_changed = (
            bar.raw_close != bar.adjusted_close
            or bar.raw_symbol != bar.canonical_symbol
        )
        price_change_percent = _price_change_percent(
            bar.raw_close,
            bar.adjusted_close,
        )
        canonical_signal = canonical.signal if canonical else None
        canonical_decision = canonical.decision if canonical else None
        signal_changed = raw.signal != canonical.signal if canonical else None
        decision_changed = raw.decision != canonical.decision if canonical else None
        return ReplayParityRow(
            security_id=bar.security_id,
            trading_date=bar.trading_date,
            raw_symbol=bar.raw_symbol,
            canonical_symbol=bar.canonical_symbol,
            raw_close=bar.raw_close,
            adjusted_close=bar.adjusted_close,
            price_change_percent=price_change_percent,
            price_changed=price_changed,
            raw_signal=raw.signal,
            canonical_signal=canonical_signal,
            signal_changed=signal_changed,
            raw_decision=raw.decision,
            canonical_decision=canonical_decision,
            decision_changed=decision_changed,
            replay_status=bar.status,
            applied_event_ids=bar.applied_event_ids,
            unresolved_event_ids=bar.unresolved_event_ids,
        )


def export_replay_parity(
    result: ReplayParityResult,
    output: Path,
) -> tuple[Path, ...]:
    """Export deterministic HTR-004 parity artifacts."""

    output.mkdir(parents=True, exist_ok=True)
    rows_path = output / "replay_parity.csv"
    changed_path = output / "changed_decisions.csv"
    audit_path = output / "replay_parity_audit.json"
    report_path = output / "replay_parity.md"
    payload = [_row_payload(row) for row in result.rows]
    _write_csv(rows_path, payload)
    _write_csv(
        changed_path,
        [row for row in payload if row["decision_changed"] is True],
    )
    audit_path.write_text(
        json.dumps(
            _json_ready(asdict(result.audit)),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    report_path.write_text(_render_report(result.audit), encoding="utf-8")
    return rows_path, changed_path, audit_path, report_path


def _index_bars(
    bars: Iterable[CanonicalReplayBar],
) -> dict[ReplayKey, CanonicalReplayBar]:
    indexed: dict[ReplayKey, CanonicalReplayBar] = {}
    for bar in bars:
        key = bar.security_id, bar.trading_date
        if key in indexed:
            raise ValueError(f"duplicate canonical replay bar for {key!r}")
        indexed[key] = bar
    return indexed


def _index_evaluations(
    evaluations: Iterable[ReplayEvaluation],
    *,
    label: str,
) -> dict[ReplayKey, ReplayEvaluation]:
    indexed: dict[ReplayKey, ReplayEvaluation] = {}
    for evaluation in evaluations:
        if evaluation.key in indexed:
            raise ValueError(
                f"duplicate {label} replay evaluation for {evaluation.key!r}"
            )
        indexed[evaluation.key] = evaluation
    return indexed


def _price_change_percent(raw: Decimal, adjusted: Decimal) -> Decimal | None:
    if raw == _ZERO:
        return None
    return ((adjusted / raw - Decimal("1")) * _HUNDRED).quantize(Decimal("0.0001"))


def _build_audit(rows: tuple[ReplayParityRow, ...]) -> ReplayParityAudit:
    ready = tuple(
        row for row in rows if row.replay_status is CanonicalReplayStatus.READY
    )
    quarantined = tuple(
        row
        for row in rows
        if row.replay_status is CanonicalReplayStatus.QUARANTINED
    )
    signal_changes = sum(row.signal_changed is True for row in ready)
    decision_changes = sum(row.decision_changed is True for row in ready)
    affected = tuple(
        sorted(
            {
                row.security_id
                for row in rows
                if row.price_changed
                or row.signal_changed is True
                or row.decision_changed is True
                or row.replay_status is CanonicalReplayStatus.QUARANTINED
            }
        )
    )
    return ReplayParityAudit(
        bars_examined=len(rows),
        bars_ready=len(ready),
        bars_quarantined=len(quarantined),
        bars_price_changed=sum(row.price_changed for row in rows),
        signals_changed=signal_changes,
        decisions_changed=decision_changes,
        securities_affected=affected,
        signal_parity_percent=_parity_percent(len(ready), signal_changes),
        decision_parity_percent=_parity_percent(len(ready), decision_changes),
        governed_replay_ready=not quarantined,
    )


def _parity_percent(total: int, changes: int) -> Decimal:
    if total == 0:
        return _ZERO
    return (Decimal(total - changes) / Decimal(total) * _HUNDRED).quantize(
        Decimal("0.0001")
    )


def _row_payload(row: ReplayParityRow) -> dict[str, object]:
    return {key: _json_ready(value) for key, value in asdict(row).items()}


def _json_ready(value: object) -> object:
    if isinstance(value, (date, Decimal, CanonicalReplayStatus)):
        return str(value)
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    return value


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _render_report(audit: ReplayParityAudit) -> str:
    return (
        "# Canonical Replay Parity Audit\n\n"
        f"- Bars Examined: `{audit.bars_examined}`\n"
        f"- Bars Ready: `{audit.bars_ready}`\n"
        f"- Bars Quarantined: `{audit.bars_quarantined}`\n"
        f"- Bars Price Changed: `{audit.bars_price_changed}`\n"
        f"- Signals Changed: `{audit.signals_changed}`\n"
        f"- Decisions Changed: `{audit.decisions_changed}`\n"
        f"- Signal Parity: `{audit.signal_parity_percent}%`\n"
        f"- Decision Parity: `{audit.decision_parity_percent}%`\n"
        f"- Governed Replay Ready: `{audit.governed_replay_ready}`\n"
    )
