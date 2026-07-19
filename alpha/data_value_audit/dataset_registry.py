"""Permanent candidate registry for the Data Value and ROI Audit."""

# ruff: noqa: E501

from __future__ import annotations

from alpha.data_value_audit.models import (
    DatasetCandidate,
    DatasetDomain,
    DecisionDimension,
    DimensionImpact,
    ImpactLevel,
    NoveltyClass,
    ReplayImpact,
    ReplayMetric,
    Subsystem,
)

FEATURE_EVIDENCE = "docs/POINT_IN_TIME_FEATURE_ATTRIBUTION.md"
OPPORTUNITY_EVIDENCE = "docs/MARKET_OPPORTUNITY_TRUTH_AUDIT.md"
GATE_EVIDENCE = "docs/INSTITUTIONAL_GATE_TRUTH_AUDIT.md"
PROCUREMENT_EVIDENCE = "docs/hmdpca/executive_report.md"
IMPACT_EVIDENCE = "docs/hmdpca/warehouse_impact.md"


def default_dataset_registry() -> tuple[DatasetCandidate, ...]:
    """Return every governed DVRA candidate in stable identifier order."""

    candidates = (
        _candidate(
            "official_nse_daily_history",
            "Official NSE Daily History",
            DatasetDomain.MARKET_DATA,
            NoveltyClass.RECONCILES_CORE_TRUTH,
            ImpactLevel.HIGH,
            ImpactLevel.HIGH,
            ImpactLevel.MEDIUM,
            ImpactLevel.HIGH,
            "Replaces provisional price-volume observations with authoritative daily truth.",
            high=(DecisionDimension.CANDIDATE_QUALITY, DecisionDimension.TRADE_QUALITY),
            medium=(
                DecisionDimension.APPROVAL_QUALITY,
                DecisionDimension.OPPORTUNITY_RECALL,
            ),
            subsystems=_core_subsystems(),
            replay_high=(ReplayMetric.CAGR, ReplayMetric.DRAWDOWN, ReplayMetric.SHARPE),
            replay_medium=(
                ReplayMetric.OPPORTUNITY_CAPTURE,
                ReplayMetric.CANDIDATE_RECALL,
            ),
            unlocks=(
                "canonical_price_history",
                "official_reconciliation",
                "certified_replay",
            ),
        ),
        _candidate(
            "official_bse_daily_history",
            "Official BSE Daily History",
            DatasetDomain.MARKET_DATA,
            NoveltyClass.RECONCILES_CORE_TRUTH,
            ImpactLevel.MEDIUM,
            ImpactLevel.HIGH,
            ImpactLevel.MEDIUM,
            ImpactLevel.MEDIUM,
            "Adds BSE-only observations and an independent exchange reconciliation source.",
            medium=(
                DecisionDimension.CANDIDATE_QUALITY,
                DecisionDimension.OPPORTUNITY_RECALL,
            ),
            low=(
                DecisionDimension.TRADE_QUALITY,
                DecisionDimension.PORTFOLIO_CONSTRUCTION,
            ),
            subsystems=(
                Subsystem.REPLAY,
                Subsystem.MARKET_OPPORTUNITY,
                Subsystem.DATA_PLATFORM,
            ),
            replay_medium=(
                ReplayMetric.OPPORTUNITY_CAPTURE,
                ReplayMetric.CANDIDATE_RECALL,
            ),
            replay_low=(ReplayMetric.CAGR, ReplayMetric.DRAWDOWN),
            dependencies=("official_nse_daily_history", "security_master"),
            unlocks=("cross_exchange_reconciliation", "bse_only_coverage"),
        ),
        _candidate(
            "corporate_actions",
            "Corporate Actions",
            DatasetDomain.CORPORATE_ACTION,
            NoveltyClass.RECONCILES_CORE_TRUTH,
            ImpactLevel.HIGH,
            ImpactLevel.HIGH,
            ImpactLevel.HIGH,
            ImpactLevel.HIGH,
            "Corrects price continuity, entitlement events and issuer lineage across replay.",
            high=(DecisionDimension.CANDIDATE_QUALITY, DecisionDimension.TRADE_QUALITY),
            medium=(
                DecisionDimension.APPROVAL_QUALITY,
                DecisionDimension.CAPITAL_ALLOCATION,
            ),
            subsystems=_core_subsystems() + (Subsystem.PERFORMANCE,),
            replay_high=(ReplayMetric.CAGR, ReplayMetric.DRAWDOWN, ReplayMetric.SHARPE),
            replay_medium=(
                ReplayMetric.OPPORTUNITY_CAPTURE,
                ReplayMetric.APPROVAL_RECALL,
            ),
            dependencies=("security_master", "isin_history"),
            unlocks=(
                "adjusted_price_continuity",
                "lineage_safe_replay",
                "valid_performance",
            ),
        ),
        *_corporate_action_components(),
        _candidate(
            "security_master",
            "Security Master",
            DatasetDomain.IDENTITY,
            NoveltyClass.RECONCILES_CORE_TRUTH,
            ImpactLevel.HIGH,
            ImpactLevel.HIGH,
            ImpactLevel.HIGH,
            ImpactLevel.MEDIUM,
            "Creates durable security identity across symbols, listings and exchanges.",
            high=(
                DecisionDimension.OPPORTUNITY_RECALL,
                DecisionDimension.PORTFOLIO_CONSTRUCTION,
            ),
            medium=(
                DecisionDimension.CANDIDATE_QUALITY,
                DecisionDimension.CAPITAL_ALLOCATION,
            ),
            subsystems=_identity_subsystems(),
            replay_high=(
                ReplayMetric.OPPORTUNITY_CAPTURE,
                ReplayMetric.CANDIDATE_RECALL,
            ),
            replay_medium=(ReplayMetric.CAGR, ReplayMetric.APPROVAL_RECALL),
            unlocks=(
                "identity_resolution",
                "listing_history",
                "corporate_action_lineage",
            ),
        ),
        *_identity_components(),
        _candidate(
            "historical_index_ohlc",
            "Historical Index OHLC",
            DatasetDomain.INDEX,
            NoveltyClass.ADDS_POINT_IN_TIME_CONTEXT,
            ImpactLevel.MEDIUM,
            ImpactLevel.HIGH,
            ImpactLevel.HIGH,
            ImpactLevel.HIGH,
            "Enables benchmark-relative features and point-in-time market context.",
            high=(
                DecisionDimension.APPROVAL_QUALITY,
                DecisionDimension.PORTFOLIO_CONSTRUCTION,
            ),
            medium=(
                DecisionDimension.CANDIDATE_QUALITY,
                DecisionDimension.CAPITAL_ALLOCATION,
            ),
            subsystems=(
                Subsystem.REPLAY,
                Subsystem.FEATURE_ATTRIBUTION,
                Subsystem.MARKET_REGIME,
                Subsystem.PORTFOLIO,
                Subsystem.STRATEGY_LAB,
            ),
            replay_high=(ReplayMetric.SHARPE,),
            replay_medium=(
                ReplayMetric.CAGR,
                ReplayMetric.DRAWDOWN,
                ReplayMetric.APPROVAL_RECALL,
            ),
            dependencies=("trading_calendar",),
            unlocks=("benchmark_comparison", "relative_strength", "market_regime"),
        ),
        _candidate(
            "historical_index_membership",
            "Historical Index Membership",
            DatasetDomain.INDEX,
            NoveltyClass.ADDS_POINT_IN_TIME_CONTEXT,
            ImpactLevel.HIGH,
            ImpactLevel.HIGH,
            ImpactLevel.HIGH,
            ImpactLevel.MEDIUM,
            "Eliminates current-constituent leakage and defines point-in-time index populations.",
            high=(
                DecisionDimension.OPPORTUNITY_RECALL,
                DecisionDimension.PORTFOLIO_CONSTRUCTION,
            ),
            medium=(
                DecisionDimension.APPROVAL_QUALITY,
                DecisionDimension.CAPITAL_ALLOCATION,
            ),
            subsystems=(
                Subsystem.POINT_IN_TIME_UNIVERSE,
                Subsystem.REPLAY,
                Subsystem.FEATURE_ATTRIBUTION,
                Subsystem.MARKET_REGIME,
                Subsystem.PORTFOLIO,
                Subsystem.MARKET_OPPORTUNITY,
            ),
            replay_high=(
                ReplayMetric.OPPORTUNITY_CAPTURE,
                ReplayMetric.CANDIDATE_RECALL,
            ),
            replay_medium=(ReplayMetric.CAGR, ReplayMetric.SHARPE),
            dependencies=("security_master", "listing_history"),
            unlocks=(
                "index_replay",
                "survivorship_safe_membership",
                "membership_attribution",
            ),
        ),
        _candidate(
            "delivery_data",
            "Delivery Data",
            DatasetDomain.DELIVERY,
            NoveltyClass.ADDS_NEW_FEATURE,
            ImpactLevel.MEDIUM,
            ImpactLevel.HIGH,
            ImpactLevel.MEDIUM,
            ImpactLevel.HIGH,
            "Adds observed delivery participation unavailable in the legacy warehouse.",
            high=(
                DecisionDimension.CANDIDATE_QUALITY,
                DecisionDimension.APPROVAL_QUALITY,
            ),
            medium=(
                DecisionDimension.TRADE_QUALITY,
                DecisionDimension.OPPORTUNITY_RECALL,
            ),
            subsystems=(
                Subsystem.FEATURE_ATTRIBUTION,
                Subsystem.CANDIDATE_GENERATION,
                Subsystem.GATE_TRUTH,
                Subsystem.MARKET_DNA,
                Subsystem.STRATEGY_LAB,
                Subsystem.LEARNING,
            ),
            replay_medium=(
                ReplayMetric.OPPORTUNITY_CAPTURE,
                ReplayMetric.CANDIDATE_RECALL,
                ReplayMetric.APPROVAL_RECALL,
            ),
            replay_unknown=(
                ReplayMetric.CAGR,
                ReplayMetric.DRAWDOWN,
                ReplayMetric.SHARPE,
            ),
            dependencies=("official_nse_daily_history", "security_master"),
            unlocks=(
                "delivery_quantity",
                "delivery_percentage",
                "participation_features",
            ),
        ),
        *_delivery_components(),
        _candidate(
            "ownership_data",
            "Ownership Data",
            DatasetDomain.OWNERSHIP,
            NoveltyClass.ADDS_POINT_IN_TIME_CONTEXT,
            ImpactLevel.MEDIUM,
            ImpactLevel.HIGH,
            ImpactLevel.HIGH,
            ImpactLevel.MEDIUM,
            "Adds point-in-time holder composition absent from current features.",
            medium=(
                DecisionDimension.APPROVAL_QUALITY,
                DecisionDimension.PORTFOLIO_CONSTRUCTION,
            ),
            low=(
                DecisionDimension.CANDIDATE_QUALITY,
                DecisionDimension.CAPITAL_ALLOCATION,
            ),
            subsystems=(
                Subsystem.FEATURE_ATTRIBUTION,
                Subsystem.GATE_TRUTH,
                Subsystem.MARKET_DNA,
                Subsystem.LEARNING,
                Subsystem.PORTFOLIO,
            ),
            replay_medium=(ReplayMetric.APPROVAL_RECALL,),
            replay_unknown=(
                ReplayMetric.CAGR,
                ReplayMetric.DRAWDOWN,
                ReplayMetric.SHARPE,
                ReplayMetric.OPPORTUNITY_CAPTURE,
            ),
            dependencies=("security_master", "isin_history"),
            unlocks=(
                "promoter_holdings",
                "fii_holdings",
                "dii_holdings",
                "mutual_fund_holdings",
            ),
        ),
        *_ownership_components(),
        _candidate(
            "earnings_data",
            "Earnings Data",
            DatasetDomain.EARNINGS,
            NoveltyClass.ADDS_NEW_FEATURE,
            ImpactLevel.MEDIUM,
            ImpactLevel.HIGH,
            ImpactLevel.HIGH,
            ImpactLevel.MEDIUM,
            "Adds issuer fundamentals and event context not represented by technical features.",
            medium=(
                DecisionDimension.APPROVAL_QUALITY,
                DecisionDimension.TRADE_QUALITY,
            ),
            low=(
                DecisionDimension.CANDIDATE_QUALITY,
                DecisionDimension.PORTFOLIO_CONSTRUCTION,
            ),
            subsystems=(
                Subsystem.FEATURE_ATTRIBUTION,
                Subsystem.GATE_TRUTH,
                Subsystem.MARKET_DNA,
                Subsystem.STRATEGY_LAB,
                Subsystem.LEARNING,
            ),
            replay_medium=(ReplayMetric.APPROVAL_RECALL,),
            replay_unknown=(
                ReplayMetric.CAGR,
                ReplayMetric.DRAWDOWN,
                ReplayMetric.SHARPE,
                ReplayMetric.OPPORTUNITY_CAPTURE,
            ),
            dependencies=("security_master", "isin_history"),
            unlocks=("earnings_dates", "earnings_revisions", "earnings_surprises"),
        ),
        *_earnings_components(),
        _candidate(
            "market_breadth",
            "Market Breadth",
            DatasetDomain.MARKET_CONTEXT,
            NoveltyClass.ADDS_NEW_FEATURE,
            ImpactLevel.MEDIUM,
            ImpactLevel.HIGH,
            ImpactLevel.HIGH,
            ImpactLevel.HIGH,
            "Adds market-wide participation context currently unavailable to regime and timing research.",
            high=(
                DecisionDimension.APPROVAL_QUALITY,
                DecisionDimension.CAPITAL_ALLOCATION,
            ),
            medium=(
                DecisionDimension.CANDIDATE_QUALITY,
                DecisionDimension.PORTFOLIO_CONSTRUCTION,
            ),
            subsystems=(
                Subsystem.MARKET_REGIME,
                Subsystem.FEATURE_ATTRIBUTION,
                Subsystem.GATE_TRUTH,
                Subsystem.CANDIDATE_GENERATION,
                Subsystem.PORTFOLIO,
                Subsystem.STRATEGY_LAB,
            ),
            replay_medium=(
                ReplayMetric.DRAWDOWN,
                ReplayMetric.SHARPE,
                ReplayMetric.APPROVAL_RECALL,
            ),
            replay_unknown=(ReplayMetric.CAGR, ReplayMetric.OPPORTUNITY_CAPTURE),
            dependencies=(
                "official_nse_daily_history",
                "security_master",
                "point_in_time_universe",
            ),
            unlocks=("breadth_regime", "participation_divergence"),
        ),
        _candidate(
            "india_vix",
            "India VIX",
            DatasetDomain.MARKET_CONTEXT,
            NoveltyClass.ADDS_NEW_FEATURE,
            ImpactLevel.LOW,
            ImpactLevel.HIGH,
            ImpactLevel.HIGH,
            ImpactLevel.MEDIUM,
            "Adds an official market volatility context series.",
            medium=(
                DecisionDimension.APPROVAL_QUALITY,
                DecisionDimension.CAPITAL_ALLOCATION,
            ),
            low=(
                DecisionDimension.TRADE_QUALITY,
                DecisionDimension.PORTFOLIO_CONSTRUCTION,
            ),
            subsystems=(
                Subsystem.MARKET_REGIME,
                Subsystem.GATE_TRUTH,
                Subsystem.PORTFOLIO,
                Subsystem.STRATEGY_LAB,
            ),
            replay_medium=(ReplayMetric.DRAWDOWN, ReplayMetric.SHARPE),
            replay_unknown=(ReplayMetric.CAGR, ReplayMetric.OPPORTUNITY_CAPTURE),
            unlocks=("volatility_regime",),
        ),
        _candidate(
            "risk_free_rate",
            "Risk-free Rate",
            DatasetDomain.MARKET_CONTEXT,
            NoveltyClass.REFINES_EXISTING_FEATURE,
            ImpactLevel.LOW,
            ImpactLevel.HIGH,
            ImpactLevel.HIGH,
            ImpactLevel.LOW,
            "Replaces zero-rate assumptions in risk-adjusted performance calculations.",
            low=(
                DecisionDimension.CAPITAL_ALLOCATION,
                DecisionDimension.PORTFOLIO_CONSTRUCTION,
            ),
            subsystems=(Subsystem.REPLAY, Subsystem.PERFORMANCE, Subsystem.PORTFOLIO),
            replay_low=(ReplayMetric.CAGR,),
            replay_medium=(ReplayMetric.SHARPE,),
            unlocks=("risk_adjusted_metrics",),
        ),
        _candidate(
            "trading_calendar",
            "Official Trading Calendar",
            DatasetDomain.MARKET_CONTEXT,
            NoveltyClass.RECONCILES_CORE_TRUTH,
            ImpactLevel.MEDIUM,
            ImpactLevel.HIGH,
            ImpactLevel.HIGH,
            ImpactLevel.LOW,
            "Distinguishes missing observations from non-trading sessions.",
            medium=(DecisionDimension.OPPORTUNITY_RECALL,),
            low=(DecisionDimension.CANDIDATE_QUALITY, DecisionDimension.TRADE_QUALITY),
            subsystems=(
                Subsystem.REPLAY,
                Subsystem.DATA_PLATFORM,
                Subsystem.POINT_IN_TIME_UNIVERSE,
                Subsystem.PERFORMANCE,
            ),
            replay_medium=(
                ReplayMetric.OPPORTUNITY_CAPTURE,
                ReplayMetric.CANDIDATE_RECALL,
            ),
            replay_low=(ReplayMetric.CAGR,),
            unlocks=("session_completeness", "missing_day_detection"),
        ),
        _candidate(
            "historical_sector_membership",
            "Historical Sector Membership",
            DatasetDomain.INDEX,
            NoveltyClass.ADDS_POINT_IN_TIME_CONTEXT,
            ImpactLevel.HIGH,
            ImpactLevel.HIGH,
            ImpactLevel.HIGH,
            ImpactLevel.MEDIUM,
            "Eliminates current-sector backfill and enables sector-stability attribution.",
            high=(DecisionDimension.PORTFOLIO_CONSTRUCTION,),
            medium=(
                DecisionDimension.APPROVAL_QUALITY,
                DecisionDimension.CAPITAL_ALLOCATION,
            ),
            subsystems=(
                Subsystem.POINT_IN_TIME_UNIVERSE,
                Subsystem.FEATURE_ATTRIBUTION,
                Subsystem.MARKET_REGIME,
                Subsystem.PORTFOLIO,
                Subsystem.MARKET_DNA,
            ),
            replay_medium=(
                ReplayMetric.DRAWDOWN,
                ReplayMetric.SHARPE,
                ReplayMetric.APPROVAL_RECALL,
            ),
            replay_unknown=(ReplayMetric.CAGR,),
            dependencies=("security_master", "historical_index_membership"),
            unlocks=("sector_stability", "point_in_time_sector_limits"),
        ),
        _candidate(
            "turnover_trade_count",
            "Turnover and Trade Count",
            DatasetDomain.MARKET_DATA,
            NoveltyClass.REFINES_EXISTING_FEATURE,
            ImpactLevel.LOW,
            ImpactLevel.HIGH,
            ImpactLevel.MEDIUM,
            ImpactLevel.MEDIUM,
            "Adds liquidity and capacity observations beyond raw volume.",
            medium=(
                DecisionDimension.CAPITAL_ALLOCATION,
                DecisionDimension.PORTFOLIO_CONSTRUCTION,
            ),
            low=(
                DecisionDimension.CANDIDATE_QUALITY,
                DecisionDimension.APPROVAL_QUALITY,
            ),
            subsystems=(
                Subsystem.GATE_TRUTH,
                Subsystem.PORTFOLIO,
                Subsystem.CANDIDATE_GENERATION,
                Subsystem.REPLAY,
            ),
            replay_medium=(ReplayMetric.DRAWDOWN,),
            replay_low=(ReplayMetric.SHARPE, ReplayMetric.APPROVAL_RECALL),
            dependencies=("official_nse_daily_history", "security_master"),
            unlocks=("liquidity_capacity",),
        ),
    )
    ordered = tuple(sorted(candidates, key=lambda item: item.dataset_id))
    ids = tuple(item.dataset_id for item in ordered)
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate DVRA dataset id")
    return ordered


def _candidate(
    dataset_id: str,
    name: str,
    domain: DatasetDomain,
    novelty: NoveltyClass,
    bias_control: ImpactLevel,
    authority: ImpactLevel,
    point_in_time_value: ImpactLevel,
    direct_feature_value: ImpactLevel,
    gap: str,
    *,
    high: tuple[DecisionDimension, ...] = (),
    medium: tuple[DecisionDimension, ...] = (),
    low: tuple[DecisionDimension, ...] = (),
    subsystems: tuple[Subsystem, ...],
    replay_high: tuple[ReplayMetric, ...] = (),
    replay_medium: tuple[ReplayMetric, ...] = (),
    replay_low: tuple[ReplayMetric, ...] = (),
    replay_unknown: tuple[ReplayMetric, ...] = (),
    dependencies: tuple[str, ...] = (),
    unlocks: tuple[str, ...] = (),
    package_parent: str | None = None,
) -> DatasetCandidate:
    impacts = tuple(
        DimensionImpact(dimension, level, _decision_reason(name, dimension, level))
        for level, dimensions in (
            (ImpactLevel.HIGH, high),
            (ImpactLevel.MEDIUM, medium),
            (ImpactLevel.LOW, low),
        )
        for dimension in dimensions
    )
    replays = tuple(
        ReplayImpact(metric, level, _replay_reason(name, metric, level))
        for level, metrics in (
            (ImpactLevel.HIGH, replay_high),
            (ImpactLevel.MEDIUM, replay_medium),
            (ImpactLevel.LOW, replay_low),
            (ImpactLevel.UNKNOWN, replay_unknown),
        )
        for metric in metrics
    )
    return DatasetCandidate(
        dataset_id=dataset_id,
        name=name,
        domain=domain,
        novelty=novelty,
        bias_control=bias_control,
        authority=authority,
        point_in_time_value=point_in_time_value,
        direct_feature_value=direct_feature_value,
        evidence_sources=(
            FEATURE_EVIDENCE,
            OPPORTUNITY_EVIDENCE,
            GATE_EVIDENCE,
            PROCUREMENT_EVIDENCE,
            IMPACT_EVIDENCE,
        ),
        feature_gap=gap,
        decision_impacts=impacts,
        subsystems=tuple(dict.fromkeys(subsystems)),
        replay_impacts=replays,
        dependencies=dependencies,
        unlocks=unlocks,
        package_parent=package_parent,
    )


def _corporate_action_components() -> tuple[DatasetCandidate, ...]:
    specs = (
        ("splits", "Splits", ImpactLevel.HIGH, "price and quantity continuity"),
        ("bonuses", "Bonuses", ImpactLevel.HIGH, "price and quantity continuity"),
        ("rights", "Rights", ImpactLevel.MEDIUM, "entitlement-aware return continuity"),
        ("dividends", "Dividends", ImpactLevel.MEDIUM, "total-return accounting"),
        ("mergers", "Mergers", ImpactLevel.HIGH, "issuer and position lineage"),
        ("demergers", "Demergers", ImpactLevel.HIGH, "issuer and entitlement lineage"),
    )
    return tuple(
        _candidate(
            dataset_id,
            name,
            DatasetDomain.CORPORATE_ACTION,
            NoveltyClass.RECONCILES_CORE_TRUTH,
            bias,
            ImpactLevel.HIGH,
            ImpactLevel.HIGH,
            ImpactLevel.MEDIUM,
            f"Adds official {name.lower()} needed for {gap}.",
            high=(DecisionDimension.TRADE_QUALITY,),
            medium=(
                DecisionDimension.CANDIDATE_QUALITY,
                DecisionDimension.CAPITAL_ALLOCATION,
            ),
            subsystems=(
                Subsystem.REPLAY,
                Subsystem.FEATURE_ATTRIBUTION,
                Subsystem.PERFORMANCE,
                Subsystem.LEARNING,
            ),
            replay_high=(ReplayMetric.CAGR,) if bias is ImpactLevel.HIGH else (),
            replay_medium=(ReplayMetric.DRAWDOWN, ReplayMetric.SHARPE),
            dependencies=("security_master", "isin_history"),
            unlocks=(f"{dataset_id}_adjustment",),
            package_parent="corporate_actions",
        )
        for dataset_id, name, bias, gap in specs
    )


def _identity_components() -> tuple[DatasetCandidate, ...]:
    specs = (
        (
            "isin_history",
            "ISIN History",
            ImpactLevel.HIGH,
            "stable cross-source identity",
        ),
        (
            "listing_history",
            "Listing History",
            ImpactLevel.HIGH,
            "exclude pre-listing observations",
        ),
        (
            "delisting_history",
            "Delisting History",
            ImpactLevel.HIGH,
            "include historical failures without survivorship bias",
        ),
        (
            "symbol_history",
            "Symbol History",
            ImpactLevel.HIGH,
            "preserve identity through ticker changes",
        ),
    )
    return tuple(
        _candidate(
            dataset_id,
            name,
            DatasetDomain.IDENTITY,
            NoveltyClass.ADDS_POINT_IN_TIME_CONTEXT,
            bias,
            ImpactLevel.HIGH,
            ImpactLevel.HIGH,
            ImpactLevel.LOW,
            gap.capitalize() + ".",
            high=(DecisionDimension.OPPORTUNITY_RECALL,),
            medium=(
                DecisionDimension.CANDIDATE_QUALITY,
                DecisionDimension.PORTFOLIO_CONSTRUCTION,
            ),
            subsystems=(
                Subsystem.POINT_IN_TIME_UNIVERSE,
                Subsystem.REPLAY,
                Subsystem.MARKET_OPPORTUNITY,
                Subsystem.DATA_PLATFORM,
            ),
            replay_high=(
                ReplayMetric.OPPORTUNITY_CAPTURE,
                ReplayMetric.CANDIDATE_RECALL,
            ),
            replay_medium=(ReplayMetric.CAGR,),
            dependencies=("security_master",) if dataset_id != "isin_history" else (),
            unlocks=(dataset_id.replace("_history", "_continuity"),),
            package_parent="security_master",
        )
        for dataset_id, name, bias, gap in specs
    )


def _delivery_components() -> tuple[DatasetCandidate, ...]:
    return tuple(
        _candidate(
            dataset_id,
            name,
            DatasetDomain.DELIVERY,
            NoveltyClass.ADDS_NEW_FEATURE,
            ImpactLevel.MEDIUM,
            ImpactLevel.HIGH,
            ImpactLevel.MEDIUM,
            ImpactLevel.HIGH,
            gap,
            high=(
                DecisionDimension.CANDIDATE_QUALITY,
                DecisionDimension.APPROVAL_QUALITY,
            ),
            medium=(DecisionDimension.TRADE_QUALITY,),
            subsystems=(
                Subsystem.FEATURE_ATTRIBUTION,
                Subsystem.CANDIDATE_GENERATION,
                Subsystem.GATE_TRUTH,
                Subsystem.MARKET_DNA,
                Subsystem.STRATEGY_LAB,
            ),
            replay_medium=(ReplayMetric.CANDIDATE_RECALL, ReplayMetric.APPROVAL_RECALL),
            replay_unknown=(ReplayMetric.CAGR, ReplayMetric.SHARPE),
            dependencies=("delivery_data",),
            package_parent="delivery_data",
        )
        for dataset_id, name, gap in (
            (
                "delivery_quantity",
                "Delivery Quantity",
                "Separates delivered quantity from total turnover.",
            ),
            (
                "delivery_percentage",
                "Delivery Percentage",
                "Adds a normalized participation feature explicitly absent from attribution.",
            ),
        )
    )


def _ownership_components() -> tuple[DatasetCandidate, ...]:
    return tuple(
        _candidate(
            dataset_id,
            name,
            DatasetDomain.OWNERSHIP,
            NoveltyClass.ADDS_POINT_IN_TIME_CONTEXT,
            ImpactLevel.MEDIUM,
            ImpactLevel.HIGH,
            ImpactLevel.HIGH,
            ImpactLevel.MEDIUM,
            f"Adds point-in-time {name.lower()} unavailable in the canonical feature history.",
            medium=(
                DecisionDimension.APPROVAL_QUALITY,
                DecisionDimension.PORTFOLIO_CONSTRUCTION,
            ),
            low=(DecisionDimension.CANDIDATE_QUALITY,),
            subsystems=(
                Subsystem.FEATURE_ATTRIBUTION,
                Subsystem.GATE_TRUTH,
                Subsystem.MARKET_DNA,
                Subsystem.LEARNING,
            ),
            replay_medium=(ReplayMetric.APPROVAL_RECALL,),
            replay_unknown=(ReplayMetric.CAGR, ReplayMetric.SHARPE),
            dependencies=("ownership_data",),
            package_parent="ownership_data",
        )
        for dataset_id, name in (
            ("promoter_holdings", "Promoter Holdings"),
            ("fii_holdings", "FII Holdings"),
            ("dii_holdings", "DII Holdings"),
            ("mutual_fund_holdings", "Mutual Fund Holdings"),
        )
    )


def _earnings_components() -> tuple[DatasetCandidate, ...]:
    specs = (
        (
            "earnings_dates",
            "Earnings Dates",
            ImpactLevel.HIGH,
            "event timing and gap-risk controls",
        ),
        (
            "earnings_revisions",
            "Earnings Revisions",
            ImpactLevel.MEDIUM,
            "forward change in analyst expectations",
        ),
        (
            "earnings_surprises",
            "Earnings Surprises",
            ImpactLevel.MEDIUM,
            "point-in-time actual-versus-expectation context",
        ),
    )
    return tuple(
        _candidate(
            dataset_id,
            name,
            DatasetDomain.EARNINGS,
            NoveltyClass.ADDS_NEW_FEATURE,
            ImpactLevel.MEDIUM,
            ImpactLevel.HIGH if dataset_id == "earnings_dates" else ImpactLevel.MEDIUM,
            point_in_time,
            ImpactLevel.MEDIUM,
            f"Adds {gap} absent from technical-only evidence.",
            medium=(
                DecisionDimension.APPROVAL_QUALITY,
                DecisionDimension.TRADE_QUALITY,
            ),
            low=(DecisionDimension.CANDIDATE_QUALITY,),
            subsystems=(
                Subsystem.FEATURE_ATTRIBUTION,
                Subsystem.GATE_TRUTH,
                Subsystem.STRATEGY_LAB,
                Subsystem.LEARNING,
            ),
            replay_medium=(ReplayMetric.APPROVAL_RECALL,),
            replay_unknown=(ReplayMetric.CAGR, ReplayMetric.DRAWDOWN),
            dependencies=("earnings_data",),
            package_parent="earnings_data",
        )
        for dataset_id, name, point_in_time, gap in specs
    )


def _core_subsystems() -> tuple[Subsystem, ...]:
    return (
        Subsystem.REPLAY,
        Subsystem.FEATURE_ATTRIBUTION,
        Subsystem.CANDIDATE_GENERATION,
        Subsystem.GATE_TRUTH,
        Subsystem.MARKET_OPPORTUNITY,
        Subsystem.MARKET_DNA,
        Subsystem.STRATEGY_LAB,
        Subsystem.LEARNING,
        Subsystem.PORTFOLIO,
    )


def _identity_subsystems() -> tuple[Subsystem, ...]:
    return (
        Subsystem.POINT_IN_TIME_UNIVERSE,
        Subsystem.REPLAY,
        Subsystem.FEATURE_ATTRIBUTION,
        Subsystem.MARKET_OPPORTUNITY,
        Subsystem.LEARNING,
        Subsystem.PORTFOLIO,
        Subsystem.DATA_PLATFORM,
    )


def _decision_reason(
    name: str, dimension: DecisionDimension, level: ImpactLevel
) -> str:
    return f"{name} has {level.value.lower()} expected influence on {dimension.value.lower().replace('_', ' ')}; no performance uplift is asserted."


def _replay_reason(name: str, metric: ReplayMetric, level: ImpactLevel) -> str:
    return f"{name} has {level.value.lower()} expected measurement influence on {metric.value}; no numeric replay improvement is estimated."


__all__ = ["default_dataset_registry"]
