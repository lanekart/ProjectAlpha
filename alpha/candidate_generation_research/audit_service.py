from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median

from alpha.candidate_generation_research.candidate_funnel import (
    CandidateGenerationFunnelEngine,
)
from alpha.candidate_generation_research.candidate_policy import (
    CandidatePolicyProposalEngine,
)
from alpha.candidate_generation_research.case_studies import (
    CandidateResearchCaseStudyEngine,
)
from alpha.candidate_generation_research.chronological_validation import (
    ChronologicalCandidateValidationEngine,
)
from alpha.candidate_generation_research.classification import (
    ZeroCandidateClassificationEngine,
)
from alpha.candidate_generation_research.event_onset import (
    TradableOpportunityOnsetEngine,
)
from alpha.candidate_generation_research.missed_candidate_attribution import (
    MissedCandidateAttributionEngine,
)
from alpha.candidate_generation_research.models import (
    CANONICAL_POLICY_ID,
    DATASET_VERSION,
    RESEARCH_POLICY_ID,
    RESEARCH_VERSION,
    CandidateResearchManifest,
    CandidateResearchReport,
    CandidateResearchSummary,
    PolicyProposalStatus,
    StageStatus,
)
from alpha.candidate_generation_research.opportunity_definition import (
    DEFAULT_OPPORTUNITY_DEFINITIONS,
    ForwardMoveEventEngine,
)
from alpha.candidate_generation_research.pine_parity import (
    PineCandidateParityEngine,
)
from alpha.candidate_generation_research.pine_trade_import import (
    PineLogicalTradeAuditEngine,
)
from alpha.candidate_generation_research.setup_recognition import (
    SetupRecognitionAuditEngine,
)
from alpha.candidate_generation_research.timing_windows import (
    CandidateTimingAuditEngine,
)
from alpha.candidate_generation_research.variant_generator import (
    CandidateVariantGenerator,
    default_candidate_variants,
)
from alpha.canonical_integrity_audit.models import OpportunityDefinition, PineTrade
from alpha.canonical_integrity_audit.parity_inputs import (
    DEFAULT_ACU_DIRECTORY,
    frozen_policy_manifest,
    load_acu_outcomes,
    load_canonical_events,
)
from alpha.canonical_integrity_audit.pine_trade_import import PineTradeImporter
from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.provenance import (
    APPROVAL_POLICY_VERSION,
    ENTRY_TIMING_ENGINE_VERSION,
    RECOMMENDATION_ENGINE_VERSION,
    TRADE_PLAN_ENGINE_VERSION,
)


class CandidateGenerationResearchEngine:
    """Run a research-only candidate recovery study with frozen policy inputs."""

    def run(
        self,
        *,
        store: LegacyMarketDataStore,
        acu_directory: Path | str = DEFAULT_ACU_DIRECTORY,
        pine_directory: Path | str | None = None,
        start: date | None = None,
        end: date | None = None,
        symbol: str | None = None,
        definitions: tuple[
            OpportunityDefinition, ...
        ] = DEFAULT_OPPORTUNITY_DEFINITIONS,
        generated_at: datetime | None = None,
    ) -> CandidateResearchReport:
        manifest = store.manifest()
        sessions = store.trade_dates(start=start, end=end)
        events = ForwardMoveEventEngine().construct(
            store=store,
            start=start,
            end=end,
            symbol=symbol,
            definitions=definitions,
        )
        onset_scan_start = None if start is None else start - timedelta(days=180)
        all_onsets = TradableOpportunityOnsetEngine().detect(
            store=store,
            start=onset_scan_start,
            end=end,
            symbol=symbol,
        )
        associated_onsets = TradableOpportunityOnsetEngine().associate(
            store=store,
            events=events,
            onsets=all_onsets,
        )
        candidates = load_canonical_events(acu_directory)
        if symbol is not None:
            normalized = symbol.strip().upper()
            candidates = tuple(item for item in candidates if item.symbol == normalized)
        outcomes = load_acu_outcomes(acu_directory)
        funnel = CandidateGenerationFunnelEngine().trace(
            events=events,
            onsets=associated_onsets,
            candidates=candidates,
            outcomes=outcomes,
        )
        setup_metrics = SetupRecognitionAuditEngine().measure(
            onsets=associated_onsets,
            funnel=funnel,
            candidates=candidates,
        )
        timing = CandidateTimingAuditEngine().measure(
            events=events,
            onsets=associated_onsets,
            candidates=candidates,
            sessions=sessions,
        )
        missed = MissedCandidateAttributionEngine().attribute(
            funnel=funnel,
            timing=timing,
        )
        definitions_used = default_candidate_variants()
        variant_rows = CandidateVariantGenerator().evaluate(
            store=store,
            all_onsets=all_onsets,
            associated_onsets=associated_onsets,
            sessions=sessions,
            variants=definitions_used,
        )
        variant_rows, validations = ChronologicalCandidateValidationEngine().validate(
            variant_rows
        )
        proposal = CandidatePolicyProposalEngine().build(
            definitions=definitions_used,
            results=variant_rows,
            validations=validations,
        )
        available_symbols = tuple(
            str(item) for item in store.liquidity_statistics()["symbol"]
        )
        zero_symbols = _zero_candidate_symbols(
            candidates,
            available_symbols,
            requested_symbol=symbol,
        )
        zero = ZeroCandidateClassificationEngine().classify(
            symbols=zero_symbols,
            sessions_examined=len(sessions),
            events=events,
            onsets=associated_onsets,
            funnel=funnel,
            candidates=candidates,
        )
        pine_trades: tuple[PineTrade, ...] = ()
        if pine_directory is not None:
            _, pine_trades = PineTradeImporter().import_directory(pine_directory)
        pine_logical = PineLogicalTradeAuditEngine().audit_directory(pine_directory)
        pine_parity = PineCandidateParityEngine().compare(
            pine_trades=pine_trades,
            onsets=associated_onsets,
            candidates=candidates,
        )
        studies = CandidateResearchCaseStudyEngine().build(
            events=events,
            onsets=associated_onsets,
            funnel=funnel,
            timing=timing,
            variants=variant_rows,
            available_symbols=available_symbols,
        )
        summary = _summary(
            events=events,
            associated_onsets=associated_onsets,
            funnel=funnel,
            timing=timing,
            missed=missed,
            variants=variant_rows,
            validations=validations,
            studies=studies,
            sessions=sessions,
        )
        research_manifest = _research_manifest()
        first = start or manifest.first_session
        last = end or manifest.last_session
        return CandidateResearchReport(
            audit_id=f"CGR-1|{CANONICAL_POLICY_ID}|{first}|{last}",
            generated_at=generated_at or datetime.now(tz=UTC),
            manifest=research_manifest,
            forward_move_events=events,
            onsets=associated_onsets,
            funnel=funnel,
            setup_metrics=setup_metrics,
            timing_metrics=timing,
            missed_attribution=missed,
            variant_results=variant_rows,
            validations=validations,
            zero_candidates=zero,
            pine_logical_trades=pine_logical,
            pine_candidate_parity=pine_parity,
            case_studies=studies,
            policy_proposal=proposal,
            summary=summary,
        )


def _research_manifest() -> CandidateResearchManifest:
    canonical = frozen_policy_manifest()
    return CandidateResearchManifest(
        policy_id=RESEARCH_POLICY_ID,
        parent_policy_id=CANONICAL_POLICY_ID,
        source_commit=canonical.source_commit,
        dataset_version=DATASET_VERSION,
        candidate_engine_version=RESEARCH_VERSION,
        setup_engine_version=RECOMMENDATION_ENGINE_VERSION,
        timing_engine_version=ENTRY_TIMING_ENGINE_VERSION,
        score_version=RECOMMENDATION_ENGINE_VERSION,
        approval_policy_version=APPROVAL_POLICY_VERSION,
        trade_plan_version=TRADE_PLAN_ENGINE_VERSION,
        outcome_version="forward-move-labels-v1+60-session-net-return-v1",
        research_thresholds={
            "candidate_cost": "0.20%",
            "candidate_explosion_penalty": "enabled",
            "development_share": "60%",
            "holdout_required": "true",
            "maximum_base_width": "25%",
            "maximum_extension": "10%",
            "minimum_average_turnover": "INR 5,000,000",
            "minimum_prospective_rr": "1.5",
            "validation_share": "20%",
            "holdout_share": "20%",
        },
    )


def _summary(
    *,
    events: tuple[object, ...],
    associated_onsets: tuple[object, ...],
    funnel: tuple[object, ...],
    timing: tuple[object, ...],
    missed: tuple[object, ...],
    variants: tuple[object, ...],
    validations: tuple[object, ...],
    studies: tuple[object, ...],
    sessions: tuple[date, ...],
) -> CandidateResearchSummary:
    event_by_id = {str(getattr(item, "event_id")): item for item in events}
    session_position = {session: index for index, session in enumerate(sessions)}
    event_ids = {
        getattr(item, "forward_event_id")
        for item in associated_onsets
        if getattr(item, "forward_event_id") is not None
    }
    setup_passes = sum(
        getattr(item, "canonical_setup_recognized") is StageStatus.PASS
        for item in funnel
        if getattr(item, "onset_id") is not None
    )
    candidate_passes = sum(
        getattr(item, "canonical_candidate_created") is StageStatus.PASS
        for item in funnel
        if getattr(item, "onset_id") is not None
    )
    denominator = len(event_ids)
    delays = [
        getattr(item, "delay_sessions")
        for item in timing
        if getattr(item, "delay_sessions") is not None
    ]
    onset_to_peak = [
        session_position[getattr(event_by_id[event_id], "peak_date")]
        - session_position[getattr(item, "onset_date")]
        for item in associated_onsets
        if (event_id := getattr(item, "forward_event_id")) in event_by_id
        and getattr(item, "onset_date") in session_position
        and getattr(event_by_id[event_id], "peak_date") in session_position
    ]
    prospective_rr = [getattr(item, "prospective_rr") for item in associated_onsets]
    pre_entry_mae = [
        getattr(event_by_id[event_id], "maximum_adverse_excursion_before_peak")
        for event_id in event_ids
        if event_id in event_by_id
    ]
    setup_blockers = Counter(
        getattr(item, "primary_blocker")
        for item in missed
        if "TIMING" not in getattr(item, "primary_blocker")
    )
    timing_blockers = Counter(getattr(item, "classification").value for item in timing)
    promoted = next(
        (
            getattr(item, "variant_id")
            for item in validations
            if getattr(item, "status") is PolicyProposalStatus.PROMOTE_TO_POLICY_REVIEW
        ),
        "NONE",
    )
    explosion = any(
        getattr(item, "explosion_penalty") > Decimal("0.25") for item in variants
    )
    study_by_symbol = {getattr(item, "requested_symbol"): item for item in studies}
    promotion_blockers = tuple(
        sorted(
            {
                getattr(item, "reason")
                for item in validations
                if getattr(item, "status")
                is not PolicyProposalStatus.PROMOTE_TO_POLICY_REVIEW
            }
        )
    )
    return CandidateResearchSummary(
        forward_move_events=len(events),
        tradable_onsets=len(associated_onsets),
        tradable_event_count=denominator,
        non_tradable_event_count=max(len(events) - denominator, 0),
        future_moves_actually_tradable_share=(
            None if not events else Decimal(denominator) / Decimal(len(events))
        ),
        canonical_setup_recall=(
            None if denominator == 0 else Decimal(setup_passes) / Decimal(denominator)
        ),
        canonical_candidate_recall=(
            None
            if denominator == 0
            else Decimal(candidate_passes) / Decimal(denominator)
        ),
        median_candidate_delay=(None if not delays else Decimal(str(median(delays)))),
        primary_setup_blocker=(
            setup_blockers.most_common(1)[0][0] if setup_blockers else "UNAVAILABLE"
        ),
        primary_timing_blocker=(
            timing_blockers.most_common(1)[0][0] if timing_blockers else "UNAVAILABLE"
        ),
        variants_tested=len({getattr(item, "variant_id") for item in variants}),
        best_validated_variant=promoted,
        candidate_explosion_risk="HIGH" if explosion else "BOUNDED",
        kalyan_classification=_case_classification(study_by_symbol.get("KALYANKJIL")),
        pc_jeweller_classification=_case_classification(
            study_by_symbol.get("PCJEWELLER")
        ),
        promotion_blockers=promotion_blockers,
        median_onset_to_peak_sessions=(
            None if not onset_to_peak else Decimal(str(median(onset_to_peak)))
        ),
        median_pre_entry_mae=(
            None if not pre_entry_mae else Decimal(str(median(pre_entry_mae)))
        ),
        median_prospective_rr=(
            None if not prospective_rr else Decimal(str(median(prospective_rr)))
        ),
    )


def _case_classification(value: object | None) -> str:
    return (
        "UNAVAILABLE"
        if value is None
        else str(getattr(value, "coverage_classification"))
    )


def _zero_candidate_symbols(
    candidates: tuple[object, ...],
    available_symbols: tuple[str, ...],
    *,
    requested_symbol: str | None = None,
) -> tuple[str, ...]:
    with_candidates = {str(getattr(item, "symbol")) for item in candidates}
    if requested_symbol is not None:
        normalized = requested_symbol.strip().upper()
        return () if normalized in with_candidates else (normalized,)
    return tuple(item for item in available_symbols if item not in with_candidates)


__all__ = ["CandidateGenerationResearchEngine"]
