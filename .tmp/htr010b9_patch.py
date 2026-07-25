from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one anchor, found {count}: {old[:80]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# Public learning-intelligence publication contract.
replace_once(
    "alpha/learning_intelligence/__init__.py",
    "from alpha.learning_intelligence.fingerprints import (\n"
    "    fingerprint_from_ledger_entry,\n"
    "    fingerprint_from_recommendation,\n"
    ")\n",
    "from alpha.learning_intelligence.fingerprints import (\n"
    "    fingerprint_from_ledger_entry,\n"
    "    fingerprint_from_recommendation,\n"
    ")\n"
    "from alpha.learning_intelligence.publication import (\n"
    "    AdaptiveMetadataPublicationBatch,\n"
    "    AdaptiveMetadataPublicationRecord,\n"
    "    AdaptiveMetadataPublisher,\n"
    "    AdaptivePublicationEligibility,\n"
    "    PointInTimeAdaptiveMetadataPublisher,\n"
    ")\n",
)
replace_once(
    "alpha/learning_intelligence/__init__.py",
    "__all__ = [\n    \"AdaptiveLearningAssessment\",\n",
    "__all__ = [\n"
    "    \"AdaptiveLearningAssessment\",\n"
    "    \"AdaptiveMetadataPublicationBatch\",\n"
    "    \"AdaptiveMetadataPublicationRecord\",\n"
    "    \"AdaptiveMetadataPublisher\",\n"
    "    \"AdaptivePublicationEligibility\",\n",
)
replace_once(
    "alpha/learning_intelligence/__init__.py",
    "    \"LearningOutcomeSample\",\n",
    "    \"LearningOutcomeSample\",\n"
    "    \"PointInTimeAdaptiveMetadataPublisher\",\n",
)

# Explicit opt-in seam in the application orchestrator.
replace_once(
    "alpha/application/intelligence.py",
    "from alpha.learning_intelligence import concise_adaptive_line\n",
    "from alpha.learning_intelligence import (\n"
    "    AdaptiveMetadataPublisher,\n"
    "    concise_adaptive_line,\n"
    ")\n",
)
replace_once(
    "alpha/application/intelligence.py",
    "        explainability_engine: IntelligenceExplainabilityEngine | None = None,\n"
    "    ) -> None:\n",
    "        explainability_engine: IntelligenceExplainabilityEngine | None = None,\n"
    "        adaptive_metadata_publisher: AdaptiveMetadataPublisher | None = None,\n"
    "        adaptive_metadata_publication_enabled: bool = False,\n"
    "    ) -> None:\n",
)
replace_once(
    "alpha/application/intelligence.py",
    "        self._explainability_engine = (\n"
    "            explainability_engine or IntelligenceExplainabilityEngine()\n"
    "        )\n",
    "        self._explainability_engine = (\n"
    "            explainability_engine or IntelligenceExplainabilityEngine()\n"
    "        )\n"
    "        self._adaptive_metadata_publisher = adaptive_metadata_publisher\n"
    "        self._adaptive_metadata_publication_enabled = (\n"
    "            adaptive_metadata_publication_enabled\n"
    "        )\n"
    "        if (\n"
    "            self._adaptive_metadata_publication_enabled\n"
    "            and self._adaptive_metadata_publisher is None\n"
    "        ):\n"
    "            raise ValueError(\n"
    "                \"adaptive metadata publication requires an injected publisher\"\n"
    "            )\n",
)
replace_once(
    "alpha/application/intelligence.py",
    "        history_window: int = 250,\n"
    "    ) -> IntelligenceApplicationService:\n",
    "        history_window: int = 250,\n"
    "        adaptive_metadata_publisher: AdaptiveMetadataPublisher | None = None,\n"
    "        adaptive_metadata_publication_enabled: bool = False,\n"
    "    ) -> IntelligenceApplicationService:\n",
)
replace_once(
    "alpha/application/intelligence.py",
    "        return cls(\n"
    "            input_provider=_AnalysisIntelligenceInputProvider(\n"
    "                analysis=analysis,\n"
    "                builder=IntelligenceInputBuilder(\n"
    "                    price_repository=price_repository,\n"
    "                    history_window=history_window,\n"
    "                ),\n"
    "            )\n"
    "        )\n",
    "        return cls(\n"
    "            input_provider=_AnalysisIntelligenceInputProvider(\n"
    "                analysis=analysis,\n"
    "                builder=IntelligenceInputBuilder(\n"
    "                    price_repository=price_repository,\n"
    "                    history_window=history_window,\n"
    "                ),\n"
    "            ),\n"
    "            adaptive_metadata_publisher=adaptive_metadata_publisher,\n"
    "            adaptive_metadata_publication_enabled=(\n"
    "                adaptive_metadata_publication_enabled\n"
    "            ),\n"
    "        )\n",
)
replace_once(
    "alpha/application/intelligence.py",
    "        recommendations = self._recommendation_engine.build(\n"
    "            inputs.recommendation_candidates,\n"
    "            portfolio=inputs.recommendation_portfolio_context,\n"
    "        )\n"
    "        allocation_plan = self._construction_engine.construct(\n",
    "        recommendations = self._recommendation_engine.build(\n"
    "            inputs.recommendation_candidates,\n"
    "            portfolio=inputs.recommendation_portfolio_context,\n"
    "        )\n"
    "        if self._adaptive_metadata_publication_enabled:\n"
    "            publisher = self._adaptive_metadata_publisher\n"
    "            if publisher is None:\n"
    "                raise ValueError(\n"
    "                    \"adaptive metadata publication requires an injected publisher\"\n"
    "                )\n"
    "            recommendations = publisher.publish(\n"
    "                recommendations=recommendations,\n"
    "                observed_on=observed_on,\n"
    "                market_regime=market_report.bias.value,\n"
    "            ).recommendations\n"
    "        allocation_plan = self._construction_engine.construct(\n",
)

# Canonical runner seam remains explicitly disabled by default.
replace_once(
    "alpha/canonical_universe_audit/canonical_runner.py",
    "from alpha.portfolio_intelligence import AllocationCandidate\n",
    "from alpha.learning_intelligence import AdaptiveMetadataPublisher\n"
    "from alpha.portfolio_intelligence import AllocationCandidate\n",
)
replace_once(
    "alpha/canonical_universe_audit/canonical_runner.py",
    "        institutional_engine: InstitutionalDecisionEngine | None = None,\n"
    "    ) -> None:\n",
    "        institutional_engine: InstitutionalDecisionEngine | None = None,\n"
    "        adaptive_metadata_publisher: AdaptiveMetadataPublisher | None = None,\n"
    "        adaptive_metadata_publication_enabled: bool = False,\n"
    "    ) -> None:\n",
)
replace_once(
    "alpha/canonical_universe_audit/canonical_runner.py",
    "        self.institutional_engine = (\n"
    "            institutional_engine or InstitutionalDecisionEngine()\n"
    "        )\n",
    "        self.institutional_engine = (\n"
    "            institutional_engine or InstitutionalDecisionEngine()\n"
    "        )\n"
    "        self.adaptive_metadata_publisher = adaptive_metadata_publisher\n"
    "        self.adaptive_metadata_publication_enabled = (\n"
    "            adaptive_metadata_publication_enabled\n"
    "        )\n"
    "        if (\n"
    "            self.adaptive_metadata_publication_enabled\n"
    "            and self.adaptive_metadata_publisher is None\n"
    "        ):\n"
    "            raise ValueError(\n"
    "                \"adaptive metadata publication requires an injected publisher\"\n"
    "            )\n",
)
replace_once(
    "alpha/canonical_universe_audit/canonical_runner.py",
    "        intelligence = IntelligenceApplicationService(input_provider=provider).run(\n"
    "            observed_on=observed_on\n"
    "        )\n",
    "        intelligence = IntelligenceApplicationService(\n"
    "            input_provider=provider,\n"
    "            adaptive_metadata_publisher=self.adaptive_metadata_publisher,\n"
    "            adaptive_metadata_publication_enabled=(\n"
    "                self.adaptive_metadata_publication_enabled\n"
    "            ),\n"
    "        ).run(observed_on=observed_on)\n",
)

# Preserve complete future fingerprint snapshots without mutating old rows.
replace_once(
    "alpha/performance_intelligence/recorder.py",
    "            \"price_breakout\": recommendation.price_evidence.breakout_state,\n",
    "            \"price_breakout\": recommendation.price_evidence.breakout_state,\n"
    "            \"retracement_state\": (\n"
    "                recommendation.price_evidence.retracement_state\n"
    "            ),\n"
    "            \"candle_pattern\": recommendation.candle_pattern,\n",
)

# Benchmark CLI registration.
replace_once(
    "alpha/application/benchmark_cli.py",
    "from alpha.application.governed_adaptive_evidence_lineage_cli import (\n"
    "    register_governed_adaptive_evidence_lineage_command,\n"
    ")\n",
    "from alpha.application.governed_adaptive_evidence_lineage_cli import (\n"
    "    register_governed_adaptive_evidence_lineage_command,\n"
    ")\n"
    "from alpha.application.governed_adaptive_publication_bridge_cli import (\n"
    "    register_governed_adaptive_publication_bridge_command,\n"
    ")\n",
)
replace_once(
    "alpha/application/benchmark_cli.py",
    "register_governed_adaptive_evidence_lineage_command(benchmark_app)\n",
    "register_governed_adaptive_evidence_lineage_command(benchmark_app)\n"
    "register_governed_adaptive_publication_bridge_command(benchmark_app)\n",
)

# Public benchmark-replay exports.
replace_once(
    "alpha/benchmark_replay/__init__.py",
    "from alpha.benchmark_replay.governed_adaptive_evidence_lineage import (\n",
    "from alpha.benchmark_replay.governed_adaptive_publication_bridge import (\n"
    "    B9_BLOCKED_ARM,\n"
    "    B9_BLOCKED_DEFAULT,\n"
    "    B9_BLOCKED_DEFECT,\n"
    "    B9_BLOCKED_FINGERPRINT,\n"
    "    B9_BLOCKED_LEAKAGE,\n"
    "    B9_BLOCKED_ROUND_TRIP,\n"
    "    B9_READY,\n"
    "    HTR010B9_CONTRACT_VERSION,\n"
    "    GovernedAdaptivePublicationBridgeEngine,\n"
    "    GovernedAdaptivePublicationBridgeResult,\n"
    "    export_governed_adaptive_publication_bridge,\n"
    "    validate_governed_adaptive_publication_bridge_certificate,\n"
    ")\n"
    "from alpha.benchmark_replay.governed_adaptive_evidence_lineage import (\n",
)
replace_once(
    "alpha/benchmark_replay/__init__.py",
    "    \"B8_READY\",\n",
    "    \"B8_READY\",\n"
    "    \"B9_BLOCKED_ARM\",\n"
    "    \"B9_BLOCKED_DEFAULT\",\n"
    "    \"B9_BLOCKED_DEFECT\",\n"
    "    \"B9_BLOCKED_FINGERPRINT\",\n"
    "    \"B9_BLOCKED_LEAKAGE\",\n"
    "    \"B9_BLOCKED_ROUND_TRIP\",\n"
    "    \"B9_READY\",\n",
)
replace_once(
    "alpha/benchmark_replay/__init__.py",
    "    \"HTR010B8_CONTRACT_VERSION\",\n",
    "    \"HTR010B8_CONTRACT_VERSION\",\n"
    "    \"HTR010B9_CONTRACT_VERSION\",\n",
)
replace_once(
    "alpha/benchmark_replay/__init__.py",
    "    \"GovernedAdaptiveEvidenceLineageResult\",\n",
    "    \"GovernedAdaptiveEvidenceLineageResult\",\n"
    "    \"GovernedAdaptivePublicationBridgeEngine\",\n"
    "    \"GovernedAdaptivePublicationBridgeResult\",\n",
)
replace_once(
    "alpha/benchmark_replay/__init__.py",
    "    \"export_governed_adaptive_evidence_lineage\",\n",
    "    \"export_governed_adaptive_evidence_lineage\",\n"
    "    \"export_governed_adaptive_publication_bridge\",\n",
)
replace_once(
    "alpha/benchmark_replay/__init__.py",
    "    \"validate_governed_adaptive_evidence_lineage_certificate\",\n",
    "    \"validate_governed_adaptive_evidence_lineage_certificate\",\n"
    "    \"validate_governed_adaptive_publication_bridge_certificate\",\n",
)
