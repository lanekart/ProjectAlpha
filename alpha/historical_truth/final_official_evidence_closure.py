"""DSI-010B5 final evidence closure and adjusted-history certification."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

import duckdb

from alpha.historical_truth.adjustment_replay_admission_models import (
    ValidationOutcome,
)
from alpha.historical_truth.legacy_isin_reference_bridge import (
    LegacyIsinReferenceBridge,
)

DSI010B5_CONTRACT_VERSION = "DSI-010B5-v1.0.0"
DSI010B5_CALCULATION_VERSION = "DSI-010B5-BACKWARD-ADJUSTMENT-v1.0.0"
PRODUCTION_INFLUENCE = False

_MATERIAL_ACTIONS = {
    "SPLIT",
    "BONUS",
    "RIGHTS",
    "FACE_VALUE_CHANGE",
    "CAPITAL_REDUCTION",
}
_TERMINAL_MULTIPLICATIVE_OUTCOMES = {
    ValidationOutcome.FACTOR_CONFIRMED_CORRECT_MARKET_GAP.value,
    ValidationOutcome.FACTOR_CONFIRMED_CORRECT_THIN_TRADING.value,
    ValidationOutcome.FACTOR_CONFIRMED_CORRECT_EVENT_DATE_OFFSET.value,
    ValidationOutcome.FACTOR_CONFIRMED_CORRECT_MULTIPLE_ACTIONS.value,
    (ValidationOutcome.FACTOR_CERTIFIED_OFFICIAL_TERMS_CONTINUITY_NOT_TESTABLE.value),
}
_TERMINAL_NON_MULTIPLICATIVE_OUTCOMES = {
    ValidationOutcome.FACTOR_NON_MULTIPLICATIVE.value,
}
_UNRESOLVED_OUTCOMES = {
    ValidationOutcome.FACTOR_INSUFFICIENT_EVIDENCE.value,
    ValidationOutcome.FACTOR_REQUIRES_REFERENCE_PRICE.value,
    ValidationOutcome.FACTOR_CONFLICTING_OFFICIAL_EVIDENCE.value,
    ValidationOutcome.IMPLEMENTATION_DEFECT.value,
    ValidationOutcome.UNRESOLVED.value,
}


@dataclass(frozen=True, slots=True)
class AcceptedFactor:
    event_id: str
    factor_id: str
    identity_key: str
    symbol: str
    series: str
    effective_date: date
    price_factor: float
    quantity_factor: float
    validation_outcome: str


@dataclass(frozen=True, slots=True)
class FinalOfficialEvidenceClosureReport:
    summary: dict[str, Any]
    before_after: tuple[dict[str, Any], ...]
    remaining_blockers: tuple[dict[str, Any], ...]
    factor_ledger: tuple[dict[str, Any], ...]
    source_manifest: tuple[dict[str, Any], ...]
    named_cases: tuple[dict[str, Any], ...]
    certificate_sha256: str


class FinalOfficialEvidenceClosureEngine:
    """Close event evidence, then fail closed on unresolved row identity."""

    def run(
        self,
        *,
        database_path: Path,
        htr009a2_output: Path,
        htr010a3_output: Path,
        htr010b_output: Path,
        final_b1c_output: Path,
        final_b1e2_output: Path,
        baseline_b4_output: Path,
        start_date: date,
        end_date: date,
        output: Path,
    ) -> FinalOfficialEvidenceClosureReport:
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")
        validation = _records(
            final_b1c_output / "htr010b1_factor_validation_results.json"
        )
        events = _indexed(
            htr010b_output / "htr010b_canonical_events.json",
            "canonical_event_id",
        )
        factors = _indexed(
            htr010b_output / "htr010b_adjustment_factors.json",
            "canonical_event_id",
        )
        _validate_b1e2(final_b1e2_output, validation)
        accepted, factor_ledger = _accepted_factors(validation, events, factors)
        baseline = _baseline_b4(baseline_b4_output)
        raw_before = _raw_candle_fingerprint(database_path)
        bridge = LegacyIsinReferenceBridge.from_output(
            htr009a2_output,
            htr010a3_output=htr010a3_output,
        )
        materialization = _materialize_governed_adjustments(
            database_path=database_path,
            output_database=output / "dsi010b5_adjusted_history.duckdb",
            bridge=bridge,
            events=events,
            accepted=accepted,
            start_date=start_date,
            end_date=end_date,
        )
        raw_after = _raw_candle_fingerprint(database_path)
        if raw_before != raw_after:
            raise RuntimeError("canonical raw candles changed during DSI-010B5")

        outcome_counts = Counter(
            str(row.get("validation_outcome")) for row in validation
        )
        unresolved_validation = tuple(
            row
            for row in validation
            if str(row.get("validation_outcome")) in _UNRESOLVED_OUTCOMES
        )
        remaining = tuple(
            sorted(
                (
                    *_event_blockers(unresolved_validation),
                    *materialization["identity_blockers"],
                ),
                key=lambda row: (
                    str(row.get("blocker_type")),
                    str(row.get("symbol")),
                    str(row.get("identity_key")),
                    str(row.get("valid_from")),
                ),
            )
        )
        source_rights_states = Counter(
            str(factors[event_id].get("factor_state"))
            for event_id, event in events.items()
            if event.get("action_type") == "RIGHTS" and event_id in factors
        )
        effective_factor_states = {
            "FACTOR_CERTIFIED_MULTIPLICATIVE": len(accepted),
            "FACTOR_NON_MULTIPLICATIVE": outcome_counts[
                ValidationOutcome.FACTOR_NON_MULTIPLICATIVE.value
            ],
            "FACTOR_UNRESOLVED": len(unresolved_validation),
        }
        adjusted_ready = (
            not remaining
            and len(validation) == 705
            and materialization["required_row_count"]
            == materialization["adjusted_row_count"]
            and materialization["invalid_adjusted_row_count"] == 0
            and materialization["duplicate_adjusted_row_count"] == 0
            and raw_before == raw_after
        )
        before_after = _before_after(
            baseline_b4_output,
            validation,
        )
        resolution_counts = _resolution_counts(
            baseline_b4_output,
            before_after,
        )
        named_cases = tuple(
            _named_case(symbol, validation)
            for symbol in ("TATAPOWER", "HINDMOTOR", "VASWANI", "MINDACORP")
        )
        source_manifest = _source_manifest(htr010b_output, events)
        htr010b_price_basis_states = _price_basis_state_counts(htr010b_output)
        summary: dict[str, Any] = {
            "contract_version": DSI010B5_CONTRACT_VERSION,
            "calculation_version": DSI010B5_CALCULATION_VERSION,
            "production_influence": PRODUCTION_INFLUENCE,
            "full_benchmark_replays": 0,
            "starting_residual_case_count": int(
                baseline.get("remaining_case_count", 66)
            ),
            "material_validation_case_count": len(validation),
            "validation_outcome_counts": dict(sorted(outcome_counts.items())),
            "unresolved_validation_case_count": len(unresolved_validation),
            "accepted_multiplicative_factor_count": len(accepted),
            "non_multiplicative_event_count": outcome_counts[
                ValidationOutcome.FACTOR_NON_MULTIPLICATIVE.value
            ],
            "final_effective_factor_state_counts": effective_factor_states,
            "source_rights_factor_state_counts": dict(
                sorted(source_rights_states.items())
            ),
            "event_resolution_counts": resolution_counts,
            "required_adjustment_row_count": materialization["required_row_count"],
            "adjusted_row_count_before": int(baseline.get("adjusted_rows_after", 0)),
            "adjusted_row_count_after": materialization["adjusted_row_count"],
            "exact_isin_adjusted_row_count": materialization[
                "exact_isin_adjusted_row_count"
            ],
            "certified_bridge_adjusted_row_count": materialization[
                "certified_bridge_adjusted_row_count"
            ],
            "unresolved_identity_adjustment_row_count": materialization[
                "unresolved_identity_adjustment_row_count"
            ],
            "unresolved_identity_count": materialization["unresolved_identity_count"],
            "unresolved_identity_segment_count": materialization[
                "unresolved_identity_segment_count"
            ],
            "mixed_price_basis_intervals_before": int(
                baseline.get("mixed_price_basis_intervals_after", 349)
            ),
            "mixed_price_basis_intervals_after": materialization[
                "unresolved_identity_count"
            ],
            "mixed_price_basis_interval_comparison_basis": (
                "ONE_2005_2015_INTERVAL_PER_GOVERNED_IDENTITY"
            ),
            "htr010b_price_basis_state_counts_after_event_rebuild": (
                htr010b_price_basis_states
            ),
            "invalid_adjusted_row_count": materialization["invalid_adjusted_row_count"],
            "duplicate_adjusted_row_count": materialization[
                "duplicate_adjusted_row_count"
            ],
            "adjusted_history_logical_sha256": materialization[
                "adjusted_history_logical_sha256"
            ],
            "raw_candle_fingerprint_before": raw_before,
            "raw_candle_fingerprint_after": raw_after,
            "raw_candles_unchanged": raw_before == raw_after,
            "security_periods_excluded": False,
            "unresolved_rows_preserved_in_raw_warehouse": True,
            "full_history_identity_certification_scope": (
                "EXACT_ISIN_OR_CERTIFIED_DATED_OFFICIAL_IDENTITY_BRIDGE"
            ),
            "adjusted_replay_ready": adjusted_ready,
            "readiness": (
                "ADJUSTED_REPLAY_CERTIFIED"
                if adjusted_ready
                else "BLOCKED_BY_UNCERTIFIED_PRE_EVENT_IDENTITY_HISTORY"
            ),
            "policy_or_production_behaviour_changed": False,
        }
        certificate = {
            "summary": summary,
            "before_after_sha256": _digest(before_after),
            "remaining_blockers_sha256": _digest(remaining),
            "factor_ledger_sha256": _digest(factor_ledger),
            "source_manifest_sha256": _digest(source_manifest),
            "named_cases_sha256": _digest(named_cases),
        }
        certificate_sha = _digest(certificate)
        summary["certificate_sha256"] = certificate_sha
        return FinalOfficialEvidenceClosureReport(
            summary=summary,
            before_after=before_after,
            remaining_blockers=remaining,
            factor_ledger=factor_ledger,
            source_manifest=source_manifest,
            named_cases=named_cases,
            certificate_sha256=certificate_sha,
        )


class FinalOfficialEvidenceClosureExporter:
    """Write deterministic B5 artifacts without rewriting source evidence."""

    def export(
        self,
        report: FinalOfficialEvidenceClosureReport,
        output: Path,
    ) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        paths = [
            _write_json(output / "dsi010b5_closure_summary.json", report.summary),
            _write_json(
                output / "dsi010b5_adjusted_replay_certificate.json",
                {
                    **report.summary,
                    "certificate_sha256": report.certificate_sha256,
                },
            ),
        ]
        for stem, rows in (
            ("dsi010b5_before_after_residual_ledger", report.before_after),
            ("dsi010b5_remaining_blockers", report.remaining_blockers),
            ("dsi010b5_factor_ledger", report.factor_ledger),
            ("dsi010b5_official_source_manifest", report.source_manifest),
            ("dsi010b5_named_case_outcomes", report.named_cases),
        ):
            paths.extend(_write_pair(output, stem, rows))
        paths.append(_write_markdown(output / "dsi010b5_executive_report.md", report))
        return tuple(paths)


def _accepted_factors(
    validation: Sequence[dict[str, Any]],
    events: Mapping[str, dict[str, Any]],
    factors: Mapping[str, dict[str, Any]],
) -> tuple[tuple[AcceptedFactor, ...], tuple[dict[str, Any], ...]]:
    accepted: list[AcceptedFactor] = []
    ledger: list[dict[str, Any]] = []
    for result in sorted(validation, key=lambda row: str(row.get("event_id"))):
        event_id = str(result.get("event_id") or "")
        event = events.get(event_id)
        factor = factors.get(event_id)
        if event is None or factor is None:
            raise ValueError(f"validation event missing canonical inputs: {event_id}")
        outcome = str(result.get("validation_outcome") or "")
        if str(event.get("action_type")) not in _MATERIAL_ACTIONS:
            raise ValueError(f"non-material event entered B5 validation: {event_id}")
        price = _positive_number(result.get("price_factor"))
        quantity = _effective_quantity_factor(result, factor)
        terminal = outcome in (
            _TERMINAL_MULTIPLICATIVE_OUTCOMES | _TERMINAL_NON_MULTIPLICATIVE_OUTCOMES
        )
        if not terminal:
            ledger.append(_factor_ledger_row(result, event, factor, False))
            continue
        if outcome in _TERMINAL_MULTIPLICATIVE_OUTCOMES:
            if price is None or quantity is None:
                raise ValueError(
                    f"terminal multiplicative event lacks factor values: {event_id}"
                )
            series = tuple(event.get("series_applicability") or ())
            if len(series) != 1:
                raise ValueError(
                    f"material event lacks exact series applicability: {event_id}"
                )
            accepted.append(
                AcceptedFactor(
                    event_id=event_id,
                    factor_id=str(factor.get("factor_id") or ""),
                    identity_key=str(factor.get("identity_key") or ""),
                    symbol=str(event.get("symbol") or "").upper(),
                    series=str(series[0]).upper(),
                    effective_date=_required_date(event.get("effective_date")),
                    price_factor=price,
                    quantity_factor=quantity,
                    validation_outcome=outcome,
                )
            )
        ledger.append(_factor_ledger_row(result, event, factor, True))
    return tuple(accepted), tuple(ledger)


def _factor_ledger_row(
    result: Mapping[str, Any],
    event: Mapping[str, Any],
    factor: Mapping[str, Any],
    terminal: bool,
) -> dict[str, Any]:
    return {
        "event_id": result.get("event_id"),
        "factor_id": factor.get("factor_id"),
        "identity_key": factor.get("identity_key"),
        "symbol": event.get("symbol"),
        "series": event.get("series_applicability"),
        "action_type": event.get("action_type"),
        "effective_date": event.get("effective_date"),
        "factor_state": result.get("factor_state"),
        "price_factor": result.get("price_factor"),
        "quantity_factor": _effective_quantity_factor(result, factor),
        "validation_outcome": result.get("validation_outcome"),
        "continuity_testable": result.get("continuity_testable", True),
        "terminal": terminal,
        "production_influence": False,
    }


def _effective_quantity_factor(
    result: Mapping[str, Any],
    factor: Mapping[str, Any],
) -> float | None:
    certification = result.get("governed_reference_certification")
    if isinstance(certification, Mapping):
        governed = _positive_number(certification.get("quantity_factor"))
        if governed is not None:
            return governed
    return _positive_number(factor.get("quantity_factor"))


def _materialize_governed_adjustments(
    *,
    database_path: Path,
    output_database: Path,
    bridge: LegacyIsinReferenceBridge,
    events: Mapping[str, dict[str, Any]],
    accepted: Sequence[AcceptedFactor],
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    output_database.parent.mkdir(parents=True, exist_ok=True)
    aliases: dict[str, set[str]] = defaultdict(set)
    for event in events.values():
        identity = str(event.get("governed_identity_id") or "")
        symbol = str(event.get("symbol") or "").upper()
        if identity and symbol:
            aliases[symbol].add(identity)
    factors_by_identity: dict[str, list[AcceptedFactor]] = defaultdict(list)
    factors_by_symbol: dict[str, list[AcceptedFactor]] = defaultdict(list)
    for factor in accepted:
        factors_by_identity[factor.identity_key].append(factor)
        factors_by_symbol[factor.symbol].append(factor)
    for symbol, identities in aliases.items():
        for identity in identities:
            factors_by_symbol[symbol].extend(factors_by_identity.get(identity, ()))
    factors_by_symbol = {
        symbol: list({factor.event_id: factor for factor in rows}.values())
        for symbol, rows in factors_by_symbol.items()
    }

    missing_rows = _missing_isin_candidates(
        database_path,
        factors_by_symbol,
        start_date,
        end_date,
    )
    bridged: list[tuple[object, ...]] = []
    rejected: list[tuple[object, ...]] = []
    grouped_rejections: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in missing_rows:
        trading_date, exchange, symbol, series, source_sha, candidates = row
        decisions = []
        certified = []
        for identity in candidates:
            result = bridge.resolve(
                identity_key=identity,
                symbol=symbol,
                series=series,
                isin=identity.removeprefix("nse:isin:"),
                reference_date=trading_date,
            )
            decisions.append(result.decision.value)
            if result.certified:
                certified.append((identity, result))
        if len(certified) == 1:
            identity, result = certified[0]
            bridged.append(
                (
                    trading_date,
                    exchange,
                    symbol,
                    series,
                    source_sha,
                    identity,
                    result.decision.value,
                    result.source_contract_id,
                    result.source_report_sha256,
                )
            )
            continue
        reason = (
            "MULTIPLE_CERTIFIED_IDENTITIES"
            if len(certified) > 1
            else "|".join(sorted(set(decisions))) or "NO_CANDIDATE_IDENTITY"
        )
        candidate_text = "|".join(sorted(candidates))
        rejected.append(
            (
                trading_date,
                exchange,
                symbol,
                series,
                source_sha,
                candidate_text,
                reason,
            )
        )
        key = (symbol, series, candidate_text, reason)
        current = grouped_rejections.get(key)
        if current is None:
            grouped_rejections[key] = {
                "blocker_type": "UNCERTIFIED_PRE_EVENT_IDENTITY_HISTORY",
                "identity_key": candidate_text,
                "symbol": symbol,
                "series": series,
                "valid_from": trading_date.isoformat(),
                "valid_to": trading_date.isoformat(),
                "affected_row_count": 1,
                "missing_official_fact": (
                    "Effective-dated official ISIN, symbol and series interval "
                    "covering the pre-action candle."
                ),
                "bridge_rejection_reason": reason,
                "production_influence": False,
            }
        else:
            current["valid_to"] = trading_date.isoformat()
            current["affected_row_count"] = int(current["affected_row_count"]) + 1

    connection = duckdb.connect(str(output_database))
    try:
        _create_materialization_tables(connection)
        _insert_factors(connection, accepted)
        if bridged:
            connection.executemany(
                "INSERT INTO governed_missing_isin_identity VALUES (?,?,?,?,?,?,?,?,?)",
                bridged,
            )
        if rejected:
            connection.executemany(
                "INSERT INTO rejected_missing_isin_identity VALUES (?,?,?,?,?,?,?)",
                rejected,
            )
        escaped = str(database_path).replace("'", "''")
        connection.execute(f"ATTACH '{escaped}' AS source_db (READ_ONLY)")
        _create_adjusted_rows(connection, start_date, end_date)
        counts = _materialization_counts(connection)
        logical_digest = _adjusted_logical_digest(connection)
        connection.execute("DETACH source_db")
    finally:
        connection.close()
    return {
        **counts,
        "adjusted_history_logical_sha256": logical_digest,
        "identity_blockers": tuple(grouped_rejections.values()),
        "unresolved_identity_count": len(
            {
                identity
                for row in grouped_rejections.values()
                for identity in str(row["identity_key"]).split("|")
                if identity
            }
        ),
        "unresolved_identity_segment_count": len(grouped_rejections),
    }


def _missing_isin_candidates(
    database_path: Path,
    factors_by_symbol: Mapping[str, Sequence[AcceptedFactor]],
    start_date: date,
    end_date: date,
) -> tuple[tuple[date, str, str, str, str, tuple[str, ...]], ...]:
    rows = []
    symbols = tuple(sorted(factors_by_symbol))
    if not symbols:
        return ()
    with duckdb.connect(str(database_path), read_only=True) as connection:
        connection.execute("CREATE TEMP TABLE factor_symbol(symbol VARCHAR)")
        connection.executemany(
            "INSERT INTO factor_symbol VALUES (?)",
            [(symbol,) for symbol in symbols],
        )
        candidates = connection.execute(
            """
            SELECT c.trading_date, c.exchange, upper(c.symbol), upper(c.series),
                   c.source_sha256
            FROM daily_candle c
            JOIN factor_symbol s ON upper(c.symbol)=s.symbol
            WHERE c.trading_date BETWEEN ? AND ?
              AND (c.isin IS NULL OR trim(c.isin)='')
            ORDER BY c.trading_date, c.exchange, c.symbol, c.series
            """,
            [start_date, end_date],
        ).fetchall()
    for trading_date, exchange, symbol, series, source_sha in candidates:
        identities = {
            factor.identity_key
            for factor in factors_by_symbol.get(str(symbol), ())
            if trading_date < factor.effective_date
        }
        if identities:
            rows.append(
                (
                    trading_date,
                    str(exchange),
                    str(symbol),
                    str(series),
                    str(source_sha or ""),
                    tuple(sorted(identities)),
                )
            )
    return tuple(rows)


def _create_materialization_tables(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute("DROP TABLE IF EXISTS accepted_adjustment_factor")
    connection.execute(
        """
        CREATE TABLE accepted_adjustment_factor(
            event_id VARCHAR, factor_id VARCHAR, identity_key VARCHAR,
            symbol VARCHAR, series VARCHAR, effective_date DATE,
            price_factor DOUBLE, quantity_factor DOUBLE,
            validation_outcome VARCHAR
        )
        """
    )
    connection.execute("DROP TABLE IF EXISTS governed_missing_isin_identity")
    connection.execute(
        """
        CREATE TABLE governed_missing_isin_identity(
            trading_date DATE, exchange VARCHAR, symbol VARCHAR, series VARCHAR,
            source_sha256 VARCHAR, identity_key VARCHAR, identity_state VARCHAR,
            bridge_contract_id VARCHAR, bridge_report_sha256 VARCHAR
        )
        """
    )
    connection.execute("DROP TABLE IF EXISTS rejected_missing_isin_identity")
    connection.execute(
        """
        CREATE TABLE rejected_missing_isin_identity(
            trading_date DATE, exchange VARCHAR, symbol VARCHAR, series VARCHAR,
            source_sha256 VARCHAR, candidate_identity_keys VARCHAR,
            rejection_reason VARCHAR
        )
        """
    )


def _insert_factors(
    connection: duckdb.DuckDBPyConnection,
    accepted: Sequence[AcceptedFactor],
) -> None:
    if accepted:
        connection.executemany(
            "INSERT INTO accepted_adjustment_factor VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (
                    row.event_id,
                    row.factor_id,
                    row.identity_key,
                    row.symbol,
                    row.series,
                    row.effective_date,
                    row.price_factor,
                    row.quantity_factor,
                    row.validation_outcome,
                )
                for row in accepted
            ],
        )


def _create_adjusted_rows(
    connection: duckdb.DuckDBPyConnection,
    start_date: date,
    end_date: date,
) -> None:
    connection.execute("DROP TABLE IF EXISTS governed_adjusted_daily_candle")
    connection.execute(
        """
        CREATE TABLE governed_adjusted_daily_candle AS
        WITH governed AS (
            SELECT c.*, 'nse:isin:' || upper(trim(c.isin)) AS identity_key,
                   'EXACT_ISIN_CANDLE' AS identity_state
            FROM source_db.daily_candle c
            WHERE c.trading_date BETWEEN ? AND ?
              AND c.isin IS NOT NULL AND trim(c.isin)<>''
              AND EXISTS (
                  SELECT 1 FROM accepted_adjustment_factor f
                  WHERE f.identity_key='nse:isin:' || upper(trim(c.isin))
                    AND c.trading_date<f.effective_date
              )
            UNION ALL
            SELECT c.*, m.identity_key, 'CERTIFIED_DATED_BRIDGE_CANDLE'
            FROM source_db.daily_candle c
            JOIN governed_missing_isin_identity m
              USING(trading_date,exchange,symbol,series,source_sha256)
        ),
        adjusted AS (
            SELECT g.trading_date, g.exchange, g.symbol, g.series, g.isin,
                   g.identity_key, g.identity_state, g.open_price AS raw_open,
                   g.high_price AS raw_high, g.low_price AS raw_low,
                   g.close_price AS raw_close, g.volume AS raw_volume,
                   g.source_sha256,
                   exp(sum(ln(f.price_factor))) AS price_factor,
                   exp(sum(ln(f.quantity_factor))) AS quantity_factor,
                   string_agg(f.event_id, ',' ORDER BY f.effective_date,f.event_id)
                       AS event_ids,
                   string_agg(f.factor_id, ',' ORDER BY f.effective_date,f.factor_id)
                       AS factor_ids,
                   max(f.effective_date) AS latest_factor_date
            FROM governed g
            JOIN accepted_adjustment_factor f
              ON f.identity_key=g.identity_key
             AND g.trading_date<f.effective_date
            GROUP BY g.trading_date,g.exchange,g.symbol,g.series,g.isin,
                     g.identity_key,g.identity_state,g.open_price,g.high_price,
                     g.low_price,g.close_price,g.volume,g.source_sha256
        )
        SELECT ? AS contract_version, trading_date, exchange, symbol, series,
               isin, identity_key,
               identity_state, raw_open, raw_high, raw_low, raw_close, raw_volume,
               source_sha256, price_factor, quantity_factor,
               raw_open*price_factor AS adjusted_open,
               raw_high*price_factor AS adjusted_high,
               raw_low*price_factor AS adjusted_low,
               raw_close*price_factor AS adjusted_close,
               CAST(round(raw_volume*quantity_factor) AS BIGINT) AS adjusted_volume,
               event_ids, factor_ids, latest_factor_date,
               sha256(coalesce(source_sha256,'') || '|' || factor_ids || '|' || ?)
                   AS lineage_sha256
        FROM adjusted
        """,
        [
            start_date,
            end_date,
            DSI010B5_CONTRACT_VERSION,
            DSI010B5_CALCULATION_VERSION,
        ],
    )


def _materialization_counts(
    connection: duckdb.DuckDBPyConnection,
) -> dict[str, int]:
    adjusted = _scalar_int(
        connection,
        "SELECT count(*) FROM governed_adjusted_daily_candle",
    )
    bridged = _scalar_int(
        connection,
        "SELECT count(*) FROM governed_adjusted_daily_candle "
        "WHERE identity_state='CERTIFIED_DATED_BRIDGE_CANDLE'",
    )
    rejected = _scalar_int(
        connection,
        "SELECT count(*) FROM rejected_missing_isin_identity",
    )
    duplicates = _scalar_int(
        connection,
        """
        SELECT count(*) FROM (
            SELECT trading_date,exchange,symbol,series,count(*) AS n
            FROM governed_adjusted_daily_candle
            GROUP BY ALL HAVING n>1
        )
        """,
    )
    invalid = _scalar_int(
        connection,
        """
        SELECT count(*) FROM governed_adjusted_daily_candle
        WHERE adjusted_open<=0 OR adjusted_high<=0 OR adjusted_low<=0
           OR adjusted_close<=0 OR price_factor<=0 OR quantity_factor<=0
        """,
    )
    return {
        "required_row_count": adjusted + rejected,
        "adjusted_row_count": adjusted,
        "exact_isin_adjusted_row_count": adjusted - bridged,
        "certified_bridge_adjusted_row_count": bridged,
        "unresolved_identity_adjustment_row_count": rejected,
        "duplicate_adjusted_row_count": duplicates,
        "invalid_adjusted_row_count": invalid,
    }


def _adjusted_logical_digest(connection: duckdb.DuckDBPyConnection) -> str:
    cursor = connection.execute(
        """
        SELECT *
        FROM governed_adjusted_daily_candle
        ORDER BY trading_date,exchange,symbol,series,identity_key,source_sha256
        """
    )
    digest = sha256()
    row_count = 0
    while rows := cursor.fetchmany(10_000):
        for row in rows:
            digest.update(
                json.dumps(
                    row,
                    default=str,
                    ensure_ascii=True,
                    separators=(",", ":"),
                ).encode()
            )
            digest.update(b"\n")
            row_count += 1
    if row_count == 0:
        raise RuntimeError("adjusted history digest query returned no rows")
    return digest.hexdigest()


def _scalar_int(
    connection: duckdb.DuckDBPyConnection,
    query: str,
) -> int:
    row = connection.execute(query).fetchone()
    if row is None:
        raise RuntimeError("materialization count query returned no row")
    return int(row[0])


def _before_after(
    baseline_b4_output: Path,
    validation: Sequence[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    baseline_path = baseline_b4_output / "dsi010b4_remaining_blockers.json"
    baseline = _records(baseline_path) if baseline_path.exists() else []
    final = {str(row.get("event_id")): row for row in validation}
    rows = []
    for row in baseline:
        event_id = str(row.get("event_id") or "")
        outcome = final.get(event_id, {})
        rows.append(
            {
                "event_id": event_id,
                "symbol": outcome.get("symbol") or row.get("symbol"),
                "action_type": outcome.get("action_type") or row.get("action_type"),
                "old_validation_outcome": row.get("validation_outcome")
                or row.get("new_validation_outcome"),
                "final_validation_outcome": outcome.get("validation_outcome"),
                "resolved": str(outcome.get("validation_outcome"))
                not in _UNRESOLVED_OUTCOMES,
                "production_influence": False,
            }
        )
    return tuple(rows)


def _resolution_counts(
    baseline_b4_output: Path,
    before_after: Sequence[dict[str, Any]],
) -> dict[str, int]:
    baseline_path = baseline_b4_output / "dsi010b4_remaining_blockers.json"
    baseline = _records(baseline_path) if baseline_path.exists() else []
    resolved_ids = {
        str(row.get("event_id")) for row in before_after if bool(row.get("resolved"))
    }
    counts = Counter(
        str(row.get("missing_component") or "UNCLASSIFIED")
        for row in baseline
        if str(row.get("event_id")) in resolved_ids
    )
    counts["TOTAL_STARTING_CASES"] = len(baseline)
    counts["TOTAL_RESOLVED_CASES"] = len(resolved_ids)
    counts["TOTAL_REMAINING_EVENT_CASES"] = len(baseline) - len(resolved_ids)
    return dict(sorted(counts.items()))


def _event_blockers(
    rows: Sequence[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "blocker_type": "UNRESOLVED_MATERIAL_FACTOR_VALIDATION",
            "event_id": row.get("event_id"),
            "identity_key": row.get("identity_key"),
            "symbol": row.get("symbol"),
            "series": row.get("series"),
            "valid_from": row.get("effective_date"),
            "valid_to": row.get("effective_date"),
            "validation_outcome": row.get("validation_outcome"),
            "missing_official_fact": row.get("recomputed_continuity_state"),
            "production_influence": False,
        }
        for row in rows
    )


def _named_case(
    symbol: str,
    validation: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    rows = [
        {
            "event_id": row.get("event_id"),
            "effective_date": row.get("effective_date"),
            "validation_outcome": row.get("validation_outcome"),
            "continuity_testable": row.get("continuity_testable", True),
        }
        for row in validation
        if str(row.get("symbol")) == symbol
    ]
    return {
        "symbol": symbol,
        "event_count": len(rows),
        "outcomes": rows,
        "production_influence": False,
    }


def _source_manifest(
    output: Path,
    events: Mapping[str, dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    paths = (
        output / "htr010b_source_completeness.json",
        output / "htr010b_executive_report.json",
        output / "htr010b_adjustment_factors.json",
        output / "htr010b_canonical_events.json",
    )
    rows = [
        {
            "source_kind": "GOVERNED_INPUT_ARTIFACT",
            "source_id": path.name,
            "path": path.name,
            "source_url": None,
            "sha256": sha256(path.read_bytes()).hexdigest(),
            "production_influence": False,
        }
        for path in paths
    ]
    official: dict[str, dict[str, Any]] = {}
    for event in events.values():
        supplement = event.get("official_term_supplement")
        if not isinstance(supplement, Mapping):
            continue
        source_sha = str(supplement.get("source_sha256") or "")
        if not source_sha:
            continue
        official[source_sha] = {
            "source_kind": "OFFICIAL_CORPORATE_ACTION_SUPPLEMENT",
            "source_id": supplement.get("supplement_id"),
            "path": supplement.get("immutable_path"),
            "source_url": supplement.get("source_url"),
            "sha256": source_sha,
            "production_influence": False,
        }
    rows.extend(official[key] for key in sorted(official))
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                str(row.get("source_kind")),
                str(row.get("source_id")),
                str(row.get("sha256")),
            ),
        )
    )


def _price_basis_state_counts(output: Path) -> dict[str, int]:
    rows = _records(output / "htr010b_price_basis_intervals.json")
    return dict(
        sorted(Counter(str(row.get("price_basis_state")) for row in rows).items())
    )


def _validate_b1e2(
    output: Path,
    validation: Sequence[dict[str, Any]],
) -> None:
    report = _object(output / "htr010b1_executive_report.json")
    if report.get("contract_version") != "HTR-010B1E2-v1.0.0":
        raise ValueError("final admission output is not HTR-010B1E2")
    readiness = _object(output / "htr010b1_replay_readiness.json")
    if int(readiness.get("final_unresolved_interval_count", -1)) != 0:
        raise ValueError("final admission output has unresolved intervals")
    final_rows = _records(output / "htr010b1_factor_validation_results.json")
    expected = {
        (str(row.get("event_id")), str(row.get("validation_outcome")))
        for row in validation
    }
    actual = {
        (str(row.get("event_id")), str(row.get("validation_outcome")))
        for row in final_rows
    }
    if actual != expected:
        raise ValueError("B1C and B1E2 factor validation populations differ")


def _baseline_b4(output: Path) -> dict[str, Any]:
    path = output / "dsi010b4_closure_summary.json"
    return _object(path) if path.exists() else {}


def _raw_candle_fingerprint(path: Path) -> str:
    with duckdb.connect(str(path), read_only=True) as connection:
        row = connection.execute(
            "SELECT COUNT(*), MIN(trading_date), MAX(trading_date), SUM(volume), "
            "COUNT(DISTINCT source_sha256) FROM daily_candle"
        ).fetchone()
    if row is None:
        raise RuntimeError("raw candle fingerprint query returned no row")
    return sha256("|".join(str(item) for item in row).encode()).hexdigest()


def _indexed(path: Path, key: str) -> dict[str, dict[str, Any]]:
    rows = _records(path)
    result = {str(row.get(key) or ""): row for row in rows}
    if "" in result or len(result) != len(rows):
        raise ValueError(f"{path} must contain unique non-empty {key} values")
    return result


def _records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("records") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"{path} must contain a JSON record list")
    return rows


def _object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _required_date(value: object) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"invalid required date: {value!r}")


def _positive_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number > 0 else None


def _digest(value: Any) -> str:
    return sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


def _write_json(path: Path, value: Any) -> Path:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return path


def _write_pair(
    output: Path,
    stem: str,
    rows: Sequence[dict[str, Any]],
) -> tuple[Path, Path]:
    json_path = _write_json(output / f"{stem}.json", rows)
    csv_path = output / f"{stem}.csv"
    fields = sorted({key for row in rows for key in row})
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(row.get(key), sort_keys=True)
                    if isinstance(row.get(key), (dict, list, tuple))
                    else row.get(key)
                    for key in fields
                }
            )
    return json_path, csv_path


def _write_markdown(
    path: Path,
    report: FinalOfficialEvidenceClosureReport,
) -> Path:
    summary = report.summary
    lines = [
        "# DSI-010B5 Final Official-Evidence Closure",
        "",
        f"- Starting event blockers: {summary['starting_residual_case_count']}",
        (
            "- Final material validation outcomes: "
            f"{summary['validation_outcome_counts']}"
        ),
        (
            "- Governed adjustment rows: "
            f"{summary['adjusted_row_count_after']:,} / "
            f"{summary['required_adjustment_row_count']:,}"
        ),
        (
            "- Uncertified pre-event identity rows: "
            f"{summary['unresolved_identity_adjustment_row_count']:,}"
        ),
        (
            "- Mixed price-basis governed identities: "
            f"{summary['mixed_price_basis_intervals_before']} -> "
            f"{summary['mixed_price_basis_intervals_after']}"
        ),
        (
            "- Unresolved identity date/series segments: "
            f"{summary['unresolved_identity_segment_count']}"
        ),
        f"- Readiness: {summary['readiness']}",
        f"- Raw candles unchanged: {summary['raw_candles_unchanged']}",
        "- Full benchmark replays: 0",
        "- Production influence: false",
        "",
        "The official factor population is closed. Adjusted replay remains fail-closed "
        "where pre-event candles omit ISIN and no signed effective-dated identity "
        "interval covers the candle date. No ticker-only identity assignment is used.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


__all__ = [
    "DSI010B5_CONTRACT_VERSION",
    "FinalOfficialEvidenceClosureEngine",
    "FinalOfficialEvidenceClosureExporter",
    "FinalOfficialEvidenceClosureReport",
    "PRODUCTION_INFLUENCE",
]
