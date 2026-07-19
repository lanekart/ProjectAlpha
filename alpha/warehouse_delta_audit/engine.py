"""Orchestration for the diagnostic-only Warehouse Delta Audit."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

from alpha.benchmark_replay import CanonicalBenchmarkReplayEngine, ReplayRequest
from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.warehouse_delta_audit.delta_engines import (
    IndicatorDeltaEngine,
    PriceDeltaEngine,
    ReplayDeltaEngine,
    unavailable_corporate_action_deltas,
)
from alpha.warehouse_delta_audit.models import (
    ConfidenceLevel,
    DecisionDeltaRecord,
    DecisionSeverity,
    PriceDeltaRecord,
    ReplayDeltaRecord,
    SourceLineage,
    ValueAttributionRecord,
    WarehouseDeltaReport,
    WarehouseDeltaRequest,
)
from alpha.warehouse_delta_audit.provenance import freeze_wda_manifest
from alpha.warehouse_delta_audit.purchase import purchase_decision
from alpha.warehouse_delta_audit.sampling import WarehouseSampleBuilder

ProgressCallback = Callable[[str, int, int, date | None], None]


class WarehouseDeltaAuditEngine:
    """Execute paired truth, indicator, decision, and frozen replay comparisons."""

    def __init__(
        self,
        *,
        sample_builder: WarehouseSampleBuilder | None = None,
        replay_engine: CanonicalBenchmarkReplayEngine | None = None,
    ) -> None:
        self.sample_builder = sample_builder or WarehouseSampleBuilder()
        self.replay_engine = replay_engine or CanonicalBenchmarkReplayEngine()

    def run(
        self,
        request: WarehouseDeltaRequest,
        *,
        project_root: Path,
        progress: ProgressCallback | None = None,
    ) -> WarehouseDeltaReport:
        _progress(progress, "PREPARE_SAMPLE", 0, 1, None)
        with self.sample_builder.prepare(request) as prepared:
            _progress(progress, "PREPARE_SAMPLE", 1, 1, prepared.profile.end)
            manifest = freeze_wda_manifest(
                project_root=project_root,
                legacy_database=Path(request.legacy_database),
                comparison_files=prepared.comparison_files,
                source_lineage=request.source_lineage,
                source_attestation=request.source_attestation,
                sample=prepared.profile,
            )
            prices = PriceDeltaEngine().compare(
                legacy_sample=prepared.legacy_sample,
                comparison_sample=prepared.comparison_sample,
                thresholds=request.thresholds,
            )
            _progress(progress, "PRICE_DELTA", 1, 1, prepared.profile.end)
            indicators = IndicatorDeltaEngine().compare(
                legacy_sample=prepared.legacy_sample,
                comparison_sample=prepared.comparison_sample,
                symbols=prepared.profile.selected_symbols,
                thresholds=request.thresholds,
            )
            _progress(progress, "INDICATOR_DELTA", 1, 1, prepared.profile.end)
            replay_request = ReplayRequest(
                start=prepared.profile.start,
                end=prepared.profile.end,
            )
            with LegacyMarketDataStore(prepared.legacy_replay_sample) as store:
                legacy_replay = self.replay_engine.run(
                    store=store,
                    request=replay_request,
                    project_root=project_root,
                    progress=_replay_progress(progress, "LEGACY_REPLAY"),
                )
            with LegacyMarketDataStore(prepared.comparison_replay_sample) as store:
                comparison_replay = self.replay_engine.run(
                    store=store,
                    request=replay_request,
                    project_root=project_root,
                    progress=_replay_progress(progress, "COMPARISON_REPLAY"),
                )
            replay_delta = ReplayDeltaEngine()
            candidates = replay_delta.candidate_deltas(
                legacy=legacy_replay,
                comparison=comparison_replay,
                thresholds=request.thresholds,
            )
            decisions = replay_delta.decision_deltas(
                legacy=legacy_replay,
                comparison=comparison_replay,
                thresholds=request.thresholds,
            )
            replay = replay_delta.replay_deltas(
                legacy=legacy_replay,
                comparison=comparison_replay,
            )
            corporate_actions = unavailable_corporate_action_deltas()
            recommendation, personal, confidence, status, improvement, reason = (
                purchase_decision(
                    source_lineage=request.source_lineage,
                    prices=prices,
                    decisions=decisions,
                    replay=replay,
                    corporate_actions_available=False,
                    spans_five_years=prepared.profile.spans_five_years,
                )
            )
            attribution = _value_attribution(
                prices=prices,
                decisions=decisions,
                replay=replay,
            )
            limitations = _limitations(
                source_lineage=request.source_lineage,
                mandatory_missing=prepared.profile.mandatory_symbols_missing,
            )
            return WarehouseDeltaReport(
                manifest=manifest,
                sample=prepared.profile,
                status=status,
                price_deltas=prices,
                indicator_deltas=indicators,
                candidate_deltas=candidates,
                decision_deltas=decisions,
                replay_deltas=replay,
                corporate_action_deltas=corporate_actions,
                value_attribution=attribution,
                purchase_recommendation=recommendation,
                personal_decision=personal,
                estimated_alpha_improvement=improvement,
                confidence=confidence,
                recommendation_reason=reason,
                limitations=limitations,
            )


def _value_attribution(
    *,
    prices: tuple[PriceDeltaRecord, ...],
    decisions: tuple[DecisionDeltaRecord, ...],
    replay: tuple[ReplayDeltaRecord, ...],
) -> tuple[ValueAttributionRecord, ...]:
    price_changes = sum(
        item.open_changed + item.high_changed + item.low_changed + item.close_changed
        for item in prices
    )
    volume_changes = sum(item.volume_changed for item in prices)
    decision_changes = sum(
        item.severity is not DecisionSeverity.NO_CHANGE for item in decisions
    )
    identity_changes = sum(
        item.missing_from_comparison + item.missing_from_legacy for item in prices
    )
    replay_effect = _replay_effect(replay)
    return (
        ValueAttributionRecord(
            source="corrected_prices",
            observable_changes=price_changes,
            decision_changes=0
            if price_changes == 0 and decision_changes == 0
            else None,
            replay_effect=replay_effect,
            confidence=(
                ConfidenceLevel.HIGH if price_changes == 0 else ConfidenceLevel.LOW
            ),
            explanation=(
                "Causal contribution is estimable only when isolated from volume, "
                "identity and corporate actions."
            ),
        ),
        ValueAttributionRecord(
            source="corrected_volume",
            observable_changes=volume_changes,
            decision_changes=0
            if volume_changes == 0 and decision_changes == 0
            else None,
            replay_effect=replay_effect,
            confidence=(
                ConfidenceLevel.HIGH if volume_changes == 0 else ConfidenceLevel.LOW
            ),
            explanation=(
                "Volume attribution remains confounded when price or identity also "
                "changes."
            ),
        ),
        ValueAttributionRecord(
            source="corporate_actions",
            observable_changes=None,
            decision_changes=None,
            replay_effect="UNKNOWN",
            confidence=ConfidenceLevel.INSUFFICIENT,
            explanation=(
                "No independent point-in-time corporate-action sample was supplied."
            ),
        ),
        ValueAttributionRecord(
            source="identity_resolution",
            observable_changes=identity_changes,
            decision_changes=0
            if identity_changes == 0 and decision_changes == 0
            else None,
            replay_effect=replay_effect,
            confidence=(
                ConfidenceLevel.MEDIUM if identity_changes == 0 else ConfidenceLevel.LOW
            ),
            explanation=(
                "Symbol/date absences are observable; issuer-lineage causality "
                "requires an identity master."
            ),
        ),
    )


def _replay_effect(rows: tuple[ReplayDeltaRecord, ...]) -> str:
    deltas = tuple(item.delta for item in rows if item.delta is not None)
    if not deltas:
        return "UNKNOWN"
    return "NO_CHANGE" if all(Decimal(value) == 0 for value in deltas) else "CHANGED"


def _limitations(
    *,
    source_lineage: SourceLineage,
    mandatory_missing: tuple[str, ...],
) -> tuple[str, ...]:
    rows = [
        "Historical sector membership is unavailable; sector coverage is UNKNOWN.",
        "Historical market-cap classifications are unavailable; liquidity strata "
        "are not market-cap labels.",
        "The stock population uses NSE EQ series plus INE ISIN evidence; a complete "
        "historical instrument taxonomy is unavailable.",
        "No independent corporate-action or adjusted-history sample was supplied.",
        "No BSE comparison sample was supplied.",
    ]
    if source_lineage is not SourceLineage.INDEPENDENT_OFFICIAL:
        rows.append(
            "The default NSE files are the legacy warehouse raw lineage, so this is "
            "an ingestion-integrity control rather than an independent vendor "
            "comparison."
        )
    if mandatory_missing:
        rows.append("Mandatory symbols missing: " + ", ".join(mandatory_missing) + ".")
    return tuple(rows)


def _replay_progress(
    callback: ProgressCallback | None,
    phase: str,
) -> Callable[[int, int, date], None] | None:
    if callback is None:
        return None

    def report(current: int, total: int, observed_on: date) -> None:
        callback(phase, current, total, observed_on)

    return report


def _progress(
    callback: ProgressCallback | None,
    phase: str,
    current: int,
    total: int,
    observed_on: date | None,
) -> None:
    if callback is not None:
        callback(phase, current, total, observed_on)


__all__ = ["ProgressCallback", "WarehouseDeltaAuditEngine"]
