from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, time
from pathlib import Path
from types import MappingProxyType
from typing import Annotated

import typer

from alpha.adaptive_weights.ablation_engine import MatchedAblationEngine
from alpha.adaptive_weights.conditional_weights import ConditionalWeightResearchEngine
from alpha.adaptive_weights.confidence_engine import ContributionConfidenceEngine
from alpha.adaptive_weights.evidence_builder import (
    CompletedOutcomeEvidenceBuilder,
    filter_evidence,
    load_evidence,
)
from alpha.adaptive_weights.marginal_contribution import MarginalContributionEngine
from alpha.adaptive_weights.models import (
    AblationContribution,
    AblationObservation,
    AdaptiveWeightResearchReport,
    CandidateWeightPolicy,
    CompletedOutcomeEvidence,
    ConditionalWeightPolicy,
    ConfidenceAssessment,
    ContributionEstimate,
    EvidencePartition,
    OverlapFinding,
    PolicyComparison,
    PromotionAssessment,
    PromotionDecision,
    StabilityAssessment,
    WeightProposal,
    canonical_weight_set,
    deployed_weight_set,
    to_primitive,
)
from alpha.adaptive_weights.overlap_analysis import IndicatorOverlapEngine
from alpha.adaptive_weights.policy_registry import (
    CandidateWeightPolicyFactory,
    CandidateWeightPolicyRegistry,
)
from alpha.adaptive_weights.promotion import (
    CandidateWeightPromotionEngine,
    PolicyComparisonEngine,
)
from alpha.adaptive_weights.proposal_engine import AdaptiveWeightProposalEngine
from alpha.adaptive_weights.rendering import (
    render_comparisons,
    render_conditional,
    render_contributions,
    render_overlap,
    render_policy,
    render_promotion,
    render_proposal,
    render_stability,
    render_weight_audit,
    write_csv,
)
from alpha.adaptive_weights.research_integration import (
    record_adaptive_weight_experiment,
)
from alpha.adaptive_weights.stability_analysis import ContributionStabilityEngine
from alpha.performance_intelligence.ledger import RecommendationLedgerRepository
from alpha.performance_intelligence.service import resolve_ledger_path
from alpha.tradingview_research.registry import TradingViewResearchRegistry
from alpha.tradingview_research.weight_evidence import TradingViewWeightEvidenceAdapter

adaptive_weights_app = typer.Typer(
    help="Research evidence-based Alpha component weights without production mutation.",
    no_args_is_help=True,
)


@dataclass(frozen=True, slots=True)
class _Options:
    evidence_path: Path | None
    partition: EvidencePartition | None
    setup: str | None
    regime: str | None
    sector: str | None
    horizon: str | None
    dataset_version: str | None
    baseline_policy: str
    candidate_policy: str | None
    json_output: bool
    csv_output: bool
    output: Path | None
    policy_registry: Path | None


@dataclass(frozen=True, slots=True)
class _Bundle:
    evidence: tuple[CompletedOutcomeEvidence, ...]
    contributions: tuple[ContributionEstimate, ...]
    ablations: tuple[AblationContribution, ...]
    overlaps: tuple[OverlapFinding, ...]
    stabilities: tuple[StabilityAssessment, ...]
    confidences: tuple[ConfidenceAssessment, ...]
    proposal: WeightProposal
    conditional: ConditionalWeightPolicy


@adaptive_weights_app.callback()
def adaptive_weight_options(
    context: typer.Context,
    evidence_path: Annotated[Path | None, typer.Option("--evidence")] = None,
    partition: Annotated[
        EvidencePartition | None,
        typer.Option("--partition", case_sensitive=False),
    ] = None,
    setup: Annotated[str | None, typer.Option("--setup")] = None,
    regime: Annotated[str | None, typer.Option("--regime")] = None,
    sector: Annotated[str | None, typer.Option("--sector")] = None,
    horizon: Annotated[str | None, typer.Option("--horizon")] = None,
    dataset_version: Annotated[str | None, typer.Option("--dataset-version")] = None,
    baseline_policy: Annotated[
        str, typer.Option("--baseline-policy")
    ] = "ALPHA_CANONICAL",
    candidate_policy: Annotated[str | None, typer.Option("--candidate-policy")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    csv_output: Annotated[bool, typer.Option("--csv")] = False,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    policy_registry: Annotated[Path | None, typer.Option("--policy-registry")] = None,
) -> None:
    if json_output and csv_output:
        raise typer.BadParameter("choose either --json or --csv")
    context.obj = _Options(
        evidence_path=evidence_path,
        partition=partition,
        setup=setup,
        regime=regime,
        sector=sector,
        horizon=horizon,
        dataset_version=dataset_version,
        baseline_policy=baseline_policy,
        candidate_policy=candidate_policy,
        json_output=json_output,
        csv_output=csv_output,
        output=output,
        policy_registry=policy_registry,
    )


@adaptive_weights_app.command("audit")
def audit(context: typer.Context) -> None:
    options = _options(context)
    evidence = _load_filtered_evidence(options)
    counts: dict[str, int] = {}
    for item in evidence:
        counts[item.partition.value] = counts.get(item.partition.value, 0) + 1
    text = render_weight_audit(
        canonical_weight_set(),
        deployed_weight_set(),
        evidence_count=len(evidence),
        partition_counts=counts,
    )
    _emit(
        options,
        text,
        {
            "canonical": canonical_weight_set(),
            "deployed": deployed_weight_set(),
            "completed_evidence_count": len(evidence),
            "partition_counts": counts,
            "production_influence": False,
        },
        canonical_weight_set().weights,
    )


@adaptive_weights_app.command("contributions")
def contributions(context: typer.Context) -> None:
    options = _options(context)
    bundle = _analyze(options)
    _emit(
        options,
        render_contributions(
            bundle.contributions,
            bundle.ablations,
            bundle.stabilities,
            bundle.confidences,
            bundle.proposal.decisions,
        ),
        {
            "contributions": bundle.contributions,
            "matched_ablations": bundle.ablations,
            "production_influence": False,
        },
        bundle.contributions,
    )


@adaptive_weights_app.command("overlap")
def overlap(context: typer.Context) -> None:
    options = _options(context)
    findings = _analyze(options).overlaps
    _emit(
        options,
        render_overlap(findings),
        {"overlap": findings, "production_influence": False},
        findings,
    )


@adaptive_weights_app.command("stability")
def stability(context: typer.Context) -> None:
    options = _options(context)
    assessments = _analyze(options).stabilities
    _emit(
        options,
        render_stability(assessments),
        {"stability": assessments, "production_influence": False},
        assessments,
    )


@adaptive_weights_app.command("propose")
def propose(context: typer.Context) -> None:
    options = _options(context)
    bundle = _analyze(options)
    if not bundle.evidence:
        text = render_proposal(bundle.proposal) + "\n" + render_policy(None)
        text += "Registry Status: NOT_CREATED_NO_COMPLETED_EVIDENCE\n"
        _emit(
            options,
            text,
            {
                "proposal": bundle.proposal,
                "candidate_policy": None,
                "registry_created": False,
                "reason": "no eligible completed evidence",
            },
            bundle.proposal.decisions,
        )
        return
    policy, created = _freeze_policy(options, bundle)
    record_adaptive_weight_experiment(
        policy,
        bundle.contributions,
        bundle.overlaps,
        bundle.stabilities,
    )
    text = render_proposal(bundle.proposal) + "\n" + render_policy(policy)
    text += f"Registry Status: {'CREATED' if created else 'ALREADY_RECORDED'}\n"
    _emit(
        options,
        text,
        {
            "proposal": bundle.proposal,
            "candidate_policy": policy,
            "registry_created": created,
        },
        bundle.proposal.decisions,
    )


@adaptive_weights_app.command("conditional")
def conditional(context: typer.Context) -> None:
    options = _options(context)
    policy = _analyze(options).conditional
    _emit(
        options,
        render_conditional(policy),
        {"conditional_policy": policy, "production_influence": False},
        policy.conditionals,
    )


@adaptive_weights_app.command("policy")
def policy(context: typer.Context) -> None:
    options = _options(context)
    registry = CandidateWeightPolicyRegistry(options.policy_registry)
    policies = registry.load()
    selected = (
        registry.get(options.candidate_policy)
        if options.candidate_policy
        else policies[-1]
        if policies
        else None
    )
    _emit(
        options,
        render_policy(selected),
        {"policy": selected, "production_influence": False},
        (selected,) if selected is not None else (),
    )


@adaptive_weights_app.command("compare")
def compare(context: typer.Context) -> None:
    options = _options(context)
    evidence = _load_filtered_evidence(options)
    candidate = _candidate_id(options)
    comparisons = _comparisons(
        evidence,
        baseline_policy=options.baseline_policy,
        candidate_policy=candidate,
    )
    _emit(
        options,
        render_comparisons(comparisons),
        {"comparisons": comparisons, "production_influence": False},
        comparisons,
    )


@adaptive_weights_app.command("promotion")
def promotion(context: typer.Context) -> None:
    options = _options(context)
    bundle = _analyze(options)
    candidate = _candidate_id(options)
    comparisons = _comparisons(
        bundle.evidence,
        baseline_policy=options.baseline_policy,
        candidate_policy=candidate,
    )
    assessment = _promotion(candidate, comparisons, bundle)
    _emit(
        options,
        render_promotion(assessment),
        assessment,
        (assessment,),
    )


@adaptive_weights_app.command("report")
def report(context: typer.Context) -> None:
    options = _options(context)
    bundle = _analyze(options)
    registry = CandidateWeightPolicyRegistry(options.policy_registry)
    candidate_policy = (
        registry.get(options.candidate_policy)
        if options.candidate_policy
        else registry.load()[-1]
        if registry.load()
        else None
    )
    candidate_id = candidate_policy.policy_id if candidate_policy else "UNAVAILABLE"
    comparisons = _comparisons(
        bundle.evidence,
        baseline_policy=options.baseline_policy,
        candidate_policy=candidate_id,
    )
    promotion_assessment = _promotion(candidate_id, comparisons, bundle)
    partition_counts: dict[str, int] = {}
    for item in bundle.evidence:
        partition_counts[item.partition.value] = (
            partition_counts.get(item.partition.value, 0) + 1
        )
    research_report = AdaptiveWeightResearchReport(
        evidence_count=len(bundle.evidence),
        partition_counts=MappingProxyType(partition_counts),
        contributions=bundle.contributions,
        ablations=bundle.ablations,
        overlaps=bundle.overlaps,
        stabilities=bundle.stabilities,
        proposal=bundle.proposal,
        candidate_policy=candidate_policy,
        promotion=promotion_assessment,
    )
    text = "\n".join(
        (
            render_weight_audit(
                canonical_weight_set(),
                deployed_weight_set(),
                evidence_count=len(bundle.evidence),
                partition_counts=partition_counts,
            ).rstrip(),
            render_contributions(
                bundle.contributions,
                bundle.ablations,
                bundle.stabilities,
                bundle.confidences,
                bundle.proposal.decisions,
            ).rstrip(),
            render_overlap(bundle.overlaps).rstrip(),
            render_stability(bundle.stabilities).rstrip(),
            render_proposal(bundle.proposal).rstrip(),
            render_conditional(bundle.conditional).rstrip(),
            render_policy(candidate_policy).rstrip(),
            render_comparisons(comparisons).rstrip(),
            render_promotion(promotion_assessment).rstrip(),
            "",
        )
    )
    _emit(options, text, research_report, bundle.proposal.decisions)


def _analyze(options: _Options) -> _Bundle:
    evidence = _load_filtered_evidence(options)
    contributions = MarginalContributionEngine().analyze(evidence)
    ablations = MatchedAblationEngine().analyze(_trl_ablations())
    overlaps = IndicatorOverlapEngine().analyze(evidence)
    stabilities = ContributionStabilityEngine().analyze(evidence, contributions)
    confidences = ContributionConfidenceEngine().assess(
        evidence, contributions, stabilities
    )
    proposal = AdaptiveWeightProposalEngine().propose(
        contributions,
        stabilities,
        confidences,
        overlaps,
        ablations=ablations,
        evidence_count=len(evidence),
    )
    conditional = ConditionalWeightResearchEngine().build(
        evidence,
        universal=proposal.proposed,
    )
    return _Bundle(
        evidence=evidence,
        contributions=contributions,
        ablations=ablations,
        overlaps=overlaps,
        stabilities=stabilities,
        confidences=confidences,
        proposal=proposal,
        conditional=conditional,
    )


def _load_filtered_evidence(
    options: _Options,
) -> tuple[CompletedOutcomeEvidence, ...]:
    if options.evidence_path is not None:
        evidence = load_evidence(options.evidence_path)
    else:
        repository = RecommendationLedgerRepository(resolve_ledger_path())
        evidence, _ = CompletedOutcomeEvidenceBuilder().from_performance_ledger(
            repository.load_entries(),
            repository.load_outcomes(),
            partition=EvidencePartition.FORWARD_OBSERVED,
        )
    return filter_evidence(
        evidence,
        partition=options.partition,
        setup=options.setup,
        regime=options.regime,
        sector=options.sector,
        horizon=options.horizon,
        dataset_version=options.dataset_version,
    )


def _trl_ablations() -> tuple[AblationObservation, ...]:
    adapter = TradingViewWeightEvidenceAdapter()
    observations: list[AblationObservation] = []
    for experiment in TradingViewResearchRegistry().load():
        try:
            observations.extend(adapter.to_matched_ablation(experiment))
        except ValueError:
            continue
    return tuple(observations)


def _freeze_policy(
    options: _Options, bundle: _Bundle
) -> tuple[CandidateWeightPolicy, bool]:
    registry = CandidateWeightPolicyRegistry(options.policy_registry)
    evidence_window = _evidence_window(bundle.evidence)
    dataset_version = (
        ",".join(sorted({item.dataset_version for item in bundle.evidence}))
        or "UNAVAILABLE"
    )
    for existing in registry.load():
        if (
            existing.parent_policy == options.baseline_policy
            and existing.evidence_window == evidence_window
            and existing.dataset_version == dataset_version
            and existing.outcome_count == len(bundle.evidence)
            and existing.proposed_weights.weights == bundle.proposal.proposed.weights
        ):
            return existing, False
    policy_id = registry.next_policy_id()
    created_at = datetime.combine(
        max(item.decision_date for item in bundle.evidence), time.min, tzinfo=UTC
    )
    policy = CandidateWeightPolicyFactory().create(
        bundle.proposal,
        policy_id=policy_id,
        parent_policy=options.baseline_policy,
        conditional_weights=bundle.conditional.conditionals,
        evidence_window=evidence_window,
        dataset_version=dataset_version,
        created_at=created_at,
    )
    return policy, registry.register(policy)


def _comparisons(
    evidence: tuple[CompletedOutcomeEvidence, ...],
    *,
    baseline_policy: str,
    candidate_policy: str,
) -> tuple[PolicyComparison, ...]:
    engine = PolicyComparisonEngine()
    rows = []
    for partition in EvidencePartition:
        comparison = engine.compare(
            evidence,
            baseline_policy=baseline_policy,
            candidate_policy=candidate_policy,
            partition=partition,
        )
        if comparison is not None:
            rows.append(comparison)
    return tuple(rows)


def _promotion(
    candidate: str,
    comparisons: tuple[PolicyComparison, ...],
    bundle: _Bundle,
) -> PromotionAssessment:
    if candidate == "UNAVAILABLE":
        return PromotionAssessment(
            candidate_policy=candidate,
            decision=PromotionDecision.MORE_EVIDENCE,
            blockers=("no frozen candidate policy",),
            supporting_evidence=(),
            required_next_step=(
                "freeze a research candidate after completed evidence exists"
            ),
        )
    return CandidateWeightPromotionEngine().assess(
        candidate,
        comparisons,
        bundle.stabilities,
        bundle.overlaps,
        bundle.proposal.decisions,
    )


def _candidate_id(options: _Options) -> str:
    if options.candidate_policy:
        return options.candidate_policy
    policies = CandidateWeightPolicyRegistry(options.policy_registry).load()
    return policies[-1].policy_id if policies else "UNAVAILABLE"


def _evidence_window(evidence: tuple[CompletedOutcomeEvidence, ...]) -> str:
    if not evidence:
        return "EMPTY"
    dates = [item.decision_date for item in evidence]
    return f"{min(dates).isoformat()}..{max(dates).isoformat()}"


def _emit(
    options: _Options,
    text: str,
    payload: object,
    rows: tuple[object, ...],
) -> None:
    if options.json_output:
        rendered = json.dumps(to_primitive(payload), indent=2, sort_keys=True) + "\n"
        _write_or_echo(options.output, rendered)
        return
    if options.csv_output:
        if options.output is None:
            raise typer.BadParameter("--csv requires --output")
        write_csv(options.output, rows)
        typer.echo(f"CSV: {options.output}")
        return
    _write_or_echo(options.output, text)


def _write_or_echo(path: Path | None, text: str) -> None:
    if path is None:
        typer.echo(text, nl=False)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    typer.echo(f"Written: {path}")


def _options(context: typer.Context) -> _Options:
    if not isinstance(context.obj, _Options):
        raise RuntimeError("adaptive-weight CLI options were not initialized")
    return context.obj


__all__ = ["adaptive_weights_app"]
