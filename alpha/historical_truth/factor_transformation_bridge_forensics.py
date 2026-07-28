"""HTR-010B1D1 cross-series and identity-bridge forensics."""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

import duckdb

HTR010B1D1_CONTRACT_VERSION = "HTR-010B1D1-v1.0.0"


class FactorTransformationBridgeForensicsEngine:
    """Reconstruct explicit pre/post candle lineage for B1D cases."""

    def run(
        self,
        *,
        database_path: Path,
        htr010b_output: Path,
        htr010b1d_output: Path,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        cases = _records(
            htr010b1d_output / "htr010b1d_factor_transformation_cases.json"
        )
        transitions = _records(htr010b_output / "htr010b_identity_transitions.json")
        selected = tuple(
            row
            for row in cases
            if start_date
            <= (_as_date(row.get("effective_date")) or date.min)
            <= end_date
        )

        dossiers: list[dict[str, Any]] = []
        with duckdb.connect(str(database_path), read_only=True) as connection:
            for case in selected:
                dossiers.append(_bridge_case(connection, case, transitions))

        classifications = Counter(str(row["bridge_classification"]) for row in dossiers)
        recommendations = Counter(
            str(row["recommended_repair_action"]) for row in dossiers
        )
        report = {
            "contract_version": HTR010B1D1_CONTRACT_VERSION,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "case_count": len(dossiers),
            "classification_counts": dict(sorted(classifications.items())),
            "recommended_repair_action_counts": dict(sorted(recommendations.items())),
            "cross_series_pairing_artifact_count": classifications[
                "CROSS_SERIES_PAIRING_ARTIFACT"
            ],
            "governed_cross_isin_bridge_count": classifications[
                "GOVERNED_CROSS_ISIN_BRIDGE_AVAILABLE"
            ],
            "identity_transition_noncomparable_count": classifications[
                "IDENTITY_TRANSITION_NONCOMPARABLE"
            ],
            "cross_isin_bridge_uncertified_count": classifications[
                "CROSS_ISIN_BRIDGE_UNCERTIFIED"
            ],
            "stable_pair_contract_defect_count": classifications[
                "STABLE_SECURITY_PAIR_SELECTION_CONTRACT_DEFECT"
            ],
            "candle_lineage_missing_count": classifications[
                "CANDLE_LINEAGE_BRIDGE_MISSING"
            ],
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
        report_json = output / "htr010b1d1_bridge_forensics.json"
        cases_json = output / "htr010b1d1_bridge_cases.json"
        cases_csv = output / "htr010b1d1_bridge_cases.csv"
        markdown = output / "htr010b1d1_executive_report.md"
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


def _bridge_case(
    connection: duckdb.DuckDBPyConnection,
    case: dict[str, Any],
    transitions: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    effective = _as_date(case.get("effective_date"))
    event_isin = str(case.get("isin") or "").upper()
    identity = str(case.get("identity_key") or "")
    symbol = str(case.get("symbol") or "").upper()
    factor = _number(case.get("official_price_factor"))
    matched = _matching_transitions(
        transitions,
        effective=effective,
        identity=identity,
        isin=event_isin,
        symbol=symbol,
    )
    isin_candidates = _isin_candidates(event_isin, identity, matched)
    symbol_candidates = _symbol_candidates(symbol, matched)
    bridge_candidates = _bridge_candidates(
        connection,
        effective=effective,
        factor=factor,
        isin_candidates=isin_candidates,
        symbol_candidates=symbol_candidates,
        transitions=matched,
    )
    selected = _select_bridge(bridge_candidates)
    classification, recommendation = _classify_bridge(selected, matched)
    prior = selected.get("prior", {}) if selected else {}
    current = selected.get("current", {}) if selected else {}
    original_evidence = case.get("forensic_evidence")
    return {
        "case_id": case.get("case_id"),
        "event_id": case.get("event_id"),
        "identity_key": identity,
        "symbol": symbol or None,
        "event_isin": event_isin or None,
        "action_type": case.get("action_type"),
        "effective_date": effective.isoformat() if effective else None,
        "official_price_factor": factor,
        "b1d_classification": case.get("forensic_classification"),
        "b1d_official_term_factor": case.get("official_term_factor"),
        "b1d_official_term_formula": case.get("official_term_formula"),
        "b1d_official_term_factor_matches": case.get("official_term_factor_matches"),
        "b1d_reference_price_certified": case.get("reference_price_certified"),
        "b1d_reference_price_provenance_state": case.get(
            "reference_price_provenance_state"
        ),
        "b1d_official_gap": (
            original_evidence.get("official_gap")
            if isinstance(original_evidence, dict)
            else None
        ),
        "b1d_best_series_gap": (
            original_evidence.get("best_series_gap")
            if isinstance(original_evidence, dict)
            else None
        ),
        "matched_identity_transitions": list(matched),
        "candidate_isins": list(isin_candidates),
        "candidate_symbols": list(symbol_candidates),
        "bridge_candidate_count": len(bridge_candidates),
        "selected_bridge": selected or {},
        "prior_isin": prior.get("isin"),
        "prior_symbol": prior.get("symbol"),
        "prior_series": prior.get("series"),
        "prior_session": prior.get("trading_date"),
        "current_isin": current.get("isin"),
        "current_symbol": current.get("symbol"),
        "current_series": current.get("series"),
        "current_session": current.get("trading_date"),
        "bridge_raw_gap_atr": selected.get("raw_gap_atr") if selected else None,
        "bridge_adjusted_gap_atr": (
            selected.get("adjusted_gap_atr") if selected else None
        ),
        "bridge_type": selected.get("bridge_type") if selected else None,
        "bridge_classification": classification,
        "recommended_repair_action": recommendation,
        "original_b1b_cross_series_pairing_possible": bool(
            case.get("reported_adjusted_gap_atr") is not None
            and case.get("forensic_evidence", {}).get("official_gap") is None
        ),
        "official_factor_retained": True,
        "market_derived_factor_autocorrection": False,
        "admitted_to_replay": False,
        "production_influence": False,
    }


def _matching_transitions(
    transitions: tuple[dict[str, Any], ...],
    *,
    effective: date | None,
    identity: str,
    isin: str,
    symbol: str,
) -> tuple[dict[str, Any], ...]:
    if effective is None:
        return ()
    matches = []
    for row in transitions:
        transition_date = _as_date(row.get("effective_date"))
        if transition_date is None or abs((transition_date - effective).days) > 10:
            continue
        identities = {
            str(row.get("predecessor_identity") or ""),
            str(row.get("successor_identity") or ""),
        }
        isins = {
            str(row.get("old_isin") or "").upper(),
            str(row.get("new_isin") or "").upper(),
        }
        symbols = {
            str(row.get("old_symbol") or "").upper(),
            str(row.get("new_symbol") or "").upper(),
        }
        if identity in identities or isin in isins or symbol in symbols:
            matches.append(row)
    return tuple(
        sorted(
            matches,
            key=lambda row: (
                abs(
                    (
                        (_as_date(row.get("effective_date")) or effective) - effective
                    ).days
                ),
                str(row.get("transition_id") or ""),
            ),
        )
    )


def _isin_candidates(
    event_isin: str,
    identity: str,
    transitions: tuple[dict[str, Any], ...],
) -> tuple[str, ...]:
    values = {event_isin, identity.removeprefix("nse:isin:").upper()}
    for row in transitions:
        values.update(
            {
                str(row.get("old_isin") or "").upper(),
                str(row.get("new_isin") or "").upper(),
                str(row.get("predecessor_identity") or "")
                .removeprefix("nse:isin:")
                .upper(),
                str(row.get("successor_identity") or "")
                .removeprefix("nse:isin:")
                .upper(),
            }
        )
    return tuple(sorted(value for value in values if value))


def _symbol_candidates(
    symbol: str,
    transitions: tuple[dict[str, Any], ...],
) -> tuple[str, ...]:
    values = {symbol}
    for row in transitions:
        values.update(
            {
                str(row.get("old_symbol") or "").upper(),
                str(row.get("new_symbol") or "").upper(),
            }
        )
    return tuple(sorted(value for value in values if value))


def _bridge_candidates(
    connection: duckdb.DuckDBPyConnection,
    *,
    effective: date | None,
    factor: float | None,
    isin_candidates: tuple[str, ...],
    symbol_candidates: tuple[str, ...],
    transitions: tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    if effective is None:
        return []
    prior_rows = _boundary_rows(
        connection,
        effective=effective,
        isins=isin_candidates,
        symbols=symbol_candidates,
        prior=True,
    )
    current_rows = _boundary_rows(
        connection,
        effective=effective,
        isins=isin_candidates,
        symbols=symbol_candidates,
        prior=False,
    )
    candidates = []
    for prior in prior_rows:
        for current in current_rows:
            transition = _transition_for_pair(transitions, prior, current)
            bridge_type = _bridge_type(prior, current)
            atr = _prior_atr(connection, prior, effective)
            raw_gap = _gap_atr(
                _number(current.get("open_price")),
                _number(prior.get("close_price")),
                atr,
                1.0,
            )
            adjusted_gap = _gap_atr(
                _number(current.get("open_price")),
                _number(prior.get("close_price")),
                atr,
                factor,
            )
            candidates.append(
                {
                    "prior": prior,
                    "current": current,
                    "bridge_type": bridge_type,
                    "matching_transition": transition or {},
                    "transition_evidence_available": transition is not None,
                    "histories_may_be_linked": (
                        bool(transition.get("histories_may_be_linked"))
                        if transition
                        else False
                    ),
                    "price_comparison_valid": (
                        bool(transition.get("price_comparison_valid"))
                        if transition
                        else bridge_type != "CROSS_ISIN"
                    ),
                    "atr_before": atr,
                    "raw_gap_atr": raw_gap,
                    "adjusted_gap_atr": adjusted_gap,
                    "ranking_key": _ranking_key(
                        prior,
                        current,
                        bridge_type,
                        transition,
                        effective,
                    ),
                }
            )
    return sorted(candidates, key=lambda row: tuple(row["ranking_key"]))


def _boundary_rows(
    connection: duckdb.DuckDBPyConnection,
    *,
    effective: date,
    isins: tuple[str, ...],
    symbols: tuple[str, ...],
    prior: bool,
) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if isins:
        clauses.append("upper(isin) IN (" + ",".join("?" for _ in isins) + ")")
        params.extend(isins)
    if symbols:
        clauses.append("upper(symbol) IN (" + ",".join("?" for _ in symbols) + ")")
        params.extend(symbols)
    if not clauses:
        return []
    comparator = "<" if prior else ">="
    order = "DESC" if prior else "ASC"
    params.append(effective)
    rows = connection.execute(
        "SELECT trading_date, upper(symbol), upper(series), upper(isin), "
        "open_price, high_price, low_price, close_price, volume "
        "FROM daily_candle WHERE ("
        + " OR ".join(clauses)
        + f") AND trading_date {comparator} ? ORDER BY trading_date {order}",
        params,
    ).fetchall()
    if not rows:
        return []
    boundary_date = rows[0][0]
    return [
        {
            "trading_date": row[0].isoformat(),
            "symbol": row[1],
            "series": row[2],
            "isin": row[3],
            "open_price": row[4],
            "high_price": row[5],
            "low_price": row[6],
            "close_price": row[7],
            "volume": row[8],
        }
        for row in rows
        if row[0] == boundary_date
    ]


def _prior_atr(
    connection: duckdb.DuckDBPyConnection,
    prior: dict[str, Any],
    effective: date,
) -> float | None:
    rows = connection.execute(
        "SELECT high_price, low_price, close_price FROM daily_candle "
        "WHERE trading_date < ? AND upper(isin)=? AND upper(series)=? "
        "ORDER BY trading_date DESC LIMIT 14",
        [effective, prior.get("isin"), prior.get("series")],
    ).fetchall()
    ordered = list(reversed(rows))
    if len(ordered) < 2:
        return None
    ranges = []
    previous_close: float | None = None
    for high, low, close in ordered:
        high_value = float(high)
        low_value = float(low)
        close_value = float(close)
        true_range = high_value - low_value
        if previous_close is not None:
            true_range = max(
                true_range,
                abs(high_value - previous_close),
                abs(low_value - previous_close),
            )
        ranges.append(true_range)
        previous_close = close_value
    return sum(ranges) / len(ranges) if ranges else None


def _transition_for_pair(
    transitions: tuple[dict[str, Any], ...],
    prior: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any] | None:
    prior_isin = str(prior.get("isin") or "").upper()
    current_isin = str(current.get("isin") or "").upper()
    prior_symbol = str(prior.get("symbol") or "").upper()
    current_symbol = str(current.get("symbol") or "").upper()
    for row in transitions:
        old_isin = str(row.get("old_isin") or "").upper()
        new_isin = str(row.get("new_isin") or "").upper()
        old_symbol = str(row.get("old_symbol") or "").upper()
        new_symbol = str(row.get("new_symbol") or "").upper()
        if (
            old_isin
            and new_isin
            and (old_isin, new_isin)
            == (
                prior_isin,
                current_isin,
            )
        ):
            return row
        if (
            old_symbol
            and new_symbol
            and (old_symbol, new_symbol)
            == (
                prior_symbol,
                current_symbol,
            )
        ):
            return row
    return None


def _bridge_type(prior: dict[str, Any], current: dict[str, Any]) -> str:
    if prior.get("isin") != current.get("isin"):
        return "CROSS_ISIN"
    if prior.get("series") != current.get("series"):
        return "CROSS_SERIES"
    return "STABLE_SECURITY_SERIES"


def _ranking_key(
    prior: dict[str, Any],
    current: dict[str, Any],
    bridge_type: str,
    transition: dict[str, Any] | None,
    effective: date,
) -> tuple[Any, ...]:
    transition_rank = 0 if transition else 1
    type_rank = {
        "STABLE_SECURITY_SERIES": 0,
        "CROSS_SERIES": 1,
        "CROSS_ISIN": 2,
    }[bridge_type]
    current_date = _as_date(current.get("trading_date")) or date.max
    prior_date = _as_date(prior.get("trading_date")) or date.min
    return (
        transition_rank,
        type_rank,
        abs((current_date - effective).days),
        abs((effective - prior_date).days),
        str(prior.get("isin") or ""),
        str(prior.get("series") or ""),
        str(current.get("isin") or ""),
        str(current.get("series") or ""),
    )


def _select_bridge(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    return candidates[0] if candidates else None


def _classify_bridge(
    selected: dict[str, Any] | None,
    transitions: tuple[dict[str, Any], ...],
) -> tuple[str, str]:
    if selected is None:
        return (
            "CANDLE_LINEAGE_BRIDGE_MISSING",
            "REPAIR_GOVERNED_CANDLE_IDENTITY_LINEAGE",
        )
    bridge_type = str(selected.get("bridge_type") or "")
    if bridge_type == "STABLE_SECURITY_SERIES":
        return (
            "STABLE_SECURITY_PAIR_SELECTION_CONTRACT_DEFECT",
            "REPAIR_B1D_SELECTED_SERIES_AND_BOUNDARY_PAIRING",
        )
    if bridge_type == "CROSS_SERIES":
        return (
            "CROSS_SERIES_PAIRING_ARTIFACT",
            "PROHIBIT_UNSCOPED_SERIES_NONE_CONTINUITY_AND_CERTIFY_SERIES_BRIDGE",
        )
    transition = selected.get("matching_transition")
    if isinstance(transition, dict) and transition:
        if not bool(transition.get("price_comparison_valid")):
            return (
                "IDENTITY_TRANSITION_NONCOMPARABLE",
                "KEEP_QUARANTINED_DO_NOT_APPLY_MULTIPLICATIVE_FACTOR",
            )
        if bool(transition.get("histories_may_be_linked")):
            return (
                "GOVERNED_CROSS_ISIN_BRIDGE_AVAILABLE",
                "VALIDATE_FACTOR_ON_EXPLICIT_PREDECESSOR_SUCCESSOR_BRIDGE",
            )
    if transitions:
        return (
            "CROSS_ISIN_BRIDGE_UNCERTIFIED",
            "RECONCILE_TRANSITION_DIRECTION_AND_EFFECTIVE_DATE",
        )
    return (
        "CROSS_ISIN_BRIDGE_UNCERTIFIED",
        "ACQUIRE_EFFECTIVE_DATED_IDENTITY_TRANSITION_EVIDENCE",
    )


def _gap_atr(
    price: float | None,
    previous_close: float | None,
    atr: float | None,
    factor: float | None,
) -> float | None:
    if (
        price is None
        or previous_close is None
        or atr is None
        or atr <= 0
        or factor is None
        or factor <= 0
    ):
        return None
    reference = previous_close * factor
    return abs(price - reference) / (atr * factor)


def _records(path: Path) -> tuple[dict[str, Any], ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(
        isinstance(row, dict) for row in payload
    ):
        raise ValueError(f"expected JSON array of objects: {path}")
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
            "# HTR-010B1D1 Cross-Series and Identity-Bridge Forensics",
            "",
            f"- Cases audited: {report['case_count']}",
            "- Classifications: "
            f"{json.dumps(report['classification_counts'], sort_keys=True)}",
            "- Recommended repairs: "
            f"{json.dumps(report['recommended_repair_action_counts'], sort_keys=True)}",
            "- Cross-series pairing artifacts: "
            f"{report['cross_series_pairing_artifact_count']}",
            "- Governed cross-ISIN bridges: "
            f"{report['governed_cross_isin_bridge_count']}",
            "- Non-comparable identity transitions: "
            f"{report['identity_transition_noncomparable_count']}",
            "- Uncertified cross-ISIN bridges: "
            f"{report['cross_isin_bridge_uncertified_count']}",
            "- Stable-pair selection contract defects: "
            f"{report['stable_pair_contract_defect_count']}",
            "- Missing candle-lineage bridges: "
            f"{report['candle_lineage_missing_count']}",
            f"- Report SHA-256: `{report['report_sha256']}`",
            "- Full benchmark replays: 0",
            "- Production influence: false",
            "",
            "Official factors remain immutable. Every case remains "
            "excluded from replay.",
            "",
        )
    )


__all__ = [
    "FactorTransformationBridgeForensicsEngine",
    "HTR010B1D1_CONTRACT_VERSION",
]
