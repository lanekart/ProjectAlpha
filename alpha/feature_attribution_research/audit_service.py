"""Composition root for the diagnostic-only feature attribution milestone."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.feature_attribution_research.case_studies import FeatureCaseStudyEngine
from alpha.feature_attribution_research.chronological_validation import (
    OrthogonalEdgeAudit,
)
from alpha.feature_attribution_research.conditional import (
    ConditionalAttributionEngine,
)
from alpha.feature_attribution_research.feature_quality import FeatureQualityEngine
from alpha.feature_attribution_research.feature_registry import FeatureRegistry
from alpha.feature_attribution_research.interactions import FeatureInteractionEngine
from alpha.feature_attribution_research.leakage import FeatureLeakageAudit
from alpha.feature_attribution_research.missingness import MissingInformationAudit
from alpha.feature_attribution_research.models import (
    FeatureAttributionReport,
    TransactionCostPolicy,
)
from alpha.feature_attribution_research.negative_feature_audit import (
    NegativeFeatureAudit,
)
from alpha.feature_attribution_research.outcome_labels import (
    OutcomeLabelEngine,
    preregistered_outcome_definitions,
)
from alpha.feature_attribution_research.point_in_time_builder import (
    DEFAULT_ACU_RANKINGS,
    DEFAULT_CANDIDATE_LEDGER,
    PointInTimeFeatureBuilder,
)
from alpha.feature_attribution_research.population import (
    DEFAULT_ACU_DIRECTORY,
    DEFAULT_CANDIDATE_DIRECTORY,
    DEFAULT_SDE_DIRECTORY,
    ResearchPopulationEngine,
)
from alpha.feature_attribution_research.rankings import FeatureRankingEngine
from alpha.feature_attribution_research.redundancy import FeatureRedundancyEngine
from alpha.feature_attribution_research.stability import (
    FeatureStabilityEngine,
    InformationDecayEngine,
)
from alpha.feature_attribution_research.univariate import (
    UnivariateAttributionEngine,
)


class FeatureAttributionResearchEngine:
    """Run the complete research workflow without touching production policy."""

    def run(
        self,
        *,
        store: LegacyMarketDataStore,
        candidate_directory: Path | str = DEFAULT_CANDIDATE_DIRECTORY,
        sde_directory: Path | str = DEFAULT_SDE_DIRECTORY,
        acu_directory: Path | str = DEFAULT_ACU_DIRECTORY,
        candidate_ledger: Path | str = DEFAULT_CANDIDATE_LEDGER,
        acu_rankings: Path | str = DEFAULT_ACU_RANKINGS,
        transaction_cost_policy: TransactionCostPolicy = TransactionCostPolicy(),
        start: date | None = None,
        end: date | None = None,
        symbol: str | None = None,
        minimum_support: int = 50,
        generated_at: datetime | None = None,
    ) -> FeatureAttributionReport:
        population_build = ResearchPopulationEngine().build(
            store=store,
            candidate_directory=candidate_directory,
            sde_directory=sde_directory,
            acu_directory=acu_directory,
            start=start,
            end=end,
            symbol=symbol,
            transaction_cost_policy=transaction_cost_policy,
            generated_at=generated_at,
        )
        definitions = FeatureRegistry().definitions
        outcome_definitions = preregistered_outcome_definitions()
        outcomes = OutcomeLabelEngine().evaluate(
            store=store,
            population=population_build.records,
            transaction_cost_policy=transaction_cost_policy,
        )
        labelled = sum(item.target_before_stop is not None for item in outcomes)
        population_summary = replace(
            population_build.summary,
            labelled_market_opportunities=labelled,
        )
        snapshots = PointInTimeFeatureBuilder().build(
            store=store,
            population=population_build.records,
            candidate_ledger=candidate_ledger,
            acu_rankings=acu_rankings,
        )
        quality = FeatureQualityEngine().audit(
            definitions=definitions, snapshots=snapshots
        )
        leakage = FeatureLeakageAudit().audit(
            definitions=definitions, snapshots=snapshots
        )
        univariate = UnivariateAttributionEngine().analyze(
            definitions=definitions,
            snapshots=snapshots,
            outcomes=outcomes,
            minimum_support=minimum_support,
            bootstrap_samples=20,
        )
        negative = NegativeFeatureAudit().analyze(univariate)
        conditional = ConditionalAttributionEngine().analyze(
            definitions=definitions,
            population=population_build.records,
            snapshots=snapshots,
            outcomes=outcomes,
            minimum_support=minimum_support,
        )
        redundancy = FeatureRedundancyEngine().analyze(
            definitions=definitions,
            snapshots=snapshots,
            outcomes=outcomes,
            minimum_support=max(100, minimum_support),
        )
        interactions = FeatureInteractionEngine().analyze(
            snapshots=snapshots,
            outcomes=outcomes,
            minimum_support=minimum_support,
        )
        orthogonal = OrthogonalEdgeAudit().analyze(
            definitions=definitions,
            snapshots=snapshots,
            outcomes=outcomes,
            univariate=univariate,
            redundancy=redundancy,
            minimum_support=max(100, minimum_support),
        )
        decay = InformationDecayEngine().analyze(univariate)
        stability = FeatureStabilityEngine().analyze(
            definitions=definitions,
            snapshots=snapshots,
            outcomes=outcomes,
            univariate=univariate,
            conditional=conditional,
            quality=quality,
            minimum_support=minimum_support,
        )
        rankings, cards = FeatureRankingEngine().build(
            definitions=definitions,
            quality=quality,
            leakage=leakage,
            univariate=univariate,
            redundancy=redundancy,
            orthogonal=orthogonal,
            stability=stability,
            information_decay=decay,
        )
        cases = FeatureCaseStudyEngine().build(
            definitions=definitions,
            population=population_build.records,
            snapshots=snapshots,
            outcomes=outcomes,
            univariate=univariate,
            stability=stability,
            leakage=leakage,
            rankings=rankings,
        )
        return FeatureAttributionReport(
            manifest=population_build.manifest,
            population=population_build.records,
            population_summary=population_summary,
            feature_definitions=definitions,
            feature_snapshots=snapshots,
            outcome_definitions=outcome_definitions,
            outcomes=outcomes,
            quality=quality,
            leakage=leakage,
            univariate=univariate,
            negative_features=negative,
            conditional=conditional,
            redundancy=redundancy,
            interactions=interactions,
            orthogonal=orthogonal,
            information_decay=decay,
            stability=stability,
            rankings=rankings,
            missing_information=MissingInformationAudit().audit(),
            feature_cards=cards,
            case_studies=cases,
        )


__all__ = ["FeatureAttributionResearchEngine"]
