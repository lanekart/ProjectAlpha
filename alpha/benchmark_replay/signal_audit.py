from __future__ import annotations

import csv
import dataclasses
import json
import os
from collections import Counter
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from io import StringIO
from pathlib import Path
from statistics import median
from tempfile import NamedTemporaryFile

from alpha.benchmark_replay.provenance import file_hash
from alpha.canonical_universe_audit.store import LegacyMarketDataStore

DIAGNOSTIC_ONLY = True
PRODUCTION_INFLUENCE = False
DEFAULT_HORIZONS = (1, 5, 10, 20)
_FOUR = Decimal("0.0001")


@dataclasses.dataclass(frozen=True, slots=True)
class DiagnosticSignalOutcome:
    decision_date: date
    symbol: str
    final_signal: str
    opportunity_score: Decimal
    primary_reason_code: str
    horizon_sessions: int
    status: str
    decision_close: Decimal | None
    target_date: date | None
    target_close: Decimal | None
    forward_return_percent: Decimal | None
    maximum_favorable_excursion_percent: Decimal | None
    maximum_adverse_excursion_percent: Decimal | None
    diagnostic_only: bool = DIAGNOSTIC_ONLY
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclasses.dataclass(frozen=True, slots=True)
class DiagnosticSignalAudit:
    outcomes: tuple[DiagnosticSignalOutcome, ...]
    summary: dict[str, object]
    source_approval_hash: str
    dataset_version: str
    horizons: tuple[int, ...]


def run_diagnostic_signal_audit(
    *,
    store: LegacyMarketDataStore,
    approval_statistics: Path | str,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> DiagnosticSignalAudit:
    path = Path(approval_statistics)
    if not path.is_file():
        raise FileNotFoundError(f"approval statistics not found: {path}")
    normalized_horizons = tuple(sorted(set(horizons)))
    if not normalized_horizons or any(value < 1 for value in normalized_horizons):
        raise ValueError("diagnostic horizons must be positive")
    signals = _read_signals(path)
    sessions = store.trade_dates()
    session_index = {observed_on: index for index, observed_on in enumerate(sessions)}
    outcomes: list[DiagnosticSignalOutcome] = []
    for signal in signals:
        decision_date = date.fromisoformat(signal["observed_on"])
        symbol = signal["symbol"].strip().upper()
        score = Decimal(signal["opportunity_score"])
        reason = signal["primary_reason_code"]
        final_signal = signal["final_signal"]
        index = session_index.get(decision_date)
        decision_close = _decision_close(store, symbol, decision_date)
        for horizon in normalized_horizons:
            outcomes.append(
                _outcome(
                    store=store,
                    sessions=sessions,
                    decision_index=index,
                    decision_date=decision_date,
                    decision_close=decision_close,
                    symbol=symbol,
                    final_signal=final_signal,
                    score=score,
                    reason=reason,
                    horizon=horizon,
                )
            )
    frozen = tuple(
        sorted(
            outcomes,
            key=lambda item: (
                item.decision_date,
                item.symbol,
                item.horizon_sessions,
            ),
        )
    )
    return DiagnosticSignalAudit(
        outcomes=frozen,
        summary=_summary(frozen, len(signals), normalized_horizons),
        source_approval_hash=file_hash(path),
        dataset_version=store.manifest().dataset_version,
        horizons=normalized_horizons,
    )


def export_diagnostic_signal_audit(
    audit: DiagnosticSignalAudit,
    *,
    output_directory: Path | str,
) -> tuple[Path, ...]:
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    outcomes_path = _write_text(output / "signal_outcomes.csv", _outcomes_csv(audit))
    summary_path = _write_text(
        output / "summary.json",
        json.dumps(audit.summary, indent=2, sort_keys=True) + "\n",
    )
    report_path = _write_text(output / "report.md", _render_report(audit))
    artifact_hashes = {
        path.name: file_hash(path)
        for path in sorted((outcomes_path, report_path, summary_path))
    }
    manifest = {
        "dataset_version": audit.dataset_version,
        "diagnostic_only": True,
        "horizons": list(audit.horizons),
        "production_influence": False,
        "source_approval_hash": audit.source_approval_hash,
        "artifact_hashes": artifact_hashes,
    }
    manifest_path = _write_text(
        output / "manifest.json",
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    )
    return outcomes_path, summary_path, report_path, manifest_path


def _read_signals(path: Path) -> tuple[dict[str, str], ...]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or ())
        required = {
            "observed_on",
            "symbol",
            "final_signal",
            "opportunity_score",
            "primary_reason_code",
        }
        missing = required - fields
        if missing:
            raise ValueError(
                "approval statistics missing diagnostic evidence: "
                + ", ".join(sorted(missing))
            )
        return tuple(
            dict(row) for row in reader if row["final_signal"] in {"BUY", "STRONG_BUY"}
        )


def _outcome(
    *,
    store: LegacyMarketDataStore,
    sessions: tuple[date, ...],
    decision_index: int | None,
    decision_date: date,
    decision_close: Decimal | None,
    symbol: str,
    final_signal: str,
    score: Decimal,
    reason: str,
    horizon: int,
) -> DiagnosticSignalOutcome:
    base = {
        "decision_date": decision_date,
        "symbol": symbol,
        "final_signal": final_signal,
        "opportunity_score": score,
        "primary_reason_code": reason,
        "horizon_sessions": horizon,
    }
    if decision_index is None or decision_close is None:
        return DiagnosticSignalOutcome(
            **base,
            status="UNAVAILABLE_DECISION_OBSERVATION",
            decision_close=decision_close,
            target_date=None,
            target_close=None,
            forward_return_percent=None,
            maximum_favorable_excursion_percent=None,
            maximum_adverse_excursion_percent=None,
        )
    target_index = decision_index + horizon
    if target_index >= len(sessions):
        return DiagnosticSignalOutcome(
            **base,
            status="CENSORED_RIGHT_BOUNDARY",
            decision_close=decision_close,
            target_date=None,
            target_close=None,
            forward_return_percent=None,
            maximum_favorable_excursion_percent=None,
            maximum_adverse_excursion_percent=None,
        )
    target_date = sessions[target_index]
    rows = store.connection.execute(
        """
        SELECT trade_date, high, low, close
        FROM daily_prices
        WHERE UPPER(symbol) = ?
          AND trade_date > ?
          AND trade_date <= ?
        ORDER BY trade_date
        """,
        (symbol, decision_date, target_date),
    ).fetchall()
    expected_dates = sessions[decision_index + 1 : target_index + 1]
    observed_dates = tuple(row[0] for row in rows)
    if observed_dates != expected_dates:
        return DiagnosticSignalOutcome(
            **base,
            status="CENSORED_MISSING_OBSERVATION",
            decision_close=decision_close,
            target_date=target_date,
            target_close=None,
            forward_return_percent=None,
            maximum_favorable_excursion_percent=None,
            maximum_adverse_excursion_percent=None,
        )
    highs = tuple(Decimal(str(row[1])) for row in rows)
    lows = tuple(Decimal(str(row[2])) for row in rows)
    target_close = Decimal(str(rows[-1][3]))
    return DiagnosticSignalOutcome(
        **base,
        status="OBSERVED",
        decision_close=decision_close,
        target_date=target_date,
        target_close=target_close,
        forward_return_percent=_percent(target_close, decision_close),
        maximum_favorable_excursion_percent=_percent(max(highs), decision_close),
        maximum_adverse_excursion_percent=_percent(min(lows), decision_close),
    )


def _decision_close(
    store: LegacyMarketDataStore,
    symbol: str,
    observed_on: date,
) -> Decimal | None:
    row = store.connection.execute(
        """
        SELECT close FROM daily_prices
        WHERE UPPER(symbol) = ? AND trade_date = ?
        """,
        (symbol, observed_on),
    ).fetchone()
    return None if row is None else Decimal(str(row[0]))


def _summary(
    outcomes: tuple[DiagnosticSignalOutcome, ...],
    signal_count: int,
    horizons: tuple[int, ...],
) -> dict[str, object]:
    statuses = Counter(item.status for item in outcomes)
    horizon_rows: list[dict[str, object]] = []
    for horizon in horizons:
        observed = tuple(
            item
            for item in outcomes
            if item.horizon_sessions == horizon and item.status == "OBSERVED"
        )
        returns = tuple(
            item.forward_return_percent
            for item in observed
            if item.forward_return_percent is not None
        )
        horizon_rows.append(
            {
                "horizon_sessions": horizon,
                "observed": len(observed),
                "censored": signal_count - len(observed),
                "median_forward_return_percent": _median(returns),
            }
        )
    return {
        "classification": "DIAGNOSTIC_SIGNAL_AUDIT",
        "diagnostic_only": True,
        "production_influence": False,
        "raw_buy_or_strong_buy_signals": signal_count,
        "outcome_rows": len(outcomes),
        "status_counts": dict(sorted(statuses.items())),
        "horizons": horizon_rows,
    }


def _outcomes_csv(audit: DiagnosticSignalAudit) -> str:
    stream = StringIO(newline="")
    headers = (
        tuple(dataclasses.asdict(audit.outcomes[0]))
        if audit.outcomes
        else tuple(field.name for field in dataclasses.fields(DiagnosticSignalOutcome))
    )
    writer = csv.DictWriter(stream, fieldnames=headers, lineterminator="\\n")
    writer.writeheader()
    for item in audit.outcomes:
        writer.writerow(
            {key: _csv_value(value) for key, value in dataclasses.asdict(item).items()}
        )
    return stream.getvalue()


def _render_report(audit: DiagnosticSignalAudit) -> str:
    lines = [
        "# Diagnostic Signal Audit",
        "",
        "**DIAGNOSTIC_ONLY / PRODUCTION_INFLUENCE=false**",
        "",
        f"- Dataset: {audit.dataset_version}",
        "- Raw BUY/STRONG BUY signals: "
        f"{audit.summary['raw_buy_or_strong_buy_signals']}",
        f"- Horizons: {', '.join(str(value) for value in audit.horizons)} sessions",
        "",
        "## Horizon Outcomes",
        "",
        "| Horizon | Observed | Censored | Median forward return |",
        "|---:|---:|---:|---:|",
    ]
    horizon_rows = audit.summary["horizons"]
    assert isinstance(horizon_rows, list)
    for row in horizon_rows:
        assert isinstance(row, dict)
        value = row["median_forward_return_percent"]
        rendered = "unavailable" if value is None else f"{value}%"
        lines.append(
            f"| {row['horizon_sessions']} | {row['observed']} | "
            f"{row['censored']} | {rendered} |"
        )
    lines.extend(
        (
            "",
            "## Scientific Boundary",
            "",
            "- Signals failed complete-history eligibility and are diagnostic only.",
            "- Future observations are used only for retrospective outcome evaluation.",
            "- Right-boundary and missing observations are censored, never fabricated.",
            "- No threshold, approval gate, or portfolio policy was changed.",
            "",
            "**PRODUCTION_INFLUENCE=false**",
            "",
        )
    )
    return "\n".join(lines)


def _percent(value: Decimal, base: Decimal) -> Decimal:
    return ((value / base - 1) * 100).quantize(_FOUR, rounding=ROUND_HALF_UP)


def _median(values: tuple[Decimal, ...]) -> str | None:
    if not values:
        return None
    return str(Decimal(str(median(values))).quantize(_FOUR, rounding=ROUND_HALF_UP))


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, (date, Decimal)):
        return str(value)
    return value


def _write_text(path: Path, content: str) -> Path:
    with NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return path


__all__ = [
    "DEFAULT_HORIZONS",
    "DIAGNOSTIC_ONLY",
    "PRODUCTION_INFLUENCE",
    "DiagnosticSignalAudit",
    "DiagnosticSignalOutcome",
    "export_diagnostic_signal_audit",
    "run_diagnostic_signal_audit",
]
