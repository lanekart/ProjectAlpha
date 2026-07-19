from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from alpha.historical_replay.breakout_source_gap import (
    BreakoutGapAttributionRecord,
    BreakoutSourceGapAuditReport,
)
from alpha.historical_replay.historical_source_evaluation import (
    HistoricalSourceEvaluationManifest,
    HistoricalSourceEvaluationManifestRecord,
)
from alpha.historical_replay.upstox_historical_probe import (
    PRODUCTION_INFLUENCE,
    UpstoxCoverageClassification,
    UpstoxHistoricalCandidateEvidence,
    UpstoxHistoricalEvidenceDataset,
    UpstoxIdentityMatchMethod,
    UpstoxIdentityStatus,
    UpstoxProbeConclusion,
    UpstoxRecommendedSourceRole,
)

UPSTOX_FULL_POPULATION_UTILITY_VERSION = "upstox-full-population-utility-v1"
_FOUR = Decimal("0.0001")


class UpstoxSelectionBiasImpact(StrEnum):
    MATERIALLY_REDUCES_OBSERVED_SELECTION_BIAS = (
        "MATERIALLY_REDUCES_OBSERVED_SELECTION_BIAS"
    )
    MODESTLY_REDUCES_OBSERVED_SELECTION_BIAS = (
        "MODESTLY_REDUCES_OBSERVED_SELECTION_BIAS"
    )
    LEAVES_OBSERVED_SELECTION_BIAS_LARGELY_UNCHANGED = (
        "LEAVES_OBSERVED_SELECTION_BIAS_LARGELY_UNCHANGED"
    )
    WORSENS_OBSERVED_CONCENTRATION = "WORSENS_OBSERVED_CONCENTRATION"
    INSUFFICIENT_FULL_POPULATION_EVIDENCE = "INSUFFICIENT_FULL_POPULATION_EVIDENCE"


@dataclass(frozen=True, slots=True)
class UpstoxCoverageSlice:
    dimension: str
    key: str
    candidates: int
    full_price_coverage: int
    coverage_rate: Decimal | None


@dataclass(frozen=True, slots=True)
class UpstoxScenarioDistribution:
    dimension: str
    key: str
    current_authoritative: int
    authoritative_plus_provisional_price: int
    remaining_unavailable: int


@dataclass(frozen=True, slots=True)
class UpstoxFullPopulationUtilityReport:
    report_version: str
    manifest_candidates: int
    source_required_candidates: int
    recovery_uncertain_candidates: int
    observed_candidates: int
    completed_candidates: int
    not_tested_candidates: int
    terminal_coverage_distribution: tuple[tuple[str, int], ...]
    terminal_statuses_reconcile: bool
    full_price_coverage_candidates: int
    full_price_coverage_rate: Decimal | None
    coverage_slices: tuple[UpstoxCoverageSlice, ...]
    full_price_unique_symbols: int
    full_price_symbol_hhi: Decimal | None
    provisional_identities: int
    authoritative_identities: int
    unresolved_identities: int
    matches_by_isin: int
    matches_by_historical_symbol: int
    matches_by_current_symbol_with_continuity: int
    current_symbol_only_matches_rejected: int
    inactive_instruments_resolved: int
    renamed_instruments_resolved: int
    ambiguous_matches: int
    duplicate_instrument_matches: int
    invalid_series_count: int
    invalid_series_causes: tuple[tuple[str, int], ...]
    currently_ready_reconstruction_records: int
    currently_unreconstructable_records: int
    upstox_full_price_covered_missing_candidates: int
    candidates_still_blocked_by_identity: int
    candidates_still_blocked_by_corporate_actions: int
    candidates_blocked_by_both: int
    candidates_blocked_only_by_price: int
    maximum_theoretical_readiness: int
    simulated_readiness_after_mandatory_blockers: int
    actual_authoritative_readiness: int
    scenario_distributions: tuple[UpstoxScenarioDistribution, ...]
    baseline_bias_distance: Decimal | None
    provisional_bias_distance: Decimal | None
    selection_bias_impact: UpstoxSelectionBiasImpact
    recommended_source_role: UpstoxRecommendedSourceRole
    exact_conclusion: UpstoxProbeConclusion
    price_availability_conclusion: str
    identity_authority_conclusion: str
    corporate_action_authority_conclusion: str
    production_suitability_conclusion: str
    total_network_requests: int
    successful_requests: int
    authentication_failures: int
    rate_limit_responses: int
    transient_failures: int
    permanent_failures: int
    retries: int
    elapsed_seconds: Decimal
    request_rate_per_second: Decimal | None
    early_stop_status: str
    token_exposure_incidents: int
    account_endpoint_calls: int
    order_endpoint_calls: int
    production_influence: bool = PRODUCTION_INFLUENCE


class UpstoxFullPopulationUtilityEngine:
    def build(
        self,
        *,
        manifest: HistoricalSourceEvaluationManifest,
        dataset: UpstoxHistoricalEvidenceDataset | None,
        breakout_audit: BreakoutSourceGapAuditReport,
    ) -> UpstoxFullPopulationUtilityReport:
        records = dataset.records if dataset is not None else ()
        record_index = {item.candidate_id: item for item in records}
        manifest_index = {item.candidate_id: item for item in manifest.records}
        observed = tuple(
            item for item in records if item.candidate_id in manifest_index
        )
        full = tuple(item for item in observed if item.full_price_coverage)
        full_ids = {item.candidate_id for item in full}
        terminal = Counter(_terminal_status(item) for item in observed)
        not_tested = max(0, len(manifest.records) - len(record_index))
        if not_tested:
            terminal[UpstoxCoverageClassification.NOT_TESTED.value] += not_tested
        terminal_distribution = tuple(sorted(terminal.items()))
        contexts = {item.candidate_id: item for item in breakout_audit.coverage.records}
        slices = _coverage_slices(
            manifest.records,
            full_ids=full_ids,
            contexts=contexts,
        )
        full_symbol_counts = Counter(
            manifest_index[item.candidate_id].historical_symbol for item in full
        )
        full_symbol_hhi = _hhi(full_symbol_counts)
        invalid = tuple(
            item
            for item in observed
            if item.coverage_classification
            is UpstoxCoverageClassification.INVALID_SERIES
        )
        invalid_causes = Counter(
            item.primary_series_defect.value
            if item.primary_series_defect is not None
            else "UNKNOWN_SERIES_DEFECT"
            for item in invalid
        )
        blockers = _marginal_value(manifest_index, full)
        scenario = _selection_bias_scenarios(
            breakout_audit.coverage.records,
            full_ids=full_ids,
        )
        completed = len(observed)
        population_complete = completed == len(manifest.records)
        impact = (
            classify_selection_bias_impact(
                scenario.baseline_distance,
                scenario.provisional_distance,
                full_symbol_hhi,
            )
            if population_complete
            else UpstoxSelectionBiasImpact.INSUFFICIENT_FULL_POPULATION_EVIDENCE
        )
        full_rate = _ratio(len(full), len(manifest.records))
        conclusion, role = _source_role(
            population_complete=population_complete,
            full_rate=full_rate,
            slices=slices,
            impact=impact,
            observed=observed,
            dataset=dataset,
        )
        metrics = dataset.operational_metrics if dataset is not None else None
        return UpstoxFullPopulationUtilityReport(
            report_version=UPSTOX_FULL_POPULATION_UTILITY_VERSION,
            manifest_candidates=len(manifest.records),
            source_required_candidates=manifest.source_required_count,
            recovery_uncertain_candidates=manifest.recovery_uncertain_count,
            observed_candidates=len(observed),
            completed_candidates=completed,
            not_tested_candidates=not_tested,
            terminal_coverage_distribution=terminal_distribution,
            terminal_statuses_reconcile=sum(terminal.values()) == len(manifest.records),
            full_price_coverage_candidates=len(full),
            full_price_coverage_rate=full_rate,
            coverage_slices=slices,
            full_price_unique_symbols=len(full_symbol_counts),
            full_price_symbol_hhi=full_symbol_hhi,
            provisional_identities=sum(
                item.identity_status
                is UpstoxIdentityStatus.RESOLVED_PROVISIONAL_FOR_PRICE_PROBE
                for item in observed
            ),
            authoritative_identities=sum(item.identity_confirmed for item in observed),
            unresolved_identities=sum(item.instrument_key is None for item in observed),
            matches_by_isin=sum(
                item.identity_match_method is UpstoxIdentityMatchMethod.ISIN
                for item in observed
            ),
            matches_by_historical_symbol=sum(
                item.instrument_key is not None
                and item.matched_symbol == item.requested_historical_symbol
                for item in observed
            ),
            matches_by_current_symbol_with_continuity=sum(
                item.instrument_key is not None
                and item.matched_symbol != item.requested_historical_symbol
                and item.identity_confirmed
                for item in observed
            ),
            current_symbol_only_matches_rejected=sum(
                item.identity_status
                is UpstoxIdentityStatus.CURRENT_SYMBOL_ONLY_REJECTED
                for item in observed
            ),
            inactive_instruments_resolved=sum(
                item.inactive_security and item.instrument_key is not None
                for item in observed
            ),
            renamed_instruments_resolved=sum(
                item.renamed_security and item.instrument_key is not None
                for item in observed
            ),
            ambiguous_matches=sum(
                item.identity_status is UpstoxIdentityStatus.AMBIGUOUS
                for item in observed
            ),
            duplicate_instrument_matches=sum(
                item.identity_status is UpstoxIdentityStatus.AMBIGUOUS
                and "multiple" in (item.identity_ambiguity_reason or "").lower()
                for item in observed
            ),
            invalid_series_count=len(invalid),
            invalid_series_causes=tuple(sorted(invalid_causes.items())),
            currently_ready_reconstruction_records=breakout_audit.ready_records,
            currently_unreconstructable_records=(
                breakout_audit.unreconstructable_records
            ),
            upstox_full_price_covered_missing_candidates=len(full),
            candidates_still_blocked_by_identity=blockers.identity,
            candidates_still_blocked_by_corporate_actions=blockers.corporate_action,
            candidates_blocked_by_both=blockers.both,
            candidates_blocked_only_by_price=blockers.price_only,
            maximum_theoretical_readiness=breakout_audit.ready_records + len(full),
            simulated_readiness_after_mandatory_blockers=(
                breakout_audit.ready_records + blockers.price_only
            ),
            actual_authoritative_readiness=breakout_audit.ready_records,
            scenario_distributions=scenario.rows,
            baseline_bias_distance=scenario.baseline_distance,
            provisional_bias_distance=scenario.provisional_distance,
            selection_bias_impact=impact,
            recommended_source_role=role,
            exact_conclusion=conclusion,
            price_availability_conclusion=(
                f"{len(full)}/{len(manifest.records)} candidates have full "
                "price-only coverage; this does not establish identity or "
                "adjustment authority."
            ),
            identity_authority_conclusion=(
                "Candle availability never upgrades provisional identity; "
                "authoritative identities="
                f"{sum(item.identity_confirmed for item in observed)}."
            ),
            corporate_action_authority_conclusion=(
                "Upstox adjustment semantics remain undocumented; authoritative "
                "effective-dated corporate-action evidence is still required."
            ),
            production_suitability_conclusion=(
                "Upstox remains outside the production provider registry; this "
                "audit has no production or trading influence."
            ),
            total_network_requests=metrics.total_network_requests if metrics else 0,
            successful_requests=metrics.successful_requests if metrics else 0,
            authentication_failures=metrics.authentication_failures if metrics else 0,
            rate_limit_responses=metrics.rate_limit_responses if metrics else 0,
            transient_failures=metrics.transient_failures if metrics else 0,
            permanent_failures=metrics.permanent_failures if metrics else 0,
            retries=metrics.retries if metrics else 0,
            elapsed_seconds=metrics.elapsed_seconds if metrics else Decimal("0"),
            request_rate_per_second=(
                metrics.request_rate_per_second if metrics else None
            ),
            early_stop_status=(
                "NOT_COMPLETE" if not population_complete else "COMPLETED"
            ),
            token_exposure_incidents=metrics.token_exposure_incidents if metrics else 0,
            account_endpoint_calls=metrics.account_endpoint_calls if metrics else 0,
            order_endpoint_calls=metrics.order_endpoint_calls if metrics else 0,
        )


@dataclass(frozen=True, slots=True)
class _BlockerCounts:
    identity: int
    corporate_action: int
    both: int
    price_only: int


@dataclass(frozen=True, slots=True)
class _SelectionScenario:
    rows: tuple[UpstoxScenarioDistribution, ...]
    baseline_distance: Decimal | None
    provisional_distance: Decimal | None


def classify_selection_bias_impact(
    baseline_distance: Decimal | None,
    provisional_distance: Decimal | None,
    symbol_hhi: Decimal | None,
) -> UpstoxSelectionBiasImpact:
    if baseline_distance is None or provisional_distance is None:
        return UpstoxSelectionBiasImpact.INSUFFICIENT_FULL_POPULATION_EVIDENCE
    improvement = baseline_distance - provisional_distance
    if improvement < Decimal("-0.01") or (
        symbol_hhi is not None and symbol_hhi > Decimal("0.20")
    ):
        return UpstoxSelectionBiasImpact.WORSENS_OBSERVED_CONCENTRATION
    if improvement >= Decimal("0.05"):
        return UpstoxSelectionBiasImpact.MATERIALLY_REDUCES_OBSERVED_SELECTION_BIAS
    if improvement >= Decimal("0.01"):
        return UpstoxSelectionBiasImpact.MODESTLY_REDUCES_OBSERVED_SELECTION_BIAS
    return UpstoxSelectionBiasImpact.LEAVES_OBSERVED_SELECTION_BIAS_LARGELY_UNCHANGED


def render_upstox_full_population_utility(
    report: UpstoxFullPopulationUtilityReport,
) -> tuple[str, ...]:
    return (
        "Upstox Full-Population Price Coverage and Utility Audit",
        f"Manifest Candidates: {report.manifest_candidates}",
        "Source-Required / Recovery-Uncertain: "
        f"{report.source_required_candidates} / {report.recovery_uncertain_candidates}",
        f"Observed / Completed / Not Tested: {report.observed_candidates} / "
        f"{report.completed_candidates} / {report.not_tested_candidates}",
        "Terminal Coverage Distribution: "
        + _pairs(report.terminal_coverage_distribution),
        "Terminal Status Reconciliation: "
        + ("RECONCILED" if report.terminal_statuses_reconcile else "MISMATCH"),
        "Full Price Coverage: "
        f"{report.full_price_coverage_candidates}/{report.manifest_candidates} "
        f"({_percent(report.full_price_coverage_rate)})",
        "2016 Full Price Coverage: " + _slice_text(report, "year_group", "2016"),
        "2017-2020 Full Price Coverage: "
        + _slice_text(report, "year_group", "2017-2020"),
        "2021-2026 Full Price Coverage: "
        + _slice_text(report, "year_group", "2021-2026"),
        "Symbol-Level Coverage: " + _dimension_text(report, "historical_symbol"),
        "Replay-Year Coverage: " + _dimension_text(report, "replay_year"),
        "Candidate-Year Coverage: " + _dimension_text(report, "candidate_year"),
        "Gap-Cause Coverage: " + _dimension_text(report, "gap_cause"),
        "Recovery-Population Coverage: "
        + _dimension_text(report, "recovery_population"),
        "Setup Coverage: " + _dimension_text(report, "setup_type"),
        "Entry-Timing Coverage: " + _dimension_text(report, "entry_timing"),
        "Market-Regime Coverage: " + _dimension_text(report, "market_regime"),
        "Breadth-State Coverage: " + _dimension_text(report, "breadth_state"),
        "Continuity Coverage: " + _dimension_text(report, "continuity_status"),
        "Active/Inactive Coverage: " + _dimension_text(report, "active_status"),
        "Corporate-Action Case Coverage: "
        + _dimension_text(report, "corporate_action_ambiguity"),
        "Repeated-Symbol Concentration: "
        f"{report.full_price_unique_symbols} full-covered symbols; "
        f"HHI={_decimal(report.full_price_symbol_hhi)}",
        "Identity Coverage:",
        f"- Provisional / Authoritative / Unresolved: "
        f"{report.provisional_identities} / {report.authoritative_identities} / "
        f"{report.unresolved_identities}",
        f"- ISIN / Historical Symbol / Current+Continuity: "
        f"{report.matches_by_isin} / {report.matches_by_historical_symbol} / "
        f"{report.matches_by_current_symbol_with_continuity}",
        "- Current-Symbol-Only Rejected: "
        f"{report.current_symbol_only_matches_rejected}",
        f"- Inactive / Renamed Resolved: {report.inactive_instruments_resolved} / "
        f"{report.renamed_instruments_resolved}",
        f"- Ambiguous / Duplicate Matches: {report.ambiguous_matches} / "
        f"{report.duplicate_instrument_matches}",
        f"Invalid Series: {report.invalid_series_count}; causes="
        + _pairs(report.invalid_series_causes),
        "Marginal Reconstruction Value (simulation only):",
        f"- Current Ready / Unreconstructable: "
        f"{report.currently_ready_reconstruction_records} / "
        f"{report.currently_unreconstructable_records}",
        f"- Upstox Full-Price-Covered Missing Candidates: "
        f"{report.upstox_full_price_covered_missing_candidates}",
        f"- Still Blocked by Identity / Corporate Action / Both: "
        f"{report.candidates_still_blocked_by_identity} / "
        f"{report.candidates_still_blocked_by_corporate_actions} / "
        f"{report.candidates_blocked_by_both}",
        f"- Blocked Only by Price: {report.candidates_blocked_only_by_price}",
        f"- Maximum Theoretical Readiness: {report.maximum_theoretical_readiness}",
        "- Simulated Readiness after Mandatory Blockers: "
        f"{report.simulated_readiness_after_mandatory_blockers}",
        f"- Actual Authoritative Readiness: {report.actual_authoritative_readiness}",
        "Selection-Bias Scenarios: " + _scenario_text(report.scenario_distributions),
        f"Bias Distance, Current / Provisional: "
        f"{_decimal(report.baseline_bias_distance)} / "
        f"{_decimal(report.provisional_bias_distance)}",
        f"Selection-Bias Impact: {report.selection_bias_impact.value}",
        "Operational Audit:",
        f"- Requests Total / Successful: {report.total_network_requests} / "
        f"{report.successful_requests}",
        f"- Authentication / Rate-Limit / Transient / Permanent Failures: "
        f"{report.authentication_failures} / {report.rate_limit_responses} / "
        f"{report.transient_failures} / {report.permanent_failures}",
        f"- Retries: {report.retries}",
        f"- Elapsed Seconds / Request Rate: {report.elapsed_seconds} / "
        f"{_decimal(report.request_rate_per_second)} per second",
        f"- Early-Stop Status: {report.early_stop_status}",
        f"- Token Exposure Incidents: {report.token_exposure_incidents}",
        f"- Account / Order Endpoint Calls: {report.account_endpoint_calls} / "
        f"{report.order_endpoint_calls}",
        f"Price Availability: {report.price_availability_conclusion}",
        f"Identity Authority: {report.identity_authority_conclusion}",
        f"Corporate-Action Authority: {report.corporate_action_authority_conclusion}",
        f"Production Suitability: {report.production_suitability_conclusion}",
        f"Recommended Upstox Source Role: {report.recommended_source_role.value}",
        f"Exact Conclusion: {report.exact_conclusion.value}",
        "PRODUCTION_INFLUENCE=false",
    )


def _terminal_status(item: UpstoxHistoricalCandidateEvidence) -> str:
    status = item.coverage_classification
    aliases = {
        UpstoxCoverageClassification.RATE_LIMITED: (
            UpstoxCoverageClassification.RATE_LIMITED_UNRESOLVED
        ),
        UpstoxCoverageClassification.PROVIDER_ERROR: (
            UpstoxCoverageClassification.PROVIDER_ERROR_UNRESOLVED
        ),
        UpstoxCoverageClassification.IDENTITY_UNRESOLVED: (
            UpstoxCoverageClassification.INSTRUMENT_NOT_FOUND
        ),
        UpstoxCoverageClassification.HISTORICAL_SYMBOL_UNAVAILABLE: (
            UpstoxCoverageClassification.INSTRUMENT_NOT_FOUND
        ),
        UpstoxCoverageClassification.MULTI_SESSION_GAPS: (
            UpstoxCoverageClassification.PARTIAL_PRICE_COVERAGE
        ),
    }
    return aliases.get(status, status).value


def _coverage_slices(
    manifest: Sequence[HistoricalSourceEvaluationManifestRecord],
    *,
    full_ids: set[str],
    contexts: Mapping[str, BreakoutGapAttributionRecord],
) -> tuple[UpstoxCoverageSlice, ...]:
    extractors: tuple[
        tuple[str, Callable[[HistoricalSourceEvaluationManifestRecord], str]], ...
    ] = (
        ("historical_symbol", lambda item: item.historical_symbol),
        ("replay_year", lambda item: str(item.replay_year)),
        ("candidate_year", lambda item: str(item.candidate_date.year)),
        ("year_group", _year_group),
        ("gap_cause", lambda item: item.gap_cause.value),
        ("recovery_population", lambda item: item.recovery_population),
        ("setup_type", lambda item: item.setup_type or "UNAVAILABLE"),
        (
            "entry_timing",
            lambda item: _context_value(
                contexts, item.candidate_id, "entry_timing_state"
            ),
        ),
        ("market_regime", lambda item: item.market_regime or "UNAVAILABLE"),
        (
            "breadth_state",
            lambda item: _context_value(contexts, item.candidate_id, "breadth_state"),
        ),
        ("continuity_status", lambda item: item.continuity_status),
        (
            "active_status",
            lambda item: (
                "ACTIVE"
                if item.continuity_status == "ACTIVE_TO_SOURCE_END"
                else "INACTIVE"
            ),
        ),
        (
            "corporate_action_ambiguity",
            lambda item: "YES" if item.corporate_action_requirement else "NO",
        ),
    )
    rows: list[UpstoxCoverageSlice] = []
    for dimension, extractor in extractors:
        totals: Counter[str] = Counter()
        covered: Counter[str] = Counter()
        for item in manifest:
            key = extractor(item)
            totals[key] += 1
            if item.candidate_id in full_ids:
                covered[key] += 1
        rows.extend(
            UpstoxCoverageSlice(
                dimension=dimension,
                key=key,
                candidates=totals[key],
                full_price_coverage=covered[key],
                coverage_rate=_ratio(covered[key], totals[key]),
            )
            for key in sorted(totals)
        )
    return tuple(rows)


def _marginal_value(
    manifest: Mapping[str, HistoricalSourceEvaluationManifestRecord],
    full: Sequence[UpstoxHistoricalCandidateEvidence],
) -> _BlockerCounts:
    identity = corporate = both = price_only = 0
    for evidence in full:
        record = manifest[evidence.candidate_id]
        identity_blocked = record.identity_uncertainty
        corporate_blocked = record.corporate_action_requirement
        identity += identity_blocked
        corporate += corporate_blocked
        both += identity_blocked and corporate_blocked
        price_only += not identity_blocked and not corporate_blocked
    return _BlockerCounts(identity, corporate, both, price_only)


def _selection_bias_scenarios(
    rows: Sequence[BreakoutGapAttributionRecord],
    *,
    full_ids: set[str],
) -> _SelectionScenario:
    current = tuple(item for item in rows if item.ready)
    expanded = tuple(
        item for item in rows if item.ready or item.candidate_id in full_ids
    )
    remaining = tuple(
        item for item in rows if not item.ready and item.candidate_id not in full_ids
    )
    dimensions: tuple[
        tuple[str, Callable[[BreakoutGapAttributionRecord], str]], ...
    ] = (
        ("year", lambda item: str(item.candidate_date.year)),
        ("setup_type", lambda item: item.context.setup_type or "UNAVAILABLE"),
        (
            "entry_timing",
            lambda item: item.context.entry_timing_state or "UNAVAILABLE",
        ),
        ("market_regime", lambda item: item.context.market_regime or "UNAVAILABLE"),
        ("breadth_state", lambda item: item.context.breadth_state or "UNAVAILABLE"),
        (
            "symbol_continuity",
            lambda item: item.context.known_symbol_change_status or "UNAVAILABLE",
        ),
        (
            "inactive_status",
            lambda item: item.context.inactive_or_delisted_status or "UNAVAILABLE",
        ),
        (
            "corporate_action_status",
            lambda item: item.context.source.corporate_action_status or "UNAVAILABLE",
        ),
    )
    output: list[UpstoxScenarioDistribution] = []
    baseline_distances: list[Decimal] = []
    provisional_distances: list[Decimal] = []
    for dimension, extractor in dimensions:
        population_counts = Counter(extractor(item) for item in rows)
        current_counts = Counter(extractor(item) for item in current)
        expanded_counts = Counter(extractor(item) for item in expanded)
        remaining_counts = Counter(extractor(item) for item in remaining)
        keys = sorted(population_counts)
        output.extend(
            UpstoxScenarioDistribution(
                dimension=dimension,
                key=key,
                current_authoritative=current_counts[key],
                authoritative_plus_provisional_price=expanded_counts[key],
                remaining_unavailable=remaining_counts[key],
            )
            for key in keys
        )
        baseline = _total_variation(
            current_counts,
            len(current),
            population_counts,
            len(rows),
        )
        provisional = _total_variation(
            expanded_counts, len(expanded), population_counts, len(rows)
        )
        if baseline is not None and provisional is not None:
            baseline_distances.append(baseline)
            provisional_distances.append(provisional)
    return _SelectionScenario(
        rows=tuple(output),
        baseline_distance=_mean(baseline_distances),
        provisional_distance=_mean(provisional_distances),
    )


def _source_role(
    *,
    population_complete: bool,
    full_rate: Decimal | None,
    slices: Sequence[UpstoxCoverageSlice],
    impact: UpstoxSelectionBiasImpact,
    observed: Sequence[UpstoxHistoricalCandidateEvidence],
    dataset: UpstoxHistoricalEvidenceDataset | None,
) -> tuple[UpstoxProbeConclusion, UpstoxRecommendedSourceRole]:
    if not population_complete or full_rate is None:
        return (
            UpstoxProbeConclusion.UPSTOX_FULL_TRIAL_INCOMPLETE,
            UpstoxRecommendedSourceRole.EMPIRICAL_TRIAL_ONLY,
        )
    unresolved_operations = sum(
        _terminal_status(item)
        in {
            UpstoxCoverageClassification.AUTHENTICATION_FAILED.value,
            UpstoxCoverageClassification.RATE_LIMITED_UNRESOLVED.value,
            UpstoxCoverageClassification.PROVIDER_ERROR_UNRESOLVED.value,
        }
        for item in observed
    )
    authentication_failures = (
        dataset.operational_metrics.authentication_failures if dataset else 0
    )
    if authentication_failures or unresolved_operations > len(observed) // 20:
        return (
            UpstoxProbeConclusion.UPSTOX_OPERATIONALLY_UNRELIABLE,
            UpstoxRecommendedSourceRole.EMPIRICAL_TRIAL_ONLY,
        )
    if full_rate < Decimal("0.25"):
        return (
            UpstoxProbeConclusion.UPSTOX_PRICE_COVERAGE_TOO_LOW,
            UpstoxRecommendedSourceRole.NOT_USEFUL_FOR_HISTORICAL_RECOVERY,
        )
    year_rates = tuple(
        item.coverage_rate
        for item in slices
        if item.dimension == "year_group"
        and item.coverage_rate is not None
        and item.candidates > 0
    )
    if year_rates and max(year_rates) - min(year_rates) >= Decimal("0.25"):
        return (
            UpstoxProbeConclusion.UPSTOX_PRICE_COVERAGE_YEAR_BIASED,
            UpstoxRecommendedSourceRole.LIMITED_SECONDARY_PRICE_VALIDATION,
        )
    if full_rate >= Decimal("0.65") and impact in {
        UpstoxSelectionBiasImpact.MATERIALLY_REDUCES_OBSERVED_SELECTION_BIAS,
        UpstoxSelectionBiasImpact.MODESTLY_REDUCES_OBSERVED_SELECTION_BIAS,
    }:
        return (
            UpstoxProbeConclusion.UPSTOX_SECONDARY_PRICE_SOURCE_USEFUL,
            UpstoxRecommendedSourceRole.SECONDARY_PRICE_VALIDATION,
        )
    return (
        UpstoxProbeConclusion.UPSTOX_SECONDARY_PRICE_SOURCE_LIMITED,
        UpstoxRecommendedSourceRole.LIMITED_SECONDARY_PRICE_VALIDATION,
    )


def _year_group(item: HistoricalSourceEvaluationManifestRecord) -> str:
    year = item.candidate_date.year
    if year == 2016:
        return "2016"
    if 2017 <= year <= 2020:
        return "2017-2020"
    if 2021 <= year <= 2026:
        return "2021-2026"
    return "OTHER"


def _context_value(
    contexts: Mapping[str, BreakoutGapAttributionRecord],
    candidate_id: str,
    attribute: str,
) -> str:
    item = contexts.get(candidate_id)
    if item is None:
        return "UNAVAILABLE"
    value = getattr(item.context, attribute)
    return str(value) if value else "UNAVAILABLE"


def _ratio(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        _FOUR, rounding=ROUND_HALF_UP
    )


def _hhi(counts: Mapping[str, int]) -> Decimal | None:
    total = sum(counts.values())
    if total <= 0:
        return None
    value = sum(
        ((Decimal(count) / Decimal(total)) ** 2 for count in counts.values()),
        start=Decimal("0"),
    )
    return value.quantize(_FOUR, rounding=ROUND_HALF_UP)


def _total_variation(
    left: Mapping[str, int],
    left_total: int,
    right: Mapping[str, int],
    right_total: int,
) -> Decimal | None:
    if left_total <= 0 or right_total <= 0:
        return None
    keys = set(left) | set(right)
    value = sum(
        abs(
            Decimal(left.get(key, 0)) / Decimal(left_total)
            - Decimal(right.get(key, 0)) / Decimal(right_total)
        )
        for key in keys
    ) / Decimal("2")
    return value.quantize(_FOUR, rounding=ROUND_HALF_UP)


def _mean(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    return (sum(values) / Decimal(len(values))).quantize(_FOUR, rounding=ROUND_HALF_UP)


def _pairs(values: Sequence[tuple[str, int]]) -> str:
    return "; ".join(f"{key}={value}" for key, value in values) or "none"


def _percent(value: Decimal | None) -> str:
    return "unavailable" if value is None else f"{value * Decimal('100'):.2f}%"


def _decimal(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


def _slice_text(
    report: UpstoxFullPopulationUtilityReport,
    dimension: str,
    key: str,
) -> str:
    row = next(
        (
            item
            for item in report.coverage_slices
            if item.dimension == dimension and item.key == key
        ),
        None,
    )
    if row is None:
        return "0/0 (unavailable)"
    return f"{row.full_price_coverage}/{row.candidates} ({_percent(row.coverage_rate)})"


def _dimension_text(
    report: UpstoxFullPopulationUtilityReport,
    dimension: str,
) -> str:
    rows = tuple(item for item in report.coverage_slices if item.dimension == dimension)
    return (
        "; ".join(
            f"{item.key}={item.full_price_coverage}/{item.candidates}" for item in rows
        )
        or "none"
    )


def _scenario_text(rows: Sequence[UpstoxScenarioDistribution]) -> str:
    return (
        "; ".join(
            f"{item.dimension}:{item.key}={item.current_authoritative}/"
            f"{item.authoritative_plus_provisional_price}/{item.remaining_unavailable}"
            for item in rows
        )
        or "none"
    )


__all__ = [
    "UPSTOX_FULL_POPULATION_UTILITY_VERSION",
    "UpstoxCoverageSlice",
    "UpstoxFullPopulationUtilityEngine",
    "UpstoxFullPopulationUtilityReport",
    "UpstoxScenarioDistribution",
    "UpstoxSelectionBiasImpact",
    "classify_selection_bias_impact",
    "render_upstox_full_population_utility",
]
