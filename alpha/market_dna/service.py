from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from hashlib import sha256
from typing import Protocol

from alpha.market_dna.cluster_discovery import ClusterDiscovery
from alpha.market_dna.cohort_builder import CohortBuilder
from alpha.market_dna.distribution_analysis import DistributionAnalysis
from alpha.market_dna.dna_registry import DNARegistry
from alpha.market_dna.effect_size_engine import EffectSizeEngine
from alpha.market_dna.feature_enrichment import FeatureQualityAuditEngine
from alpha.market_dna.feature_manifest import MarketDNAFeatureManifest
from alpha.market_dna.feature_snapshot_builder import FeatureSnapshotBuilder
from alpha.market_dna.hierarchical_dna import HierarchicalDNA
from alpha.market_dna.hypothesis_generator import HypothesisGenerator
from alpha.market_dna.interaction_discovery import InteractionDiscovery
from alpha.market_dna.matched_cohort import MatchedCohortEngine
from alpha.market_dna.models import (
    MARKET_DNA_SCHEMA_VERSION,
    CohortSummary,
    DistributionComparison,
    DNADiscoveryReport,
    DNAEvidenceClass,
    DNAHypothesis,
    DNAPattern,
    DNAPatternStatus,
    FeatureAudit,
    FeatureFinding,
    FeatureSnapshot,
    InteractionFinding,
    MarketDNAConclusion,
    MultipleTestingSummary,
)
from alpha.market_dna.multiple_testing_control import FalseDiscoveryControl
from alpha.market_dna.outcome_cohort_registry import OutcomeCohortRegistry
from alpha.market_dna.research_integration import record_market_dna_experiment
from alpha.market_dna.stability_analysis import StabilityAnalysis
from alpha.research.research_registry import ResearchExperimentRegistry
from alpha.strategy_discovery.historical_signal_generator import (
    HistoricalSignalGenerator,
)
from alpha.strategy_discovery.models import DiscoveryDataset


class DNADataSource(Protocol):
    def discovery_dataset(self) -> DiscoveryDataset: ...


@dataclass(frozen=True, slots=True)
class MarketDNARequest:
    horizon: str | None = None
    outcome_cohorts: tuple[str, ...] = ()
    setup: str | None = None
    symbols: tuple[str, ...] = ()
    sector: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    evidence_class: DNAEvidenceClass | None = None
    minimum_sample: int = 30
    maximum_interactions: int = 50

    def __post_init__(self) -> None:
        if self.minimum_sample < 5:
            raise ValueError("minimum sample must be at least 5")
        if self.maximum_interactions < 1 or self.maximum_interactions > 500:
            raise ValueError("maximum interactions must be between 1 and 500")
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start date cannot follow end date")
        if self.sector:
            raise ValueError(
                "historical sector is quarantined and cannot filter Market DNA"
            )


class MarketDNAService:
    """Compose existing point-in-time evidence into governed outcome-first research."""

    def __init__(
        self,
        *,
        data_source: DNADataSource | None = None,
        registry: DNARegistry | None = None,
        research_registry: ResearchExperimentRegistry | None = None,
        feature_manifest: MarketDNAFeatureManifest | None = None,
    ) -> None:
        self.data_source = data_source or HistoricalSignalGenerator()
        self.registry = registry or DNARegistry()
        self.research_registry = research_registry or ResearchExperimentRegistry()
        self.feature_manifest = feature_manifest or MarketDNAFeatureManifest()
        self.cohort_registry = OutcomeCohortRegistry()
        self.snapshot_builder = FeatureSnapshotBuilder()
        self.quality_engine = FeatureQualityAuditEngine()
        self.cohort_builder = CohortBuilder()
        self.matcher = MatchedCohortEngine()
        self.distributions = DistributionAnalysis()
        self.effect_engine = EffectSizeEngine()
        self.interactions = InteractionDiscovery()
        self.multiple_testing = FalseDiscoveryControl()
        self.clusters = ClusterDiscovery()
        self.hierarchy = HierarchicalDNA()
        self.stability = StabilityAnalysis()
        self.hypotheses = HypothesisGenerator()

    def inventory(self) -> tuple[object, ...]:
        return self.feature_manifest.definitions

    def report(
        self,
        request: MarketDNARequest | None = None,
    ) -> DNADiscoveryReport:
        active = request or MarketDNARequest()
        dataset = self.data_source.discovery_dataset()
        snapshots = _filter(self.snapshot_builder.build(dataset), active)
        if active.evidence_class is not None and (
            not snapshots or snapshots[0].evidence_class is not active.evidence_class
        ):
            raise ValueError("requested evidence class is unavailable")
        audits = self.quality_engine.audit(self.feature_manifest.definitions, snapshots)
        definitions = (
            tuple(self.cohort_registry.require(item) for item in active.outcome_cohorts)
            if active.outcome_cohorts
            else self.cohort_registry.definitions
        )
        cohorts = tuple(
            self.cohort_builder.build(definition, snapshots)
            for definition in definitions
        )
        matched = tuple(self.matcher.match(cohort, snapshots) for cohort in cohorts)
        matched_by_id = {item.cohort_id: item for item in matched}
        raw_findings: list[FeatureFinding] = []
        distributions: list[DistributionComparison] = []
        for cohort in cohorts:
            cohort_match = matched_by_id[cohort.definition.cohort_id]
            use_match = cohort_match.matched_pairs >= active.minimum_sample
            raw_findings.extend(
                self.effect_engine.evaluate(
                    cohort=cohort,
                    scope="UNIVERSAL",
                    snapshots=snapshots,
                    audits=audits,
                    matched_candidate_ids=(
                        frozenset(cohort_match.matched_candidate_ids)
                        if use_match
                        else None
                    ),
                    matched_baseline_ids=(
                        frozenset(cohort_match.matched_baseline_ids)
                        if use_match
                        else None
                    ),
                )
            )
            distributions.extend(
                self.distributions.compare(
                    cohort_id=cohort.definition.cohort_id,
                    scope="UNIVERSAL",
                    cohort_ids=frozenset(cohort.candidate_ids),
                    snapshots=snapshots,
                    audits=audits,
                )
            )
            raw_findings.extend(
                self._hierarchical_findings(
                    cohort=cohort,
                    snapshots=snapshots,
                    audits=audits,
                    minimum_sample=active.minimum_sample,
                )
            )
        findings, testing = self.multiple_testing.adjust_findings(tuple(raw_findings))
        interactions = self._interactions(
            cohorts=cohorts,
            snapshots=snapshots,
            findings=findings,
            audits=audits,
            minimum_sample=active.minimum_sample,
            maximum_interactions=active.maximum_interactions,
        )
        adjusted_interactions = self.multiple_testing.adjust_interactions(interactions)
        testing = _combined_testing(testing, adjusted_interactions)
        patterns = self.stability.patterns(
            findings=findings,
            interactions=adjusted_interactions,
            minimum_sample=active.minimum_sample,
        )
        hypotheses = self.hypotheses.generate(patterns)
        final_conclusion = _conclusion(patterns, hypotheses)
        report = DNADiscoveryReport(
            report_id=_report_id(dataset, active),
            generated_at=dataset.generated_at,
            dataset_version=dataset.dataset_version,
            evidence_class=(
                snapshots[0].evidence_class
                if snapshots
                else DNAEvidenceClass.PROVISIONAL
            ),
            source_rows=len(snapshots),
            excluded_rows=len(dataset.exclusions),
            feature_audits=audits,
            cohorts=cohorts,
            matched_cohorts=matched,
            distributions=tuple(distributions),
            findings=findings,
            interactions=adjusted_interactions,
            clusters=self.clusters.discover(snapshots),
            hierarchy=self.hierarchy.summarize(
                snapshots=snapshots,
                findings=findings,
                minimum_sample=active.minimum_sample,
            ),
            patterns=patterns,
            hypotheses=hypotheses,
            multiple_testing=testing,
            final_conclusion=final_conclusion,
            highest_value_evidence_gap=(
                "Authoritative completed outcomes with corporate-action-complete "
                "chronological bars and a genuinely untouched holdout population."
            ),
            limitations=(
                "All current historical outcomes are reconstructed research evidence.",
                "Discovery and evaluation share the same population; no unchanged "
                "holdout claim is made.",
                "Regime, sector, retracement, and future-derived features remain "
                "quarantined.",
                "Associations are not causal and DNA scores are not exposed to live "
                "recommendations.",
            ),
        )
        self.registry.record(report)
        record_market_dna_experiment(report, registry=self.research_registry)
        return report

    def _hierarchical_findings(
        self,
        *,
        cohort: CohortSummary,
        snapshots: tuple[FeatureSnapshot, ...],
        audits: tuple[FeatureAudit, ...],
        minimum_sample: int,
    ) -> tuple[FeatureFinding, ...]:
        if cohort.definition.cohort_id not in {
            "STRONG_WINNERS",
            "CATASTROPHIC_LOSERS",
            "PROFITABLE_REJECTED",
            "APPROVED_UNPROFITABLE",
        }:
            return ()
        output: list[FeatureFinding] = []
        dimensions = (
            ("SETUP", tuple(sorted({item.setup for item in snapshots}))),
            ("HORIZON", tuple(sorted({item.horizon for item in snapshots}))),
        )
        cohort_ids = frozenset(cohort.candidate_ids)
        for kind, values in dimensions:
            for value in values:
                scoped = tuple(
                    item
                    for item in snapshots
                    if (item.setup if kind == "SETUP" else item.horizon) == value
                )
                scoped_ids = tuple(
                    item.candidate_id
                    for item in scoped
                    if item.candidate_id in cohort_ids
                )
                if (
                    len(scoped_ids) < minimum_sample
                    or len(scoped) - len(scoped_ids) < minimum_sample
                ):
                    continue
                scoped_cohort = replace(
                    cohort,
                    candidate_ids=scoped_ids,
                    sample_size=len(scoped_ids),
                    symbol_count=len(
                        {
                            item.symbol
                            for item in scoped
                            if item.candidate_id in frozenset(scoped_ids)
                        }
                    ),
                )
                output.extend(
                    self.effect_engine.evaluate(
                        cohort=scoped_cohort,
                        scope=f"{kind}:{value}",
                        snapshots=scoped,
                        audits=audits,
                    )
                )
        return tuple(output)

    def _interactions(
        self,
        *,
        cohorts: tuple[CohortSummary, ...],
        snapshots: tuple[FeatureSnapshot, ...],
        findings: tuple[FeatureFinding, ...],
        audits: tuple[FeatureAudit, ...],
        minimum_sample: int,
        maximum_interactions: int,
    ) -> tuple[InteractionFinding, ...]:
        target_ids = {
            "STRONG_WINNERS",
            "CATASTROPHIC_LOSERS",
            "PROFITABLE_REJECTED",
        }
        output: list[InteractionFinding] = []
        remaining = maximum_interactions
        for cohort in cohorts:
            if cohort.definition.cohort_id not in target_ids or remaining <= 0:
                continue
            discovered = self.interactions.discover(
                cohort=cohort,
                snapshots=snapshots,
                findings=tuple(
                    item
                    for item in findings
                    if item.scope == "UNIVERSAL"
                    and item.cohort_id == cohort.definition.cohort_id
                ),
                audits=audits,
                minimum_cell=minimum_sample,
                maximum_interactions=remaining,
            )
            output.extend(discovered)
            remaining -= len(discovered)
        return tuple(output)


def _filter(
    snapshots: tuple[FeatureSnapshot, ...], request: MarketDNARequest
) -> tuple[FeatureSnapshot, ...]:
    symbols = frozenset(item.strip().upper() for item in request.symbols)
    setup = request.setup.strip().upper() if request.setup else None
    return tuple(
        item
        for item in snapshots
        if (request.horizon is None or item.horizon == request.horizon)
        and (setup is None or item.setup.upper() == setup)
        and (not symbols or item.symbol in symbols)
        and (
            request.start_date is None
            or item.candidate_timestamp.date() >= request.start_date
        )
        and (
            request.end_date is None
            or item.candidate_timestamp.date() <= request.end_date
        )
    )


def _report_id(dataset: DiscoveryDataset, request: MarketDNARequest) -> str:
    key = "|".join(
        (
            MARKET_DNA_SCHEMA_VERSION,
            dataset.dataset_version,
            request.horizon or "ALL",
            ",".join(sorted(request.outcome_cohorts)) or "ALL",
            request.setup or "ALL",
            ",".join(sorted(request.symbols)) or "ALL",
            str(request.start_date),
            str(request.end_date),
            str(request.minimum_sample),
            str(request.maximum_interactions),
        )
    )
    return "market-dna-" + sha256(key.encode()).hexdigest()[:24]


def _combined_testing(
    base: MultipleTestingSummary,
    interactions: tuple[InteractionFinding, ...],
) -> MultipleTestingSummary:
    surviving = sum(
        item.adjusted_p_value is not None and item.adjusted_p_value <= Decimal("0.05")
        for item in interactions
    )
    return MultipleTestingSummary(
        hypotheses_tested=base.hypotheses_tested + len(interactions),
        effective_hypotheses=base.effective_hypotheses
        + sum(item.raw_p_value is not None for item in interactions),
        procedure="BENJAMINI_HOCHBERG_FDR_BY_FEATURE_AND_INTERACTION_FAMILY",
        significance_threshold=base.significance_threshold,
        surviving_findings=base.surviving_findings + surviving,
        rejected_findings=base.rejected_findings + len(interactions) - surviving,
    )


def _conclusion(
    patterns: tuple[DNAPattern, ...], hypotheses: tuple[DNAHypothesis, ...]
) -> str:
    dna = MarketDNAConclusion
    if hypotheses:
        return f"PUBLISH_{hypotheses[0].hypothesis_id}_TO_STRATEGY_LAB"
    robust = any(
        getattr(item, "status", None)
        in {
            DNAPatternStatus.ROBUST_RESEARCH_PATTERN,
            DNAPatternStatus.STRATEGY_HYPOTHESIS_CANDIDATE,
        }
        for item in patterns
    )
    if robust:
        return dna.ROBUST_RESEARCH_PATTERNS_FOUND_NO_STRATEGY_HYPOTHESES.value
    return MarketDNAConclusion.NO_ROBUST_MARKET_DNA_FOUND.value


__all__ = ["DNADataSource", "MarketDNARequest", "MarketDNAService"]
