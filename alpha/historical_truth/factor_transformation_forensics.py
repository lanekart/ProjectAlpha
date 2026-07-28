"""HTR-010B1D residual factor-transformation forensics."""

from __future__ import annotations

import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

import duckdb

HTR010B1D_CONTRACT_VERSION = "HTR-010B1D-v1.0.0"
_IMPLEMENTATION_DEFECT = "IMPLEMENTATION_DEFECT"


class FactorTransformationForensicsEngine:
    """Build diagnostic dossiers for residual corporate-action factor defects."""

    def run(
        self,
        *,
        database_path: Path,
        htr010b_output: Path,
        htr010b1c_output: Path,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        results = _records(htr010b1c_output / "htr010b1_factor_validation_results.json")
        events = _records(htr010b_output / "htr010b_canonical_events.json")
        factors = _records(htr010b_output / "htr010b_adjustment_factors.json")
        cumulative = _records(htr010b_output / "htr010b_cumulative_factors.json")
        duplicate_groups = _records(htr010b_output / "htr010b_duplicate_groups.json")
        lineage = _records(htr010b_output / "htr010b_event_lineage.json")

        event_by_id = {str(row["canonical_event_id"]): row for row in events}
        factor_by_event = {str(row["canonical_event_id"]): row for row in factors}
        cumulative_by_event = _cumulative_by_event(factors, cumulative)
        duplicate_by_event = {
            str(row["canonical_event_id"]): row for row in duplicate_groups
        }
        lineage_by_event = {str(row["canonical_event_id"]): row for row in lineage}
        same_day = _same_day_factors(factors)

        selected = tuple(
            row
            for row in results
            if str(row.get("validation_outcome")) == _IMPLEMENTATION_DEFECT
            and (
                start_date
                <= (_as_date(row.get("effective_date")) or date.min)
                <= end_date
            )
        )
        dossiers: list[dict[str, Any]] = []
        with duckdb.connect(str(database_path), read_only=True) as connection:
            for row in selected:
                event_id = str(row.get("event_id") or "")
                event = event_by_id.get(event_id, {})
                factor = factor_by_event.get(event_id, {})
                dossiers.append(
                    _case_diagnostics(
                        connection=connection,
                        result=row,
                        event=event,
                        factor=factor,
                        cumulative=cumulative_by_event.get(event_id),
                        duplicate=duplicate_by_event.get(event_id),
                        lineage=lineage_by_event.get(event_id),
                        same_day_factors=same_day.get(
                            (
                                str(row.get("identity_key") or ""),
                                str(row.get("effective_date") or ""),
                            ),
                            (),
                        ),
                    )
                )

        classification_counts = Counter(
            str(row["forensic_classification"]) for row in dossiers
        )
        action_counts = Counter(
            str(row.get("action_type") or "UNKNOWN") for row in dossiers
        )
        recommendation_counts = Counter(
            str(row["recommended_repair_action"]) for row in dossiers
        )
        report = {
            "contract_version": HTR010B1D_CONTRACT_VERSION,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "case_count": len(dossiers),
            "classification_counts": dict(sorted(classification_counts.items())),
            "action_type_counts": dict(sorted(action_counts.items())),
            "recommended_repair_action_counts": dict(
                sorted(recommendation_counts.items())
            ),
            "orientation_candidate_count": classification_counts[
                "FACTOR_ORIENTATION_CONVENTION_MISMATCH"
            ],
            "term_arithmetic_mismatch_count": classification_counts[
                "OFFICIAL_TERM_ARITHMETIC_MISMATCH"
            ],
            "series_selection_mismatch_count": classification_counts[
                "SERIES_SELECTION_MISMATCH"
            ],
            "series_selection_ambiguity_count": classification_counts[
                "SERIES_SELECTION_AMBIGUITY"
            ],
            "close_basis_count": classification_counts[
                "OPEN_PRICE_NOT_REPRESENTATIVE_CLOSE_BASIS_RESTORES"
            ],
            "date_basis_mismatch_count": classification_counts[
                "EVENT_DATE_BASIS_MISMATCH"
            ],
            "multiple_action_composition_count": classification_counts[
                "MULTIPLE_ACTION_COMPOSITION_REQUIRED"
            ],
            "market_gap_not_factor_error_count": classification_counts[
                "RESIDUAL_MARKET_GAP_NOT_FACTOR_ERROR"
            ],
            "unresolved_count": classification_counts[
                "UNRESOLVED_TRANSFORMATION_FORENSICS"
            ],
            "market_derived_factor_autocorrection": False,
            "official_factor_mutated": False,
            "admission_policy_changed": False,
            "full_benchmark_replays": 0,
            "production_influence": False,
            "cases": sorted(
                dossiers,
                key=lambda item: (
                    str(item.get("effective_date") or ""),
                    str(item.get("identity_key") or ""),
                    str(item.get("event_id") or ""),
                ),
            ),
        }
        report["report_sha256"] = _digest(report)
        return report

    @staticmethod
    def export(report: dict[str, Any], output: Path) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        cases = tuple(report.get("cases", ()))
        executive = {key: value for key, value in report.items() if key != "cases"}
        report_json = output / "htr010b1d_factor_transformation_forensics.json"
        cases_json = output / "htr010b1d_factor_transformation_cases.json"
        cases_csv = output / "htr010b1d_factor_transformation_cases.csv"
        markdown = output / "htr010b1d_executive_report.md"
        report_json.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        cases_json.write_text(
            json.dumps(list(cases), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _write_csv(cases_csv, cases)
        markdown.write_text(_markdown(executive), encoding="utf-8")
        return report_json, cases_json, cases_csv, markdown


def _case_diagnostics(
    *,
    connection: duckdb.DuckDBPyConnection,
    result: dict[str, Any],
    event: dict[str, Any],
    factor: dict[str, Any],
    cumulative: dict[str, Any] | None,
    duplicate: dict[str, Any] | None,
    lineage: dict[str, Any] | None,
    same_day_factors: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    identity = str(
        result.get("identity_key") or event.get("governed_identity_id") or ""
    )
    event_id = str(result.get("event_id") or event.get("canonical_event_id") or "")
    effective = _as_date(result.get("effective_date") or event.get("effective_date"))
    isin = str(result.get("isin") or event.get("isin") or "").upper()
    selected_series = str(result.get("series") or "").upper() or None
    official_factor = _number(result.get("price_factor") or factor.get("price_factor"))
    action_type = str(
        result.get("action_type") or event.get("action_type") or "UNKNOWN"
    )

    term_factor, term_formula = _official_term_factor(event, action_type)
    term_match = _nearly_equal(official_factor, term_factor)
    series_metrics = _series_metrics(connection, isin, effective, official_factor)
    selected_metrics = _selected_series_metrics(series_metrics, selected_series)
    best_series = _best_metric(series_metrics, "open_adjusted_gap_atr")
    close_basis = _best_metric(series_metrics, "close_adjusted_gap_atr")
    inverse_factor = (
        1.0 / official_factor if official_factor and official_factor > 0 else None
    )
    best_inverse = _best_metric(
        _series_metrics(connection, isin, effective, inverse_factor),
        "open_adjusted_gap_atr",
    )
    date_candidates = _date_candidates(
        connection,
        isin,
        selected_series,
        event,
        official_factor,
    )
    best_date = _best_metric(date_candidates, "open_adjusted_gap_atr")
    same_day_factor = _product(
        tuple(_number(row.get("price_factor")) for row in same_day_factors)
    )
    best_same_day = _best_metric(
        _series_metrics(connection, isin, effective, same_day_factor),
        "open_adjusted_gap_atr",
    )

    classification, recommendation, evidence = _classify(
        result=result,
        action_type=action_type,
        official_factor=official_factor,
        term_factor=term_factor,
        term_match=term_match,
        selected_series=selected_series,
        selected_metrics=selected_metrics,
        best_series=best_series,
        close_basis=close_basis,
        best_inverse=best_inverse,
        best_date=best_date,
        effective=effective,
        best_same_day=best_same_day,
        same_day_factor_count=len(same_day_factors),
    )
    return {
        "case_id": f"htr010b1d:{sha256(event_id.encode()).hexdigest()}",
        "event_id": event_id,
        "identity_key": identity,
        "symbol": result.get("symbol") or event.get("symbol"),
        "isin": isin or None,
        "selected_series": selected_series,
        "action_type": action_type,
        "effective_date": effective.isoformat() if effective else None,
        "ex_date": event.get("ex_date"),
        "record_date": event.get("record_date"),
        "announcement_date": event.get("announcement_date"),
        "raw_action_text": event.get("raw_action_text"),
        "factor_state": result.get("factor_state") or factor.get("factor_state"),
        "official_price_factor": official_factor,
        "official_term_factor": term_factor,
        "official_term_formula": term_formula,
        "official_term_factor_matches": term_match,
        "inverse_factor_diagnostic": inverse_factor,
        "same_day_cumulative_factor_diagnostic": same_day_factor,
        "same_day_factor_count": len(same_day_factors),
        "historical_cumulative_factor": cumulative or {},
        "canonical_duplicate_group": duplicate or {},
        "event_lineage": lineage or {},
        "reported_adjusted_gap_atr": result.get("adjusted_gap_atr"),
        "reported_raw_gap_atr": result.get("raw_gap_atr"),
        "reported_residual_attribution": result.get("residual_attribution"),
        "selected_series_metrics": selected_metrics or {},
        "best_series_metrics": best_series or {},
        "best_close_basis_metrics": close_basis or {},
        "best_inverse_metrics": best_inverse or {},
        "best_event_date_metrics": best_date or {},
        "best_same_day_composition_metrics": best_same_day or {},
        "series_metrics": series_metrics,
        "event_date_candidates": date_candidates,
        "forensic_classification": classification,
        "forensic_evidence": evidence,
        "recommended_repair_action": recommendation,
        "official_factor_retained": True,
        "market_derived_factor_autocorrection": False,
        "admitted_to_replay": False,
        "production_influence": False,
    }


def _classify(
    *,
    result: dict[str, Any],
    action_type: str,
    official_factor: float | None,
    term_factor: float | None,
    term_match: bool | None,
    selected_series: str | None,
    selected_metrics: dict[str, Any] | None,
    best_series: dict[str, Any] | None,
    close_basis: dict[str, Any] | None,
    best_inverse: dict[str, Any] | None,
    best_date: dict[str, Any] | None,
    effective: date | None,
    best_same_day: dict[str, Any] | None,
    same_day_factor_count: int,
) -> tuple[str, str, dict[str, Any]]:
    official_gap = _metric(selected_metrics, "open_adjusted_gap_atr")
    raw_gap = _metric(selected_metrics, "open_raw_gap_atr")
    inverse_gap = _metric(best_inverse, "open_adjusted_gap_atr")
    best_series_gap = _metric(best_series, "open_adjusted_gap_atr")
    close_gap = _metric(close_basis, "close_adjusted_gap_atr")
    date_gap = _metric(best_date, "open_adjusted_gap_atr")
    composition_gap = _metric(best_same_day, "open_adjusted_gap_atr")
    evidence = {
        "official_gap": official_gap,
        "raw_gap": raw_gap,
        "inverse_gap": inverse_gap,
        "best_series_gap": best_series_gap,
        "close_basis_gap": close_gap,
        "best_date_gap": date_gap,
        "same_day_composition_gap": composition_gap,
    }

    if official_factor is None:
        return "MISSING_FACTOR_VALUE", "REPAIR_FACTOR_INPUT_CONTRACT", evidence
    if term_match is False and term_factor is not None:
        return (
            "OFFICIAL_TERM_ARITHMETIC_MISMATCH",
            "REPAIR_ACTION_TERM_FACTOR_DERIVATION",
            evidence,
        )
    if _restores(inverse_gap, raw_gap) and not _restores(official_gap, raw_gap):
        return (
            "FACTOR_ORIENTATION_CONVENTION_MISMATCH",
            "REVIEW_FACTOR_DIRECTION_CONTRACT_NO_AUTO_INVERSION",
            evidence,
        )
    if best_series and selected_series:
        best_name = str(best_series.get("series"))
        if best_name != selected_series and _restores(best_series_gap, official_gap):
            return (
                "SERIES_SELECTION_MISMATCH",
                "REPAIR_EVENT_SERIES_APPLICABILITY",
                evidence,
            )
    if best_series and not selected_series and _restores(best_series_gap, raw_gap):
        return (
            "SERIES_SELECTION_AMBIGUITY",
            "CERTIFY_SINGLE_EVENT_SERIES_BEFORE_FACTOR_VALIDATION",
            evidence,
        )
    if _restores(close_gap, official_gap) and not _restores(official_gap, raw_gap):
        return (
            "OPEN_PRICE_NOT_REPRESENTATIVE_CLOSE_BASIS_RESTORES",
            "USE_GOVERNED_CONTINUITY_BASIS_BY_LIQUIDITY_POLICY",
            evidence,
        )
    if best_date and effective:
        candidate = _as_date(best_date.get("candidate_date"))
        if candidate and candidate != effective and _restores(date_gap, official_gap):
            return (
                "EVENT_DATE_BASIS_MISMATCH",
                "REPAIR_EFFECTIVE_DATE_SELECTION_FROM_OFFICIAL_FIELDS",
                evidence,
            )
    if same_day_factor_count > 1 and _restores(composition_gap, official_gap):
        return (
            "MULTIPLE_ACTION_COMPOSITION_REQUIRED",
            "COMPOSE_SAME_SESSION_FACTORS_IN_GOVERNED_ORDER",
            evidence,
        )
    if action_type == "RIGHTS":
        return (
            "RIGHTS_REFERENCE_PRICE_BASIS_UNCERTAIN",
            "KEEP_QUARANTINED_USE_GOVERNED_PRE_RIGHTS_REFERENCE_CLOSE",
            evidence,
        )
    if _restores(official_gap, raw_gap):
        return (
            "RESIDUAL_MARKET_GAP_NOT_FACTOR_ERROR",
            "RECLASSIFY_AS_MARKET_GAP_WITHOUT_FACTOR_MUTATION",
            evidence,
        )
    if str(result.get("residual_attribution") or "") == (
        "POSSIBLE_THIN_TRADING_DISTORTION"
    ):
        return (
            "THIN_TRADING_CONTINUITY_UNRELIABLE",
            "KEEP_QUARANTINED_REQUIRE_LIQUIDITY_AWARE_VALIDATION",
            evidence,
        )
    return (
        "UNRESOLVED_TRANSFORMATION_FORENSICS",
        "MANUAL_OFFICIAL_SOURCE_AND_CANDLE_LINEAGE_REVIEW",
        evidence,
    )


def _official_term_factor(
    event: dict[str, Any], action_type: str
) -> tuple[float | None, str | None]:
    numerator = _number(event.get("ratio_numerator"))
    denominator = _number(event.get("ratio_denominator"))
    old_face = _number(event.get("old_face_value"))
    new_face = _number(event.get("new_face_value"))
    if action_type in {"SPLIT", "FACE_VALUE_CHANGE"}:
        if old_face and new_face and old_face > 0 and new_face > 0:
            return new_face / old_face, "new_face_value / old_face_value"
        if numerator and denominator and numerator > 0 and denominator > 0:
            return denominator / numerator, "ratio_denominator / ratio_numerator"
    if action_type == "BONUS" and numerator and denominator:
        if numerator > 0 and denominator > 0:
            factor = denominator / (numerator + denominator)
            formula = "ratio_denominator / (ratio_numerator + ratio_denominator)"
            if old_face is not None:
                if not new_face or old_face <= 0 or new_face <= 0:
                    return None, None
                factor *= new_face / old_face
                formula += " * new_face_value / old_face_value"
            return factor, formula
    return None, None


def _series_metrics(
    connection: duckdb.DuckDBPyConnection,
    isin: str,
    effective: date | None,
    factor: float | None,
) -> list[dict[str, Any]]:
    if not isin or effective is None:
        return []
    series_rows = connection.execute(
        "SELECT DISTINCT upper(series) FROM daily_candle WHERE upper(isin)=? "
        "AND trading_date BETWEEN ? AND ? ORDER BY 1",
        [isin, effective - timedelta(days=30), effective + timedelta(days=30)],
    ).fetchall()
    return [
        _metrics_for_date(connection, isin, str(row[0]), effective, factor)
        for row in series_rows
    ]


def _date_candidates(
    connection: duckdb.DuckDBPyConnection,
    isin: str,
    series: str | None,
    event: dict[str, Any],
    factor: float | None,
) -> list[dict[str, Any]]:
    candidates: set[date] = set()
    for key in ("effective_date", "ex_date", "record_date", "announcement_date"):
        value = _as_date(event.get(key))
        if value:
            candidates.add(value)
    effective = _as_date(event.get("effective_date"))
    if effective:
        rows = connection.execute(
            "SELECT DISTINCT trading_date FROM daily_candle WHERE upper(isin)=? "
            "AND trading_date BETWEEN ? AND ? ORDER BY trading_date",
            [isin, effective - timedelta(days=10), effective + timedelta(days=10)],
        ).fetchall()
        candidates.update(row[0] for row in rows)
    return [
        {
            **_metrics_for_date(connection, isin, series, candidate, factor),
            "candidate_date": candidate.isoformat(),
        }
        for candidate in sorted(candidates)
    ]


def _metrics_for_date(
    connection: duckdb.DuckDBPyConnection,
    isin: str,
    series: str | None,
    trading_date: date,
    factor: float | None,
) -> dict[str, Any]:
    if not isin:
        return {"series": series, "candidate_date": trading_date.isoformat()}
    clause = "" if series is None else " AND upper(series)=?"
    prior_params: list[Any] = [trading_date, isin]
    current_params: list[Any] = [trading_date, isin]
    if series is not None:
        prior_params.append(series)
        current_params.append(series)
    select = (
        "SELECT trading_date, open_price, high_price, low_price, close_price, volume "
        "FROM daily_candle "
    )
    prior = connection.execute(
        select
        + "WHERE trading_date < ? AND upper(isin)=?"
        + clause
        + " ORDER BY trading_date DESC LIMIT 15",
        prior_params,
    ).fetchall()
    current = connection.execute(
        select
        + "WHERE trading_date >= ? AND upper(isin)=?"
        + clause
        + " ORDER BY trading_date LIMIT 1",
        current_params,
    ).fetchone()
    prior = list(reversed(prior))
    if not prior or current is None:
        return {
            "series": series,
            "candidate_date": trading_date.isoformat(),
            "candle_context": "INSUFFICIENT",
        }
    previous_close = float(prior[-1][4])
    action_open = float(current[1])
    action_close = float(current[4])
    atr = _atr(prior)
    volumes = [float(row[5]) for row in prior if row[5] is not None]
    median_volume = statistics.median(volumes) if volumes else None
    return {
        "series": series,
        "candidate_date": trading_date.isoformat(),
        "previous_session": prior[-1][0].isoformat(),
        "action_session": current[0].isoformat(),
        "previous_close": previous_close,
        "action_open": action_open,
        "action_close": action_close,
        "atr_before": atr,
        "median_prior_volume": median_volume,
        "open_raw_gap_atr": _gap(action_open, previous_close, atr, 1.0),
        "open_adjusted_gap_atr": _gap(action_open, previous_close, atr, factor),
        "close_raw_gap_atr": _gap(action_close, previous_close, atr, 1.0),
        "close_adjusted_gap_atr": _gap(action_close, previous_close, atr, factor),
        "candle_context": "AVAILABLE",
    }


def _cumulative_by_event(
    factors: tuple[dict[str, Any], ...],
    cumulative: tuple[dict[str, Any], ...],
) -> dict[str, dict[str, Any]]:
    cumulative_by_key = {
        (str(row.get("identity_key")), str(row.get("effective_date"))): row
        for row in cumulative
    }
    return {
        str(row.get("canonical_event_id")): cumulative_by_key.get(
            (str(row.get("identity_key")), str(row.get("effective_date"))),
            {},
        )
        for row in factors
    }


def _same_day_factors(
    factors: tuple[dict[str, Any], ...],
) -> dict[tuple[str, str], tuple[dict[str, Any], ...]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in factors:
        grouped[(str(row.get("identity_key")), str(row.get("effective_date")))].append(
            row
        )
    return {
        key: tuple(sorted(rows, key=lambda item: str(item.get("factor_id"))))
        for key, rows in grouped.items()
    }


def _selected_series_metrics(
    rows: list[dict[str, Any]], selected_series: str | None
) -> dict[str, Any] | None:
    if selected_series:
        for row in rows:
            if str(row.get("series")) == selected_series:
                return row
    return rows[0] if len(rows) == 1 else None


def _best_metric(rows: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    candidates = [row for row in rows if _number(row.get(key)) is not None]
    return min(candidates, key=lambda row: float(row[key])) if candidates else None


def _metric(row: dict[str, Any] | None, key: str) -> float | None:
    return _number(row.get(key)) if row else None


def _restores(candidate: float | None, baseline: float | None) -> bool:
    if candidate is None:
        return False
    return candidate <= 2.0 or (
        baseline is not None and candidate <= max(2.0, baseline * 0.5)
    )


def _nearly_equal(left: float | None, right: float | None) -> bool | None:
    if left is None or right is None:
        return None
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-12)


def _product(values: tuple[float | None, ...]) -> float | None:
    valid = [value for value in values if value is not None and value > 0]
    if len(valid) <= 1 or len(valid) != len(values):
        return None
    result = 1.0
    for value in valid:
        result *= value
    return result


def _atr(rows: list[tuple[Any, ...]]) -> float | None:
    if len(rows) < 2:
        return None
    ranges: list[float] = []
    previous_close: float | None = None
    for row in rows[-14:]:
        high = float(row[2])
        low = float(row[3])
        close = float(row[4])
        true_range = high - low
        if previous_close is not None:
            true_range = max(
                true_range,
                abs(high - previous_close),
                abs(low - previous_close),
            )
        ranges.append(true_range)
        previous_close = close
    return sum(ranges) / len(ranges) if ranges else None


def _gap(
    price: float,
    previous_close: float,
    atr: float | None,
    factor: float | None,
) -> float | None:
    if atr is None or atr <= 0 or factor is None or factor <= 0:
        return None
    return abs(price - (previous_close * factor)) / (atr * factor)


def _records(path: Path) -> tuple[dict[str, Any], ...]:
    if not path.exists():
        raise ValueError(f"required forensic input is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(
        isinstance(row, dict) for row in payload
    ):
        raise ValueError(f"forensic input must be a JSON object list: {path}")
    return tuple(payload)


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _number(value: object) -> float | None:
    if value is None or not isinstance(value, (str, int, float)):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _digest(report: dict[str, Any]) -> str:
    payload = dict(report)
    payload.pop("report_sha256", None)
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _write_csv(path: Path, rows: tuple[dict[str, Any], ...]) -> None:
    fields = sorted({key for row in rows for key in row}) or ["value"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, sort_keys=True)
                    if isinstance(value, (dict, list))
                    else value
                    for key, value in row.items()
                }
            )


def _markdown(report: dict[str, Any]) -> str:
    return "\n".join(
        (
            "# HTR-010B1D Factor Transformation Forensics",
            "",
            f"- Cases audited: {report['case_count']}",
            "- Classifications: "
            f"{json.dumps(report['classification_counts'], sort_keys=True)}",
            "- Recommended repairs: "
            f"{json.dumps(report['recommended_repair_action_counts'], sort_keys=True)}",
            f"- Orientation candidates: {report['orientation_candidate_count']}",
            "- Official-term arithmetic mismatches: "
            f"{report['term_arithmetic_mismatch_count']}",
            "- Series-selection mismatches: "
            f"{report['series_selection_mismatch_count']}",
            "- Series-selection ambiguities: "
            f"{report['series_selection_ambiguity_count']}",
            f"- Close-basis restorations: {report['close_basis_count']}",
            f"- Event-date mismatches: {report['date_basis_mismatch_count']}",
            "- Multiple-action compositions: "
            f"{report['multiple_action_composition_count']}",
            f"- Residual market gaps: {report['market_gap_not_factor_error_count']}",
            f"- Unresolved forensic cases: {report['unresolved_count']}",
            f"- Report SHA-256: `{report['report_sha256']}`",
            "- Full benchmark replays: 0",
            "- Production influence: false",
            "",
            "Official factors remain immutable. Diagnostic alternatives "
            "never alter replay admission.",
            "",
        )
    )


__all__ = [
    "FactorTransformationForensicsEngine",
    "HTR010B1D_CONTRACT_VERSION",
]
