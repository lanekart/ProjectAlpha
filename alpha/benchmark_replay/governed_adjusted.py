"""Governed raw-versus-adjusted benchmark integration for HTR-010B2."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

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
from alpha.historical_replay.governed_price_repository import (
    CanonicalReplayPriceRepository,
)
from alpha.historical_truth.b1_final_closure import (
    HTR010B1_FINAL_CONTRACT_VERSION,
    final_closure_report_sha256,
)
from alpha.historical_truth.b1_shadow_universe import load_b1_shadow_admission
from alpha.recovery.security_timeline import SecurityIdentityTimeline

HTR010B2_CONTRACT_VERSION = "HTR-010B2-v1.0.0"
_READY_STATES = {
    "READY_FOR_GOVERNED_ADJUSTED_REPLAY",
    "READY_WITH_GOVERNED_EXCLUSIONS",
}
_B2_READY = "READY_FOR_GOVERNED_ADJUSTED_BENCHMARK_RESEARCH"
_B2_BLOCKED_PARITY = "BLOCKED_BY_BENCHMARK_PARITY_DIVERGENCE"
_B2_BLOCKED_EMPTY = "BLOCKED_BY_EMPTY_BENCHMARK_POPULATION"
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


class _AdmittedReplayPriceSource:
    """Restrict every raw source read to the signed B1H identity population."""

    def __init__(
        self,
        source: LegacyMarketDataStore,
        identities: SecurityIdentityTimeline,
        admitted_ids: frozenset[str],
    ) -> None:
        self.source = source
        self.identities = identities
        self.admitted_ids = admitted_ids
        self.available_dates: tuple[date, ...] | None = None

    def find_by_trade_date(self, trade_date: date) -> pd.DataFrame:
        return self._filter(self.source.find_by_trade_date(trade_date))

    def find_history_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int,
    ) -> pd.DataFrame:
        return self._filter(
            self.source.find_history_by_symbols(
                symbols=symbols,
                end_date=end_date,
                limit=limit,
            )
        )

    def find_range_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        normalized = {item.strip().upper() for item in symbols if item.strip()}
        frames: list[pd.DataFrame] = []
        for trading_date in self.source.trade_dates(start=start_date, end=end_date):
            frame = self.source.find_by_trade_date(trading_date)
            if normalized:
                selected = frame["symbol"].astype(str).str.strip().str.upper()
                frame = frame.loc[selected.isin(normalized)].copy()
            frame = self._filter(frame)
            if not frame.empty:
                frames.append(frame)
        if not frames:
            return pd.DataFrame(columns=_PRICE_COLUMNS)
        return pd.concat(frames, ignore_index=True)

    def find_trade_dates(self, *, start: date, end: date) -> tuple[date, ...]:
        dates = self.available_dates
        if dates is None:
            dates = tuple(
                trading_date
                for trading_date in self.source.trade_dates(start=start, end=end)
                if not self.find_by_trade_date(trading_date).empty
            )
        return tuple(item for item in dates if start <= item <= end)

    def close(self) -> None:
        """The owning B2 pair closes the shared source exactly once."""

    def _filter(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame.copy()
        rows: list[dict[str, Any]] = []
        for record in cast(list[dict[str, Any]], frame.to_dict("records")):
            trading_date = _as_date(record.get("trade_date"))
            if trading_date is None:
                continue
            identity = self.identities.resolve_source_identity(
                str(record.get("symbol") or "").strip().upper(),
                trading_date=trading_date,
                exchange=str(record.get("exchange") or "").strip().upper() or None,
                security_id=_optional_text(record.get("security_id")),
                isin=_optional_text(record.get("isin")),
            )
            if identity is not None and identity.security_id in self.admitted_ids:
                rows.append(record)
        return pd.DataFrame(rows, columns=frame.columns)


class GovernedBenchmarkStore(LegacyMarketDataStore):
    """Dynamic point-in-time benchmark store for one governed price view."""

    def __init__(
        self,
        *,
        path: Path,
        price_view: str,
        canonical: CanonicalReplayPriceRepository,
        manifest: DatasetManifest,
        liquidity: pd.DataFrame,
        eligibility_frame: pd.DataFrame,
        replay_dates: tuple[date, ...],
        canonical_symbols: tuple[str, ...],
    ) -> None:
        self.path = path
        self.price_view = price_view
        self._canonical = canonical
        self._manifest = manifest
        self._liquidity = liquidity
        self._eligibility_frame = eligibility_frame
        self._replay_dates = replay_dates
        self._canonical_symbols = canonical_symbols

    @property
    def canonical_attestation_sha256s(self) -> tuple[str, ...]:
        return tuple(
            item.attestation_sha256 for item in self._canonical.consumer_attestations
        )

    def manifest(self) -> DatasetManifest:
        return self._manifest

    def trade_dates(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> tuple[date, ...]:
        first = start or date.min
        last = end or date.max
        return tuple(item for item in self._replay_dates if first <= item <= last)

    def find_by_trade_date(self, trade_date: date) -> pd.DataFrame:
        return _price_view(
            self._canonical.find_by_trade_date(trade_date),
            adjusted=self.price_view == "ADJUSTED",
        )

    def find_history_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int,
    ) -> pd.DataFrame:
        return _price_view(
            self._canonical.find_history_by_symbols(
                symbols=symbols,
                end_date=end_date,
                limit=limit,
            ),
            adjusted=self.price_view == "ADJUSTED",
        )

    def find_range_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        return _price_view(
            self._canonical.find_range_by_symbols(
                symbols=symbols,
                start_date=start_date,
                end_date=end_date,
            ),
            adjusted=self.price_view == "ADJUSTED",
        )

    def history_counts_before(self, observed_on: date) -> dict[str, int]:
        if observed_on == date.min:
            return {}
        frame = self.find_history_by_symbols(
            symbols=self._canonical_symbols,
            end_date=date.fromordinal(observed_on.toordinal() - 1),
            limit=100000,
        )
        if frame.empty:
            return {}
        counts = frame.groupby("symbol", sort=True).size()
        return {str(symbol): int(count) for symbol, count in counts.items()}

    def eligible_security_count(
        self,
        *,
        start: date,
        end: date,
        minimum_history: int = 200,
    ) -> int:
        """Count eligible securities inside the signed governed population."""

        if end < start:
            raise ValueError("eligibility range end cannot precede start")
        if minimum_history < 1:
            raise ValueError("minimum history must be positive")

        frame = self._eligibility_frame
        if frame.empty:
            return 0

        valid = (
            frame["open"].astype(float).gt(0)
            & frame["high"].astype(float).gt(0)
            & frame["low"].astype(float).gt(0)
            & frame["close"].astype(float).gt(0)
            & frame["volume"].astype(float).ge(0)
        )

        through_end = frame.loc[valid & (frame["trade_date"] <= end)]
        observed = frame.loc[
            valid & (frame["trade_date"] >= start) & (frame["trade_date"] <= end),
            "symbol",
        ]

        history_counts = through_end.groupby("symbol", sort=True).size()
        observed_symbols = {str(symbol).strip().upper() for symbol in observed}

        return sum(
            int(count) >= minimum_history
            and str(symbol).strip().upper() in observed_symbols
            for symbol, count in history_counts.items()
        )

    def liquidity_statistics(self) -> pd.DataFrame:
        return self._liquidity.copy()

    def future_bars(self, candidates: pd.DataFrame, *, limit: int) -> pd.DataFrame:
        required = {"candidate_id", "symbol", "observed_on"}
        if not required.issubset(candidates.columns):
            raise ValueError("future-bar candidates require id, symbol, and date")
        if limit < 1:
            raise ValueError("future-bar limit must be positive")
        rows: list[pd.DataFrame] = []
        for candidate in candidates.itertuples(index=False):
            observed_on = _as_date(getattr(candidate, "observed_on"))
            if observed_on is None:
                continue
            future_dates = tuple(
                item for item in self._replay_dates if item > observed_on
            )[:limit]
            if not future_dates:
                continue
            frame = self.find_range_by_symbols(
                symbols=(str(getattr(candidate, "symbol")),),
                start_date=future_dates[0],
                end_date=future_dates[-1],
            )
            if frame.empty:
                continue
            frame = frame.sort_values("trade_date", kind="stable").head(limit).copy()
            frame.insert(0, "candidate_id", str(getattr(candidate, "candidate_id")))
            rows.append(frame)
        if not rows:
            return pd.DataFrame(columns=("candidate_id", *_PRICE_COLUMNS))
        return pd.concat(rows, ignore_index=True)

    def return_history(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int = 60,
    ) -> pd.DataFrame:
        frame = self.find_history_by_symbols(
            symbols=symbols,
            end_date=end_date,
            limit=limit + 1,
        )
        if frame.empty:
            return pd.DataFrame()
        frame = frame.copy()
        frame["return"] = frame.groupby("symbol", sort=False)["close"].pct_change()
        return frame.pivot(index="trade_date", columns="symbol", values="return")

    def close(self) -> None:
        """The owning pair closes the shared raw source."""

    def __enter__(self) -> GovernedBenchmarkStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


@dataclass(slots=True)
class GovernedBenchmarkStorePair:
    """Paired dynamic stores and their shared governed lineage."""

    raw: GovernedBenchmarkStore
    adjusted: GovernedBenchmarkStore
    source: LegacyMarketDataStore
    identity_session_sha256: str
    source_replay_dates: tuple[date, ...]
    final_closure_report_sha256: str
    admission_contract_sha256: str
    governed_input_manifest_sha256: str
    admitted_identity_count: int
    observed_identity_count: int
    unobserved_admitted_identity_ids: tuple[str, ...]

    @property
    def canonical_attestation_sha256s(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    *self.raw.canonical_attestation_sha256s,
                    *self.adjusted.canonical_attestation_sha256s,
                }
            )
        )

    def close(self) -> None:
        self.source.close()


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
        progress: Callable[[int, int, date], None] | None = None,
        store_progress: Callable[[int, int, date], None] | None = None,
    ) -> GovernedAdjustedBenchmarkResult:
        pair = build_governed_benchmark_stores(
            source=source,
            identity_artifact=identity_artifact,
            corporate_action_artifact=corporate_action_artifact,
            final_closure_report=final_closure_report,
            admission_contract=admission_contract,
            identity_admission=identity_admission,
            raw_universe=raw_universe,
            adjusted_universe=adjusted_universe,
            output=output / "store_contracts",
            progress=store_progress,
        )
        admission_mapping = _mapping(admission_contract)
        try:
            request = ReplayRequest(
                start=date.fromisoformat(str(admission_mapping["replay_start"])),
                end=date.fromisoformat(str(admission_mapping["replay_end"])),
                policy=policy or BenchmarkPolicy(),
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
        finally:
            pair.close()


def validate_governed_adjusted_handoff(
    *,
    final_closure_report: Path,
    admission_contract: Path,
    identity_admission: Path,
    raw_universe: Path,
    adjusted_universe: Path,
) -> None:
    """Validate signed B1/B1H handoff before loading market data."""

    _validated_final_closure(final_closure_report)
    load_b1_shadow_admission(
        contract_path=admission_contract,
        identity_admission_path=identity_admission,
        raw_universe_path=raw_universe,
        adjusted_universe_path=adjusted_universe,
    )


def build_governed_benchmark_stores(
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
    progress: Callable[[int, int, date], None] | None = None,
) -> GovernedBenchmarkStorePair:
    """Build paired point-in-time stores over one signed identity-session set."""

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

    admitted_source = _AdmittedReplayPriceSource(
        source,
        inputs.identities,
        frozenset(admission.admitted_security_ids),
    )
    identity_rows: list[dict[str, Any]] = []
    identity_session_keys: list[str] = []
    observed_ids: set[str] = set()
    available_dates: list[date] = []
    dependency_dates = source.trade_dates(
        start=dependency_start,
        end=dependency_end,
    )
    for current, trading_date in enumerate(dependency_dates, start=1):
        if progress is not None:
            progress(current, len(dependency_dates), trading_date)
        frame = admitted_source.find_by_trade_date(trading_date)
        if frame.empty:
            continue
        canonical_identity_frame = _canonical_identity_frame(
            frame,
            identities=inputs.identities,
        )
        if canonical_identity_frame.empty:
            continue
        available_dates.append(trading_date)
        identity_rows.extend(
            cast(list[dict[str, Any]], canonical_identity_frame.to_dict("records"))
        )
        for row in canonical_identity_frame.itertuples(index=False):
            security_id = str(getattr(row, "security_id"))
            symbol = str(getattr(row, "symbol"))
            observed_ids.add(security_id)
            identity_session_keys.append(
                f"{security_id}|{trading_date.isoformat()}|{symbol}"
            )
    admitted_source.available_dates = tuple(available_dates)

    admitted_ids, unobserved_ids = _identity_coverage(
        admitted_ids=admission.admitted_security_ids,
        observed_ids=observed_ids,
    )
    source_replay_dates = source.trade_dates(
        start=admission.replay_start,
        end=admission.replay_end,
    )
    admitted_replay_dates = admitted_source.find_trade_dates(
        start=admission.replay_start,
        end=admission.replay_end,
    )
    if not source_replay_dates or admitted_replay_dates != source_replay_dates:
        raise ValueError("B2 admitted sessions do not match the governed source")
    if not identity_rows:
        raise ValueError("B2 identity-session population is empty")

    identity_frame = pd.DataFrame(identity_rows)
    manifest = _manifest(identity_frame)
    liquidity = _liquidity(identity_frame)

    eligibility_frame = identity_frame.loc[
        :,
        (
            "symbol",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ),
    ].copy()
    eligibility_frame["symbol"] = (
        eligibility_frame["symbol"].astype(str).str.strip().str.upper()
    )
    eligibility_frame["trade_date"] = pd.to_datetime(
        eligibility_frame["trade_date"],
        errors="raise",
    ).dt.date

    identity_session_sha256 = _digest_list(sorted(identity_session_keys))
    output.mkdir(parents=True, exist_ok=True)
    raw_contract = _store_contract(
        output / "htr010b2_raw_store_contract.json",
        price_view="RAW",
        identity_session_sha256=identity_session_sha256,
        closure_sha256=str(closure["report_sha256"]),
        admission_sha256=admission.admission_contract_sha256,
        input_manifest_sha256=inputs.manifest.manifest_sha256,
    )
    adjusted_contract = _store_contract(
        output / "htr010b2_adjusted_store_contract.json",
        price_view="ADJUSTED",
        identity_session_sha256=identity_session_sha256,
        closure_sha256=str(closure["report_sha256"]),
        admission_sha256=admission.admission_contract_sha256,
        input_manifest_sha256=inputs.manifest.manifest_sha256,
    )
    canonical_symbols = tuple(sorted(set(admission.admitted_symbols)))
    raw_store = GovernedBenchmarkStore(
        path=raw_contract,
        price_view="RAW",
        canonical=CanonicalReplayPriceRepository(
            admitted_source,
            inputs.identities,
            inputs.actions,
        ),
        manifest=_view_manifest(manifest, "RAW"),
        liquidity=liquidity,
        eligibility_frame=eligibility_frame,
        replay_dates=tuple(available_dates),
        canonical_symbols=canonical_symbols,
    )
    adjusted_store = GovernedBenchmarkStore(
        path=adjusted_contract,
        price_view="ADJUSTED",
        canonical=CanonicalReplayPriceRepository(
            admitted_source,
            inputs.identities,
            inputs.actions,
        ),
        manifest=_view_manifest(manifest, "ADJUSTED"),
        liquidity=liquidity,
        eligibility_frame=eligibility_frame,
        replay_dates=tuple(available_dates),
        canonical_symbols=canonical_symbols,
    )
    return GovernedBenchmarkStorePair(
        raw=raw_store,
        adjusted=adjusted_store,
        source=source,
        identity_session_sha256=identity_session_sha256,
        source_replay_dates=source_replay_dates,
        final_closure_report_sha256=str(closure["report_sha256"]),
        admission_contract_sha256=admission.admission_contract_sha256,
        governed_input_manifest_sha256=inputs.manifest.manifest_sha256,
        admitted_identity_count=len(admitted_ids),
        observed_identity_count=len(observed_ids),
        unobserved_admitted_identity_ids=unobserved_ids,
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
    if len(expected) != 64 or expected != final_closure_report_sha256(payload):
        raise ValueError("B1 final closure digest mismatch")
    return payload


def _canonical_identity_frame(
    frame: pd.DataFrame,
    *,
    identities: SecurityIdentityTimeline,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for record in cast(list[dict[str, Any]], frame.to_dict("records")):
        trading_date = _as_date(record.get("trade_date"))
        if trading_date is None:
            continue
        identity = identities.resolve_source_identity(
            str(record.get("symbol") or "").strip().upper(),
            trading_date=trading_date,
            exchange=str(record.get("exchange") or "").strip().upper() or None,
            security_id=_optional_text(record.get("security_id")),
            isin=_optional_text(record.get("isin")),
        )
        if identity is None:
            continue
        rows.append(
            {
                **record,
                "security_id": identity.security_id,
                "symbol": identity.symbol,
            }
        )
    return pd.DataFrame(rows)


def _price_view(frame: pd.DataFrame, *, adjusted: bool) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=_PRICE_COLUMNS)
    rows = frame.copy()
    if not adjusted:
        for column in ("open", "high", "low", "close", "volume"):
            rows[column] = rows[f"raw_{column}"]
    return rows.loc[:, _PRICE_COLUMNS].copy()


def _manifest(frame: pd.DataFrame) -> DatasetManifest:
    parsed_dates = {_as_date(value) for value in frame["trade_date"]}
    valid_dates = tuple(sorted(item for item in parsed_dates if item is not None))
    if not valid_dates:
        raise ValueError("B2 manifest has no valid dates")
    exchanges = ", ".join(
        sorted({str(item).strip().upper() for item in frame["exchange"]})
    )
    return DatasetManifest(
        dataset_version="HTR010B2_GOVERNED_BASE_V1",
        first_session=valid_dates[0],
        last_session=valid_dates[-1],
        sessions=len(valid_dates),
        rows=len(frame),
        symbols=int(frame["symbol"].nunique()),
        exchange=exchanges,
        sector_rows=int(frame["sector"].notna().sum()),
        confidence=Decimal("1"),
        labels=("GOVERNED", "HTR-010B2", "PRODUCTION_INFLUENCE=false"),
    )


def _view_manifest(base: DatasetManifest, price_view: str) -> DatasetManifest:
    return DatasetManifest(
        dataset_version=f"HTR010B2_GOVERNED_{price_view}_V1",
        first_session=base.first_session,
        last_session=base.last_session,
        sessions=base.sessions,
        rows=base.rows,
        symbols=base.symbols,
        exchange=base.exchange,
        sector_rows=base.sector_rows,
        confidence=Decimal("1"),
        labels=(*base.labels, f"PRICE_VIEW={price_view}"),
    )


def _liquidity(frame: pd.DataFrame) -> pd.DataFrame:
    rows = frame.copy()
    rows["turnover"] = rows["close"].astype(float) * rows["volume"].astype(float)
    grouped = rows.groupby("symbol", sort=True)
    result = grouped.agg(
        average_daily_volume=("volume", "mean"),
        average_daily_turnover=("turnover", "mean"),
        sessions=("trade_date", "count"),
        first_session=("trade_date", "min"),
        last_session=("trade_date", "max"),
    )
    return result.reset_index()


def _store_contract(
    path: Path,
    *,
    price_view: str,
    identity_session_sha256: str,
    closure_sha256: str,
    admission_sha256: str,
    input_manifest_sha256: str,
) -> Path:
    payload: dict[str, Any] = {
        "contract_version": HTR010B2_CONTRACT_VERSION,
        "price_view": price_view,
        "identity_session_sha256": identity_session_sha256,
        "final_closure_report_sha256": closure_sha256,
        "admission_contract_sha256": admission_sha256,
        "governed_input_manifest_sha256": input_manifest_sha256,
        "active_replay_integration": False,
        "production_influence": False,
    }
    payload["report_sha256"] = _digest_mapping(payload)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


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
        "session_counts_match": raw["session_count"] == adjusted["session_count"],
        "eligible_security_counts_match": (
            raw["eligible_security_count"] == adjusted["eligible_security_count"]
        ),
        "eligible_observation_counts_match": (
            raw["eligible_security_observation_count"]
            == adjusted["eligible_security_observation_count"]
        ),
        "source_contracts_distinct": (
            raw["source_contract_sha256"] != adjusted["source_contract_sha256"]
        ),
    }
    unexplained = sum(
        not bool(value)
        for key, value in parity.items()
        if key != "identity_session_sha256"
    )
    deltas = {
        key: str(_number(adjusted.get(key)) - _number(raw.get(key)))
        for key in (
            "technical_candidate_count",
            "institutional_approval_count",
            "trade_count",
            "cagr_percent",
            "maximum_drawdown_percent",
            "expectancy_percent",
        )
    }
    population_nonempty = _benchmark_population_nonempty(raw, adjusted)
    readiness = _readiness_decision(
        unexplained=unexplained,
        population_nonempty=population_nonempty,
    )
    readiness_blockers: list[str] = []
    if unexplained:
        readiness_blockers.append("BENCHMARK_PARITY_DIVERGENCE")
    if not population_nonempty:
        readiness_blockers.append("EMPTY_BENCHMARK_POPULATION")
    comparison = {
        "comparison_state": "COMPARED",
        "parity": parity,
        "metric_deltas": deltas,
        "benchmark_population_nonempty": population_nonempty,
        "readiness_blockers": readiness_blockers,
        "unexplained_divergence_count": unexplained,
        "production_influence": False,
    }
    attestations = pair.canonical_attestation_sha256s
    report: dict[str, Any] = {
        "contract_version": HTR010B2_CONTRACT_VERSION,
        "final_closure_report_sha256": pair.final_closure_report_sha256,
        "admission_contract_sha256": pair.admission_contract_sha256,
        "governed_input_manifest_sha256": pair.governed_input_manifest_sha256,
        "identity_coverage": {
            "admitted_identity_count": pair.admitted_identity_count,
            "observed_identity_count": pair.observed_identity_count,
            "unobserved_admitted_identity_count": len(
                pair.unobserved_admitted_identity_ids
            ),
            "unobserved_admitted_identity_sha256": _digest_list(
                list(pair.unobserved_admitted_identity_ids)
            ),
            "unobserved_admitted_identity_sample": list(
                pair.unobserved_admitted_identity_ids[:20]
            ),
        },
        "canonical_attestation_count": len(attestations),
        "canonical_attestation_sha256s": list(attestations),
        "raw_artifact_count": raw_artifact_count,
        "adjusted_artifact_count": adjusted_artifact_count,
        "raw_summary": raw,
        "adjusted_summary": adjusted,
        "comparison": comparison,
        "readiness_decision": readiness,
        "governed_adjusted_benchmark_enabled": readiness == _B2_READY,
        "decision_metrics_evaluated": population_nonempty,
        "active_replay_integration": False,
        "production_influence": False,
    }
    report["report_sha256"] = _digest_mapping(report)
    return report


def _identity_coverage(
    *,
    admitted_ids: tuple[str, ...],
    observed_ids: set[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    admitted = tuple(sorted(set(admitted_ids)))
    admitted_set = set(admitted)

    unexpected = tuple(sorted(observed_ids.difference(admitted_set)))
    if unexpected:
        raise ValueError(
            "observed benchmark identities are outside B1H admission: "
            + ",".join(unexpected[:20])
        )

    if not observed_ids:
        raise ValueError("B2 observed identity population is empty")

    unobserved = tuple(sorted(admitted_set.difference(observed_ids)))
    return admitted, unobserved


def _benchmark_population_nonempty(
    raw: dict[str, Any],
    adjusted: dict[str, Any],
) -> bool:
    required = (
        "eligible_security_count",
        "eligible_security_observation_count",
    )
    return all(
        _number(summary.get(key)) > 0 for summary in (raw, adjusted) for key in required
    )


def _readiness_decision(*, unexplained: int, population_nonempty: bool) -> str:
    if unexplained:
        return _B2_BLOCKED_PARITY
    if not population_nonempty:
        return _B2_BLOCKED_EMPTY
    return _B2_READY


def _benchmark_summary(report: BenchmarkReplayReport) -> dict[str, Any]:
    stats = report.portfolio_statistics
    summary: dict[str, Any] = {
        "run_id": report.manifest.run_id,
        "source_contract_sha256": report.manifest.versions.warehouse_hash,
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
        "cagr_percent": str(stats.cagr_percent),
        "maximum_drawdown_percent": str(stats.maximum_drawdown_percent),
        "expectancy_percent": (
            None if stats.expectancy_percent is None else str(stats.expectancy_percent)
        ),
    }
    summary["report_sha256"] = _digest_mapping(summary)
    return summary


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


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_date(value: object) -> date | None:
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    return date.fromisoformat(text) if text else None


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
            f"- Raw eligible securities: `{raw['eligible_security_count']}`",
            (
                "- Raw eligible observations: "
                f"`{raw['eligible_security_observation_count']}`"
            ),
            f"- Adjusted eligible securities: `{adjusted['eligible_security_count']}`",
            (
                "- Adjusted eligible observations: "
                f"`{adjusted['eligible_security_observation_count']}`"
            ),
            (
                "- Benchmark population nonempty: "
                f"`{comparison['benchmark_population_nonempty']}`"
            ),
            f"- Decision metrics evaluated: `{report['decision_metrics_evaluated']}`",
            f"- Raw candidates: `{raw['technical_candidate_count']}`",
            f"- Adjusted candidates: `{adjusted['technical_candidate_count']}`",
            (
                "- Unexplained divergences: "
                f"`{comparison['unexplained_divergence_count']}`"
            ),
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
    "build_governed_benchmark_stores",
    "export_governed_adjusted_benchmark",
    "validate_governed_adjusted_handoff",
]
