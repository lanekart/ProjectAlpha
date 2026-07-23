"""Governed raw-versus-adjusted benchmark integration for HTR-010B2."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import duckdb
import pandas as pd

from alpha.benchmark_replay.engine import CanonicalBenchmarkReplayEngine
from alpha.benchmark_replay.exporting import BenchmarkArtifactExporter
from alpha.benchmark_replay.models import (
    BenchmarkPolicy,
    BenchmarkReplayReport,
    ReplayRequest,
)
from alpha.canonical_universe_audit.models import DatasetManifest
from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.historical_replay.governed_artifacts import load_governed_replay_inputs
from alpha.historical_truth.b1_final_closure import HTR010B1_FINAL_CONTRACT_VERSION
from alpha.historical_truth.b1_shadow_universe import load_b1_shadow_admission
from alpha.recovery.replay_frame import CanonicalReplayFrameAdapter

HTR010B2_CONTRACT_VERSION = "HTR-010B2-v1.0.0"
_READY_STATES = {
    "READY_FOR_GOVERNED_ADJUSTED_REPLAY",
    "READY_WITH_GOVERNED_EXCLUSIONS",
}
_B2_READY = "READY_FOR_GOVERNED_ADJUSTED_BENCHMARK_RESEARCH"
_B2_BLOCKED = "BLOCKED_BY_BENCHMARK_PARITY_DIVERGENCE"
_PRICE_COLUMNS = (
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "sector",
    "exchange",
)


class GovernedBenchmarkStore(LegacyMarketDataStore):
    """Read-only benchmark store carrying an explicit governed price view."""

    def __init__(self, path: Path, *, price_view: str) -> None:
        self.price_view = price_view
        super().__init__(path)

    def manifest(self) -> DatasetManifest:
        row = self.connection.execute(
            """
            SELECT
                COUNT(*),
                COUNT(DISTINCT symbol),
                COUNT(DISTINCT trade_date),
                MIN(trade_date),
                MAX(trade_date),
                COUNT(sector),
                STRING_AGG(DISTINCT exchange, ', ' ORDER BY exchange)
            FROM daily_prices
            """
        ).fetchone()
        if row is None or row[3] is None or row[4] is None:
            raise ValueError("governed benchmark population is empty")
        return DatasetManifest(
            dataset_version=f"HTR010B2_GOVERNED_{self.price_view}_V1",
            first_session=row[3],
            last_session=row[4],
            sessions=int(row[2]),
            rows=int(row[0]),
            symbols=int(row[1]),
            exchange=str(row[6]),
            sector_rows=int(row[5]),
            confidence=Decimal("1"),
            labels=(
                "GOVERNED",
                "HTR-010B2",
                f"PRICE_VIEW={self.price_view}",
                "PRODUCTION_INFLUENCE=false",
            ),
        )


@dataclass(slots=True)
class GovernedBenchmarkStorePair:
    """Materialized stores and lineage shared by both benchmark arms."""

    raw: GovernedBenchmarkStore
    adjusted: GovernedBenchmarkStore
    identity_session_sha256: str
    source_replay_dates: tuple[date, ...]
    materialized_replay_dates: tuple[date, ...]
    canonical_attestation_sha256s: tuple[str, ...]
    final_closure_report_sha256: str
    admission_contract_sha256: str
    governed_input_manifest_sha256: str

    def close(self) -> None:
        self.raw.close()
        self.adjusted.close()


@dataclass(frozen=True, slots=True)
class GovernedAdjustedBenchmarkResult:
    """Paired benchmark reports plus the B2 integration decision."""

    raw_report: BenchmarkReplayReport
    adjusted_report: BenchmarkReplayReport
    report: dict[str, Any]


class GovernedAdjustedBenchmarkEngine:
    """Run the unchanged benchmark stack over paired governed price views."""

    def run(
        self,
        *,
        source: LegacyMarketDataStore,
        identity_artifact: Path,
        corporate_action_artifact: Path,
        final_closure_report: Path,
        admission_contract: Path,
        identity_admission: Path,
        raw_universe: Path,
        adjusted_universe: Path,
        output: Path,
        policy: BenchmarkPolicy | None = None,
        project_root: Path | str = Path("."),
        progress: Any = None,
    ) -> GovernedAdjustedBenchmarkResult:
        pair = materialize_governed_benchmark_stores(
            source=source,
            identity_artifact=identity_artifact,
            corporate_action_artifact=corporate_action_artifact,
            final_closure_report=final_closure_report,
            admission_contract=admission_contract,
            identity_admission=identity_admission,
            raw_universe=raw_universe,
            adjusted_universe=adjusted_universe,
            output=output / "materialized",
        )
        try:
            replay_policy = policy or BenchmarkPolicy()
            request = ReplayRequest(
                start=date.fromisoformat(
                    _mapping(admission_contract)["replay_start"]
                ),
                end=date.fromisoformat(_mapping(admission_contract)["replay_end"]),
                policy=replay_policy,
            )
            engine = CanonicalBenchmarkReplayEngine()
            raw_report = engine.run(
                store=pair.raw,
                request=request,
                project_root=project_root,
                progress=progress,
            )
            adjusted_report = engine.run(
                store=pair.adjusted,
                request=request,
                project_root=project_root,
                progress=progress,
            )
        finally:
            pair.close()

        raw_paths = BenchmarkArtifactExporter().export(
            raw_report,
            output_directory=output / "raw",
        )
        adjusted_paths = BenchmarkArtifactExporter().export(
            adjusted_report,
            output_directory=output / "adjusted",
        )
        report = _integration_report(
            pair=pair,
            raw_report=raw_report,
            adjusted_report=adjusted_report,
            raw_artifact_count=len(raw_paths),
            adjusted_artifact_count=len(adjusted_paths),
        )
        export_governed_adjusted_benchmark(report, output)
        return GovernedAdjustedBenchmarkResult(
            raw_report=raw_report,
            adjusted_report=adjusted_report,
            report=report,
        )


def materialize_governed_benchmark_stores(
    *,
    source: LegacyMarketDataStore,
    identity_artifact: Path,
    corporate_action_artifact: Path,
    final_closure_report: Path,
    admission_contract: Path,
    identity_admission: Path,
    raw_universe: Path,
    adjusted_universe: Path,
    output: Path,
) -> GovernedBenchmarkStorePair:
    """Build paired read-only stores from one governed canonicalization pass."""

    closure = _validated_final_closure(final_closure_report)
    admission_mapping = _mapping(admission_contract)
    admission = load_b1_shadow_admission(
        contract_path=admission_contract,
        identity_admission_path=identity_admission,
        raw_universe_path=raw_universe,
        adjusted_universe_path=adjusted_universe,
    )
    inputs = load_governed_replay_inputs(
        identity_path=identity_artifact,
        corporate_action_path=corporate_action_artifact,
    )
    dependency_start = date.fromisoformat(str(admission_mapping["dependency_start"]))
    dependency_end = date.fromisoformat(str(admission_mapping["dependency_end"]))
    if dependency_start > admission.replay_start:
        raise ValueError("B1H dependency window does not cover replay warm-up")
    if dependency_end < admission.replay_end:
        raise ValueError("B1H dependency window does not cover replay outcomes")

    output.mkdir(parents=True, exist_ok=True)
    raw_path = output / "htr010b2_raw_benchmark.duckdb"
    adjusted_path = output / "htr010b2_adjusted_benchmark.duckdb"
    for path in (raw_path, adjusted_path):
        if path.exists():
            path.unlink()
    raw_connection = _new_database(raw_path)
    adjusted_connection = _new_database(adjusted_path)
    canonicalizer = CanonicalReplayFrameAdapter(inputs.identities, inputs.actions)
    admitted_ids = frozenset(admission.admitted_security_ids)
    identity_session_keys: list[str] = []
    attestation_sha256s: list[str] = []
    observed_security_ids: set[str] = set()

    try:
        dependency_dates = source.trade_dates(
            start=dependency_start,
            end=dependency_end,
        )
        if not dependency_dates:
            raise ValueError("source has no sessions in the B1H dependency window")
        for trading_date in dependency_dates:
            source_frame = source.find_by_trade_date(trading_date)
            admitted_frame = _admitted_source_frame(
                source_frame,
                identities=inputs.identities,
                admitted_ids=admitted_ids,
                trading_date=trading_date,
            )
            if admitted_frame.empty:
                continue
            canonical = canonicalizer.canonicalize(
                admitted_frame,
                trade_date=trading_date,
                as_of=trading_date,
            )
            adjusted_frame = canonical.frame
            raw_rows = _price_view(adjusted_frame, adjusted=False)
            adjusted_rows = _price_view(adjusted_frame, adjusted=True)
            _assert_view_parity(raw_rows, adjusted_rows)
            _insert_rows(raw_connection, raw_rows)
            _insert_rows(adjusted_connection, adjusted_rows)
            attestation_sha256s.append(canonical.attestation.attestation_sha256)
            for row in adjusted_frame.itertuples(index=False):
                security_id = str(getattr(row, "security_id"))
                symbol = str(getattr(row, "symbol"))
                observed_security_ids.add(security_id)
                identity_session_keys.append(
                    f"{security_id}|{trading_date.isoformat()}|{symbol}"
                )
        raw_connection.close()
        adjusted_connection.close()
    except Exception:
        raw_connection.close()
        adjusted_connection.close()
        raise

    missing_ids = tuple(sorted(admitted_ids.difference(observed_security_ids)))
    if missing_ids:
        raise ValueError(
            "admitted identities have no materialized benchmark rows: "
            + ",".join(missing_ids[:20])
        )

    raw_store = GovernedBenchmarkStore(raw_path, price_view="RAW")
    adjusted_store = GovernedBenchmarkStore(adjusted_path, price_view="ADJUSTED")
    source_replay_dates = source.trade_dates(
        start=admission.replay_start,
        end=admission.replay_end,
    )
    raw_dates = raw_store.trade_dates(
        start=admission.replay_start,
        end=admission.replay_end,
    )
    adjusted_dates = adjusted_store.trade_dates(
        start=admission.replay_start,
        end=admission.replay_end,
    )
    if not source_replay_dates or raw_dates != source_replay_dates:
        raw_store.close()
        adjusted_store.close()
        raise ValueError("raw benchmark sessions do not match the governed source")
    if adjusted_dates != source_replay_dates:
        raw_store.close()
        adjusted_store.close()
        raise ValueError("adjusted benchmark sessions do not match the governed source")

    return GovernedBenchmarkStorePair(
        raw=raw_store,
        adjusted=adjusted_store,
        identity_session_sha256=_digest_list(sorted(identity_session_keys)),
        source_replay_dates=source_replay_dates,
        materialized_replay_dates=raw_dates,
        canonical_attestation_sha256s=tuple(attestation_sha256s),
        final_closure_report_sha256=str(closure["report_sha256"]),
        admission_contract_sha256=admission.admission_contract_sha256,
        governed_input_manifest_sha256=inputs.manifest.manifest_sha256,
    )


def export_governed_adjusted_benchmark(
    report: dict[str, Any],
    output: Path,
) -> tuple[Path, ...]:
    """Export deterministic B2 comparison and executive artifacts."""

    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "htr010b2_governed_adjusted_benchmark_report.json"
    comparison_path = output / "htr010b2_benchmark_comparison.json"
    markdown_path = output / "htr010b2_executive_report.md"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    comparison_path.write_text(
        json.dumps(report["comparison"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    return report_path, comparison_path, markdown_path


def _validated_final_closure(path: Path) -> dict[str, Any]:
    payload = _mapping(path)
    if payload.get("contract_version") != HTR010B1_FINAL_CONTRACT_VERSION:
        raise ValueError("B2 requires the HTR-010B1 final closure contract")
    if payload.get("final_readiness_decision") not in _READY_STATES:
        raise ValueError("B1 final closure does not permit governed adjusted replay")
    if int(payload.get("contract_contradiction_count", -1)) != 0:
        raise ValueError("B1 final closure contains contract contradictions")
    if int(payload.get("implementation_defect_count", -1)) != 0:
        raise ValueError("B1 final closure contains implementation defects")
    if payload.get("adjusted_replay_integration_enabled") is not False:
        raise ValueError("B1 final closure integration state is not a clean handoff")
    if payload.get("production_influence") is not False:
        raise ValueError("B1 final closure must remain diagnostic-only")
    expected = str(payload.get("report_sha256") or "")
    if len(expected) != 64 or expected != _digest_mapping(payload):
        raise ValueError("B1 final closure digest mismatch")
    return payload


def _new_database(path: Path) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(str(path))
    connection.execute(
        """
        CREATE TABLE daily_prices (
            symbol VARCHAR NOT NULL,
            trade_date DATE NOT NULL,
            open DOUBLE NOT NULL,
            high DOUBLE NOT NULL,
            low DOUBLE NOT NULL,
            close DOUBLE NOT NULL,
            volume DOUBLE NOT NULL,
            sector VARCHAR,
            exchange VARCHAR NOT NULL,
            PRIMARY KEY (symbol, trade_date)
        )
        """
    )
    return connection


def _admitted_source_frame(
    frame: pd.DataFrame,
    *,
    identities: Any,
    admitted_ids: frozenset[str],
    trading_date: date,
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    rows: list[dict[str, Any]] = []
    for record in cast(list[dict[str, Any]], frame.to_dict("records")):
        identity = identities.resolve(
            str(record.get("symbol") or "").strip().upper(),
            trading_date=trading_date,
            exchange=str(record.get("exchange") or "").strip().upper() or None,
        )
        if identity is not None and identity.security_id in admitted_ids:
            rows.append(record)
    return pd.DataFrame(rows, columns=frame.columns)


def _price_view(frame: pd.DataFrame, *, adjusted: bool) -> pd.DataFrame:
    rows = frame.copy()
    if not adjusted:
        for column in ("open", "high", "low", "close", "volume"):
            rows[column] = rows[f"raw_{column}"]
    return rows.loc[:, _PRICE_COLUMNS].copy()


def _assert_view_parity(raw: pd.DataFrame, adjusted: pd.DataFrame) -> None:
    keys = ("symbol", "trade_date", "exchange")
    raw_keys = tuple(map(tuple, raw.loc[:, keys].astype(str).to_numpy().tolist()))
    adjusted_keys = tuple(
        map(tuple, adjusted.loc[:, keys].astype(str).to_numpy().tolist())
    )
    if raw_keys != adjusted_keys:
        raise ValueError("raw and adjusted materialized identity-session keys differ")


def _insert_rows(connection: duckdb.DuckDBPyConnection, frame: pd.DataFrame) -> None:
    connection.register("_htr010b2_rows", frame)
    try:
        connection.execute(
            """
            INSERT INTO daily_prices
            SELECT symbol, trade_date, open, high, low, close, volume, sector, exchange
            FROM _htr010b2_rows
            """
        )
    except duckdb.ConstraintException as error:
        raise ValueError("B2 materialization produced duplicate symbol/date rows") from error
    finally:
        connection.unregister("_htr010b2_rows")


def _integration_report(
    *,
    pair: GovernedBenchmarkStorePair,
    raw_report: BenchmarkReplayReport,
    adjusted_report: BenchmarkReplayReport,
    raw_artifact_count: int,
    adjusted_artifact_count: int,
) -> dict[str, Any]:
    raw = _benchmark_summary(raw_report)
    adjusted = _benchmark_summary(adjusted_report)
    parity = {
        "identity_session_sha256": pair.identity_session_sha256,
        "source_and_materialized_sessions_match": (
            pair.source_replay_dates == pair.materialized_replay_dates
        ),
        "session_counts_match": raw["session_count"] == adjusted["session_count"],
        "eligible_security_counts_match": (
            raw["eligible_security_count"] == adjusted["eligible_security_count"]
        ),
        "eligible_observation_counts_match": (
            raw["eligible_security_observation_count"]
            == adjusted["eligible_security_observation_count"]
        ),
        "source_contracts_distinct": (
            raw["dataset_version"] != adjusted["dataset_version"]
        ),
    }
    unexplained = sum(not bool(value) for key, value in parity.items() if key != "identity_session_sha256")
    deltas = {
        key: _number(adjusted.get(key)) - _number(raw.get(key))
        for key in (
            "technical_candidate_count",
            "institutional_approval_count",
            "trade_count",
            "cagr_percent",
            "maximum_drawdown_percent",
            "expectancy_percent",
        )
    }
    comparison = {
        "comparison_state": "COMPARED",
        "parity": parity,
        "metric_deltas": deltas,
        "unexplained_divergence_count": unexplained,
        "production_influence": False,
    }
    report: dict[str, Any] = {
        "contract_version": HTR010B2_CONTRACT_VERSION,
        "final_closure_report_sha256": pair.final_closure_report_sha256,
        "admission_contract_sha256": pair.admission_contract_sha256,
        "governed_input_manifest_sha256": pair.governed_input_manifest_sha256,
        "canonical_attestation_count": len(pair.canonical_attestation_sha256s),
        "canonical_attestation_sha256s": list(pair.canonical_attestation_sha256s),
        "raw_artifact_count": raw_artifact_count,
        "adjusted_artifact_count": adjusted_artifact_count,
        "raw_summary": raw,
        "adjusted_summary": adjusted,
        "comparison": comparison,
        "readiness_decision": _B2_READY if unexplained == 0 else _B2_BLOCKED,
        "governed_adjusted_benchmark_enabled": unexplained == 0,
        "active_replay_integration": False,
        "production_influence": False,
    }
    report["report_sha256"] = _digest_mapping(report)
    return report


def _benchmark_summary(report: BenchmarkReplayReport) -> dict[str, Any]:
    stats = report.portfolio_statistics
    return {
        "run_id": report.manifest.run_id,
        "dataset_version": report.manifest.versions.warehouse_sha256,
        "session_count": report.manifest.sessions,
        "eligible_security_count": report.eligible_securities,
        "eligible_security_observation_count": report.eligible_security_observations,
        "technical_candidate_count": sum(
            row.technical_candidates for row in report.candidate_statistics
        ),
        "institutional_approval_count": sum(
            row.institutional_approvals for row in report.candidate_statistics
        ),
        "trade_count": stats.logical_trades,
        "cagr_percent": stats.cagr_percent,
        "maximum_drawdown_percent": stats.maximum_drawdown_percent,
        "expectancy_percent": stats.expectancy_percent,
        "report_sha256": _digest_mapping(
            {
                "run_id": report.manifest.run_id,
                "input_hash": report.manifest.input_hash,
                "sessions": report.manifest.sessions,
                "eligible_securities": report.eligible_securities,
                "eligible_security_observations": report.eligible_security_observations,
                "logical_trades": stats.logical_trades,
                "ending_capital": str(stats.ending_capital),
            }
        ),
    }


def _mapping(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"artifact must contain a mapping: {path}")
    return dict(payload)


def _digest_mapping(value: dict[str, Any]) -> str:
    payload = dict(value)
    payload.pop("report_sha256", None)
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _digest_list(values: list[str]) -> str:
    encoded = json.dumps(values, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _number(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _markdown(report: dict[str, Any]) -> str:
    comparison = report["comparison"]
    raw = report["raw_summary"]
    adjusted = report["adjusted_summary"]
    return "\n".join(
        [
            "# HTR-010B2 Governed Adjusted Benchmark Integration",
            "",
            f"- Readiness: `{report['readiness_decision']}`",
            f"- Raw sessions: `{raw['session_count']}`",
            f"- Adjusted sessions: `{adjusted['session_count']}`",
            f"- Raw candidates: `{raw['technical_candidate_count']}`",
            f"- Adjusted candidates: `{adjusted['technical_candidate_count']}`",
            f"- Unexplained divergences: `{comparison['unexplained_divergence_count']}`",
            f"- Report SHA-256: `{report['report_sha256']}`",
            "- ACTIVE_REPLAY_INTEGRATION=false",
            "- PRODUCTION_INFLUENCE=false",
            "",
        ]
    )


__all__ = [
    "HTR010B2_CONTRACT_VERSION",
    "GovernedAdjustedBenchmarkEngine",
    "GovernedAdjustedBenchmarkResult",
    "GovernedBenchmarkStore",
    "GovernedBenchmarkStorePair",
    "export_governed_adjusted_benchmark",
    "materialize_governed_benchmark_stores",
]
