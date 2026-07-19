"""Deterministic reconstruction of the pre-association research population."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from alpha.candidate_generation_research.event_onset import (
    TradableOpportunityOnsetEngine,
    merge_duplicate_onsets,
)
from alpha.candidate_generation_research.feature_snapshots import (
    PointInTimeFeatureEngine,
)
from alpha.candidate_generation_research.models import (
    CandidatePartition,
    TradableOpportunityOnset,
)
from alpha.candidate_generation_research.tradability import TradabilityEngine
from alpha.candidate_generation_research.variant_generator import partition_ranges
from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.feature_attribution_research.models import (
    CANDIDATE_RESEARCH_VERSION,
    CANONICAL_POLICY_ID,
    FEATURE_ENGINE_VERSION,
    OUTCOME_DEFINITION_VERSION,
    RESEARCH_VERSION,
    SETUP_DISCOVERY_VERSION,
    EvidencePartition,
    FeatureAttributionManifest,
    PartitionManifest,
    ResearchCohort,
    ResearchPopulationRecord,
    ResearchPopulationSummary,
    TransactionCostPolicy,
)

DEFAULT_CANDIDATE_DIRECTORY = Path(".alpha/candidate_research/ALPHA_CANONICAL_v1.0")
DEFAULT_SDE_DIRECTORY = Path(".alpha/setup_discovery/SDE_v1.0")
DEFAULT_ACU_DIRECTORY = Path(".alpha/acu/ALPHA_CANONICAL_v1.0")


@dataclass(frozen=True, slots=True)
class PopulationBuild:
    manifest: FeatureAttributionManifest
    records: tuple[ResearchPopulationRecord, ...]
    summary: ResearchPopulationSummary

    def cohort(self, cohort: ResearchCohort) -> tuple[ResearchPopulationRecord, ...]:
        return tuple(item for item in self.records if cohort in item.cohorts)


@dataclass(frozen=True, slots=True)
class _LinkedEvidence:
    event_ids: tuple[str, ...]
    funnel_rows: tuple[Mapping[str, str], ...]


@dataclass(frozen=True, slots=True)
class _CanonicalCandidate:
    candidate_id: str
    setup: str
    score: Decimal | None
    final_signal: str
    final_gate: str


class ResearchPopulationEngine:
    """Rebuild all causal onsets before any future-event association."""

    def build(
        self,
        *,
        store: LegacyMarketDataStore,
        candidate_directory: Path | str = DEFAULT_CANDIDATE_DIRECTORY,
        sde_directory: Path | str = DEFAULT_SDE_DIRECTORY,
        acu_directory: Path | str = DEFAULT_ACU_DIRECTORY,
        start: date | None = None,
        end: date | None = None,
        symbol: str | None = None,
        transaction_cost_policy: TransactionCostPolicy = TransactionCostPolicy(),
        generated_at: datetime | None = None,
    ) -> PopulationBuild:
        candidate_root = Path(candidate_directory)
        sde_root = Path(sde_directory)
        self._validate_sources(candidate_root, sde_root)
        sessions = store.trade_dates(start=start, end=end)
        if not sessions:
            raise ValueError("research population requires market sessions")
        partitions = _partition_manifest(store.trade_dates())
        scan_start = None if start is None else start - timedelta(days=450)
        reconstructed = _detect_reconstructed_onsets(
            store=store,
            start=scan_start,
            end=end,
            symbol=symbol,
        )
        if start is not None:
            reconstructed = tuple(
                item for item in reconstructed if item.onset_date >= start
            )
        linked_rows = _csv_rows(candidate_root / "tradable_opportunity_onsets.csv")
        funnel_rows = _csv_rows(candidate_root / "candidate_generation_funnel.csv")
        linked = _linked_evidence(linked_rows, funnel_rows)
        candidates = {
            item.candidate_id: item
            for item in _load_canonical_candidates(Path(acu_directory))
        }
        records = tuple(
            _population_record(
                onset=item,
                linked=linked.get(_onset_key_from_model(item)),
                candidates=candidates,
                partition=partitions.partition_for(item.onset_date),
            )
            for item in reconstructed
        )
        records = tuple(
            sorted(
                records, key=lambda item: (item.symbol, item.onset_date, item.onset_id)
            )
        )
        non_tradable = sum(
            row.get("coverage") == "NOT_ACTUALLY_TRADABLE" for row in funnel_rows
        )
        counts = Counter(cohort.value for item in records for cohort in item.cohorts)
        counts[ResearchCohort.NON_TRADABLE_HINDSIGHT_EVENTS.value] = non_tradable
        deduplicated_linked = len({_onset_key_from_csv(row) for row in linked_rows})
        summary = ResearchPopulationSummary(
            raw_linked_onsets=len(linked_rows),
            deduplicated_linked_onsets=deduplicated_linked,
            reconstructed_market_opportunities=len(records),
            labelled_market_opportunities=0,
            cohort_counts=tuple(sorted(counts.items())),
            selection_bias_warning=(
                "The linked-hindsight cohort is conditioned on a later major-move "
                "event. Primary attribution uses the pre-association reconstructed "
                "market-opportunity population."
            ),
        )
        source_hashes = tuple(
            sorted(
                (str(path), _file_hash(path))
                for path in (
                    candidate_root / "candidate_research_manifest.json",
                    candidate_root / "tradable_opportunity_onsets.csv",
                    candidate_root / "candidate_generation_funnel.csv",
                    sde_root / "setup_discovery_manifest.json",
                )
            )
        )
        manifest = FeatureAttributionManifest(
            research_id=(
                f"{RESEARCH_VERSION}|{sessions[0].isoformat()}|"
                f"{sessions[-1].isoformat()}|{transaction_cost_policy.policy_id}|"
                f"{transaction_cost_policy.round_trip_rate}"
            ),
            generated_at=generated_at
            or datetime.combine(sessions[-1], time.min, tzinfo=UTC),
            source_commit=_source_commit(candidate_root),
            dataset_version=_dataset_version(store),
            canonical_policy_id=CANONICAL_POLICY_ID,
            candidate_research_version=CANDIDATE_RESEARCH_VERSION,
            setup_discovery_version=SETUP_DISCOVERY_VERSION,
            feature_engine_version=FEATURE_ENGINE_VERSION,
            outcome_definition_version=OUTCOME_DEFINITION_VERSION,
            transaction_cost_policy=transaction_cost_policy,
            partition_manifest=partitions,
            source_artifact_hashes=source_hashes,
        )
        return PopulationBuild(manifest=manifest, records=records, summary=summary)

    @staticmethod
    def _validate_sources(candidate_root: Path, sde_root: Path) -> None:
        required = (
            candidate_root / "candidate_research_manifest.json",
            candidate_root / "tradable_opportunity_onsets.csv",
            candidate_root / "candidate_generation_funnel.csv",
            sde_root / "setup_discovery_manifest.json",
        )
        missing = tuple(path for path in required if not path.exists())
        if missing:
            raise FileNotFoundError(
                "feature attribution source artifacts are missing: "
                + ", ".join(str(path) for path in missing)
            )
        candidate_manifest = json.loads(required[0].read_text(encoding="utf-8"))
        sde_manifest = json.loads(required[3].read_text(encoding="utf-8"))
        if candidate_manifest.get("parent_policy_id") != CANONICAL_POLICY_ID:
            raise ValueError("candidate research canonical policy is not frozen v1.0")
        if sde_manifest.get("parent_policy_id") != CANONICAL_POLICY_ID:
            raise ValueError("SDE canonical policy is not frozen v1.0")
        if bool(candidate_manifest.get("production_influence")):
            raise ValueError("candidate research unexpectedly influences production")
        if bool(sde_manifest.get("production_influence")):
            raise ValueError("SDE unexpectedly influences production")


def deduplicate_linked_onsets(
    rows: Iterable[Mapping[str, str]],
) -> tuple[Mapping[str, str], ...]:
    """Keep one deterministic representative for repeated event associations."""

    selected: dict[tuple[str, str, str, str], Mapping[str, str]] = {}
    for row in sorted(rows, key=lambda item: item.get("onset_id", "")):
        selected.setdefault(_onset_key_from_csv(row), row)
    return tuple(selected[key] for key in sorted(selected))


def _detect_reconstructed_onsets(
    *,
    store: LegacyMarketDataStore,
    start: date | None,
    end: date | None,
    symbol: str | None,
    batch_size: int = 150,
) -> tuple[TradableOpportunityOnset, ...]:
    if start is None:
        return TradableOpportunityOnsetEngine().detect(
            store=store, start=None, end=end, symbol=symbol
        )
    history_start = start - timedelta(days=450)
    symbols = (
        (symbol.strip().upper(),)
        if symbol
        else tuple(
            str(row[0])
            for row in store.connection.execute(
                "SELECT DISTINCT UPPER(symbol) FROM daily_prices ORDER BY 1"
            ).fetchall()
        )
    )
    feature_engine = PointInTimeFeatureEngine()
    tradability_engine = TradabilityEngine()
    rows: list[TradableOpportunityOnset] = []
    for batch in _batches(symbols, batch_size):
        placeholders = ", ".join("?" for _ in batch)
        end_filter = "" if end is None else "AND trade_date <= ?"
        parameters: tuple[object, ...] = (
            (*batch, history_start) if end is None else (*batch, history_start, end)
        )
        frame = store.connection.execute(
            f"""
            SELECT UPPER(symbol) AS symbol, trade_date, open, high, low, close, volume
            FROM daily_prices
            WHERE UPPER(symbol) IN ({placeholders})
              AND trade_date >= ?
              {end_filter}
              AND open > 0 AND high > 0 AND low > 0 AND close > 0 AND volume >= 0
              AND high >= GREATEST(open, low, close)
              AND low <= LEAST(open, high, close)
            ORDER BY symbol, trade_date
            """,
            parameters,
        ).fetchdf()
        snapshots = feature_engine.build(frame, near_setup_only=True)
        rows.extend(
            onset
            for snapshot in snapshots
            if snapshot.observed_on >= start
            and (onset := tradability_engine.assess(snapshot)) is not None
        )
    return merge_duplicate_onsets(tuple(rows))


def _population_record(
    *,
    onset: TradableOpportunityOnset,
    linked: _LinkedEvidence | None,
    candidates: Mapping[str, object],
    partition: EvidencePartition,
) -> ResearchPopulationRecord:
    funnel_rows = () if linked is None else linked.funnel_rows
    candidate_ids = tuple(
        sorted(
            {
                row["canonical_candidate_id"]
                for row in funnel_rows
                if row.get("canonical_candidate_id")
            }
        )
    )
    candidate = next(
        (candidates[item] for item in candidate_ids if item in candidates), None
    )
    coverage = tuple(sorted({row.get("coverage", "UNKNOWN") for row in funnel_rows}))
    cohorts = [
        ResearchCohort.ALL_MARKET_OPPORTUNITIES,
        ResearchCohort.ALL_TRADABLE_ONSETS,
    ]
    if linked is not None:
        cohorts.append(ResearchCohort.LINKED_HINDSIGHT)
    if candidate_ids:
        cohorts.append(ResearchCohort.CANONICAL_CANDIDATES)
    if any("MISSED" in item or "FAILED" in item for item in coverage):
        cohorts.append(ResearchCohort.CANONICAL_MISSES)
    if "CANONICAL_CANDIDATE_REJECTED" in coverage:
        cohorts.append(ResearchCohort.CANONICAL_REJECTIONS)
    if any(
        item in {"CAPTURED_BY_CANONICAL", "PARTIALLY_CAPTURED_BY_CANONICAL"}
        for item in coverage
    ):
        cohorts.append(ResearchCohort.CAPTURED_OR_PARTIALLY_CAPTURED)
    values = tuple(sorted(onset.point_in_time_inputs.items()))
    return ResearchPopulationRecord(
        onset_id=onset.onset_id,
        source_onset_id=onset.onset_id,
        event_ids=() if linked is None else linked.event_ids,
        symbol=onset.symbol,
        onset_date=onset.onset_date,
        onset_sequence=onset.onset_sequence,
        event_family=onset.event_family.value,
        candidate_status="NO_HINDSIGHT_EVENT_LINK"
        if not coverage
        else "|".join(coverage),
        canonical_setup=_optional_attr(candidate, "setup"),
        canonical_score=_optional_decimal_attr(candidate, "score"),
        canonical_verdict=_optional_attr(candidate, "final_signal"),
        canonical_gate_result=_optional_attr(candidate, "final_gate"),
        entry_trigger=onset.entry_trigger,
        reference_level=onset.reference_level,
        prospective_stop=onset.prospective_stop,
        prospective_target=onset.prospective_target,
        prospective_rr=onset.prospective_rr,
        confidence=onset.confidence,
        point_in_time_inputs=values,
        cohorts=tuple(dict.fromkeys(cohorts)),
        partition=partition,
        dataset_version=onset.dataset_version,
        feature_snapshot_hash=_snapshot_hash(onset, values),
    )


def _linked_evidence(
    linked_rows: tuple[dict[str, str], ...],
    funnel_rows: tuple[dict[str, str], ...],
) -> dict[tuple[str, str, str, str], _LinkedEvidence]:
    funnel_by_event: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in funnel_rows:
        funnel_by_event[row.get("event_id", "")].append(row)
    events_by_key: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)
    for row in linked_rows:
        events_by_key[_onset_key_from_csv(row)].add(row.get("forward_event_id", ""))
    return {
        key: _LinkedEvidence(
            event_ids=tuple(sorted(item for item in event_ids if item)),
            funnel_rows=tuple(
                row
                for event_id in sorted(event_ids)
                for row in funnel_by_event.get(event_id, ())
            ),
        )
        for key, event_ids in events_by_key.items()
    }


def _onset_key_from_model(
    onset: TradableOpportunityOnset,
) -> tuple[str, str, str, str]:
    values = onset.point_in_time_inputs
    return (
        onset.symbol.upper(),
        onset.onset_date.isoformat(),
        onset.event_family.value,
        values.get("feature_hash", ""),
    )


def _onset_key_from_csv(row: Mapping[str, str]) -> tuple[str, str, str, str]:
    values = json.loads(row.get("point_in_time_inputs", "{}"))
    return (
        row.get("symbol", "").upper(),
        row.get("onset_date", ""),
        row.get("event_family", ""),
        str(values.get("feature_hash", "")),
    )


def _partition_manifest(sessions: tuple[date, ...]) -> PartitionManifest:
    ranges = partition_ranges(sessions)
    development = ranges[CandidatePartition.DEVELOPMENT]
    validation = ranges[CandidatePartition.VALIDATION]
    holdout = ranges[CandidatePartition.HOLDOUT]
    return PartitionManifest(
        development_start=development[0],
        development_end=development[1],
        validation_start=validation[0],
        validation_end=validation[1],
        holdout_start=holdout[0],
        holdout_end=holdout[1],
    )


def _snapshot_hash(
    onset: TradableOpportunityOnset, values: tuple[tuple[str, str], ...]
) -> str:
    payload = json.dumps(
        {
            "symbol": onset.symbol,
            "onset_date": onset.onset_date.isoformat(),
            "family": onset.event_family.value,
            "entry": str(onset.entry_trigger),
            "stop": str(onset.prospective_stop),
            "target": str(onset.prospective_target),
            "inputs": dict(values),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _dataset_version(store: LegacyMarketDataStore) -> str:
    value = store.manifest()
    return (
        f"{value.dataset_version}|{value.first_session}|{value.last_session}|"
        f"rows={value.rows}"
    )


def _source_commit(candidate_root: Path) -> str:
    manifest = json.loads(
        (candidate_root / "candidate_research_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    frozen = str(manifest.get("source_commit", "")).strip()
    if frozen:
        return frozen
    try:
        result = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"
    return result.stdout.strip() or "UNKNOWN"


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _csv_rows(path: Path) -> tuple[dict[str, str], ...]:
    with path.open(encoding="utf-8", newline="") as handle:
        return tuple(dict(row) for row in csv.DictReader(handle))


def _batches(values: tuple[str, ...], size: int) -> Iterable[tuple[str, ...]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _load_canonical_candidates(root: Path) -> tuple[_CanonicalCandidate, ...]:
    rankings_path = root / "candidate_rankings.csv"
    if not rankings_path.exists():
        return ()
    gates_path = root / "gate_attribution.csv"
    gates = _csv_rows(gates_path) if gates_path.exists() else ()
    primary_gate = {
        (row.get("observed_on", ""), row.get("symbol", "").upper()): row.get(
            "gate_code", "PASSED"
        )
        for row in gates
        if row.get("primary", "").lower() == "true"
    }
    rows = []
    for item in _csv_rows(rankings_path):
        observed_on = item.get("observed_on", "")
        symbol = item.get("symbol", "").upper()
        if not observed_on or not symbol:
            continue
        rows.append(
            _CanonicalCandidate(
                candidate_id=f"{observed_on}|{symbol}",
                setup=item.get("setup_type", "UNKNOWN") or "UNKNOWN",
                score=_optional_decimal(item.get("score")),
                final_signal=item.get("final_signal", "UNKNOWN") or "UNKNOWN",
                final_gate=primary_gate.get((observed_on, symbol), "PASSED"),
            )
        )
    return tuple(sorted(rows, key=lambda item: item.candidate_id))


def _optional_decimal(value: str | None) -> Decimal | None:
    if value in {None, "", "None", "UNAVAILABLE"}:
        return None
    try:
        return Decimal(str(value))
    except ArithmeticError:
        return None


def _optional_attr(value: object | None, name: str) -> str | None:
    if value is None:
        return None
    item = getattr(value, name, None)
    return None if item is None else str(item)


def _optional_decimal_attr(value: object | None, name: str) -> Decimal | None:
    if value is None:
        return None
    item = getattr(value, name, None)
    return item if isinstance(item, Decimal) else None


__all__ = [
    "DEFAULT_CANDIDATE_DIRECTORY",
    "DEFAULT_ACU_DIRECTORY",
    "DEFAULT_SDE_DIRECTORY",
    "PopulationBuild",
    "ResearchPopulationEngine",
    "deduplicate_linked_onsets",
]
