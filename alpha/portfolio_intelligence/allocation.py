from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from types import MappingProxyType

_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")
_FOUR_PLACES = Decimal("0.0001")
_TWO_PLACES = Decimal("0.01")


class AllocationDecision(StrEnum):
    ALLOCATE = "ALLOCATE"
    REDUCE = "REDUCE"
    SKIP = "SKIP"


class AllocationConstraint(StrEnum):
    CASH_LIMIT = "CASH_LIMIT"
    POSITION_LIMIT = "POSITION_LIMIT"
    SECTOR_LIMIT = "SECTOR_LIMIT"
    CORRELATION_LIMIT = "CORRELATION_LIMIT"
    RISK_BUDGET = "RISK_BUDGET"
    LOW_CONVICTION = "LOW_CONVICTION"


class AllocationReasonCode(StrEnum):
    POSITION_SIZE_CAP = "POSITION_SIZE_CAP"
    VOLATILITY_ADJUSTMENT = "VOLATILITY_ADJUSTMENT"
    CONCENTRATION_CONTROL = "CONCENTRATION_CONTROL"
    CASH_RESERVE_RULE = "CASH_RESERVE_RULE"
    CONFIDENCE_ADJUSTMENT = "CONFIDENCE_ADJUSTMENT"
    WATCHLIST_NOT_DEPLOYABLE = "WATCHLIST_NOT_DEPLOYABLE"
    NOT_ACTIONABLE = "NOT_ACTIONABLE"
    EXIT_SIGNAL = "EXIT_SIGNAL"
    POLICY_SKIP = "POLICY_SKIP"


class AllocationConviction(StrEnum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    WATCHLIST = "WATCHLIST"
    HOLD = "HOLD"
    AVOID = "AVOID"

    @property
    def is_allocation_eligible(self) -> bool:
        return self in {
            AllocationConviction.STRONG_BUY,
            AllocationConviction.BUY,
            AllocationConviction.WATCHLIST,
        }

    @property
    def requires_reduced_allocation(self) -> bool:
        return self is AllocationConviction.WATCHLIST


def _bounded_weight(value: Decimal, label: str) -> Decimal:
    normalized = Decimal(str(value))
    if normalized < _ZERO or normalized > _ONE:
        raise ValueError(f"{label} must be between 0 and 1")
    return normalized


def _bounded_score_100(value: Decimal, label: str) -> Decimal:
    normalized = Decimal(str(value))
    if normalized < _ZERO or normalized > _HUNDRED:
        raise ValueError(f"{label} must be between 0 and 100")
    return normalized


def _quantize(value: Decimal) -> Decimal:
    return Decimal(str(value)).quantize(_FOUR_PLACES, rounding=ROUND_HALF_UP)


def _quantize_money(value: Decimal) -> Decimal:
    return Decimal(str(value)).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def _as_percent(value: Decimal) -> str:
    percent = Decimal(str(value)) * _HUNDRED
    return f"{percent.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)}%"


def _reward_to_risk(
    *,
    expected_return: Decimal,
    expected_drawdown: Decimal,
) -> Decimal:
    if expected_drawdown <= _ZERO:
        if expected_return <= _ZERO:
            return _ZERO
        return Decimal("5")

    return max(expected_return / expected_drawdown, _ZERO)


def _weighted_average(values: Iterable[tuple[Decimal, Decimal]]) -> Decimal:
    pairs = tuple(values)
    total_weight = sum((weight for _, weight in pairs), _ZERO)
    if total_weight <= _ZERO:
        return _ZERO
    return sum((value * weight for value, weight in pairs), _ZERO) / total_weight


def _conviction_from_score(score: Decimal) -> AllocationConviction:
    normalized = _bounded_score_100(score, "recommendation score")
    if normalized >= Decimal("90"):
        return AllocationConviction.STRONG_BUY
    if normalized >= Decimal("80"):
        return AllocationConviction.BUY
    if normalized >= Decimal("50"):
        return AllocationConviction.WATCHLIST
    if normalized >= Decimal("40"):
        return AllocationConviction.HOLD
    return AllocationConviction.AVOID


@dataclass(frozen=True, slots=True)
class SectorExposure:
    sector: str
    current_weight: Decimal

    def __post_init__(self) -> None:
        sector = self.sector.strip().upper()
        if not sector:
            raise ValueError("sector cannot be empty")

        object.__setattr__(self, "sector", sector)
        object.__setattr__(
            self,
            "current_weight",
            _bounded_weight(self.current_weight, "sector current weight"),
        )


@dataclass(frozen=True, slots=True)
class RiskBudget:
    max_position_weight: Decimal = Decimal("0.10")
    max_sector_weight: Decimal = Decimal("0.30")
    max_correlation: Decimal = Decimal("0.75")
    max_portfolio_risk_weight: Decimal = Decimal("0.35")
    min_recommendation_score: Decimal = Decimal("50")

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_position_weight",
            _bounded_weight(self.max_position_weight, "max position weight"),
        )
        object.__setattr__(
            self,
            "max_sector_weight",
            _bounded_weight(self.max_sector_weight, "max sector weight"),
        )
        object.__setattr__(
            self,
            "max_correlation",
            _bounded_weight(self.max_correlation, "max correlation"),
        )
        object.__setattr__(
            self,
            "max_portfolio_risk_weight",
            _bounded_weight(
                self.max_portfolio_risk_weight,
                "max portfolio risk weight",
            ),
        )
        object.__setattr__(
            self,
            "min_recommendation_score",
            _bounded_score_100(
                self.min_recommendation_score,
                "min recommendation score",
            ),
        )


@dataclass(frozen=True, slots=True)
class PortfolioContext:
    total_capital: Decimal
    available_cash: Decimal
    current_positions: Mapping[str, Decimal] = field(
        default_factory=lambda: MappingProxyType({})
    )
    sector_exposures: tuple[SectorExposure, ...] = ()
    risk_budget: RiskBudget = field(default_factory=RiskBudget)

    def __post_init__(self) -> None:
        total_capital = Decimal(str(self.total_capital))
        available_cash = Decimal(str(self.available_cash))

        if total_capital <= _ZERO:
            raise ValueError("total capital must be positive")
        if available_cash < _ZERO:
            raise ValueError("available cash cannot be negative")
        if available_cash > total_capital:
            raise ValueError("available cash cannot exceed total capital")

        positions: dict[str, Decimal] = {}
        for symbol, weight in self.current_positions.items():
            normalized_symbol = symbol.strip().upper()
            if not normalized_symbol:
                raise ValueError("position symbol cannot be empty")
            positions[normalized_symbol] = _bounded_weight(
                weight,
                "current position weight",
            )

        object.__setattr__(self, "total_capital", total_capital)
        object.__setattr__(self, "available_cash", available_cash)
        object.__setattr__(
            self,
            "current_positions",
            MappingProxyType(dict(sorted(positions.items()))),
        )
        object.__setattr__(
            self,
            "sector_exposures",
            tuple(sorted(self.sector_exposures, key=lambda item: item.sector)),
        )

    @property
    def cash_weight(self) -> Decimal:
        return _quantize(self.available_cash / self.total_capital)

    def sector_weight(self, sector: str) -> Decimal:
        normalized_sector = sector.strip().upper()
        if not normalized_sector:
            raise ValueError("sector cannot be empty")

        for exposure in self.sector_exposures:
            if exposure.sector == normalized_sector:
                return exposure.current_weight

        return _ZERO

    def current_position_weight(self, symbol: str) -> Decimal:
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol cannot be empty")
        return self.current_positions.get(normalized_symbol, _ZERO)


@dataclass(frozen=True, slots=True)
class AllocationCandidate:
    symbol: str
    sector: str
    observed_on: date
    recommendation_score: Decimal
    success_probability: Decimal
    expected_return: Decimal
    expected_drawdown: Decimal
    correlation_to_portfolio: Decimal
    liquidity_score: Decimal
    conviction_score: Decimal
    metadata: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    recommendation_action: str = "BUY"
    final_signal: str | None = None

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        sector = self.sector.strip().upper()
        recommendation_action = self.recommendation_action.strip().upper()
        final_signal = (
            self.final_signal.strip().upper() if self.final_signal is not None else None
        )

        if not symbol:
            raise ValueError("candidate symbol cannot be empty")
        if not sector:
            raise ValueError("candidate sector cannot be empty")
        if not recommendation_action:
            raise ValueError("candidate recommendation action cannot be empty")
        if final_signal == "":
            raise ValueError("candidate final signal cannot be empty")

        metadata = MappingProxyType(
            dict(
                sorted(
                    (key.strip(), value.strip()) for key, value in self.metadata.items()
                )
            )
        )
        if any(not key or not value for key, value in metadata.items()):
            raise ValueError("candidate metadata keys and values cannot be empty")

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "sector", sector)
        object.__setattr__(
            self,
            "recommendation_score",
            _bounded_score_100(
                self.recommendation_score,
                "recommendation score",
            ),
        )
        object.__setattr__(
            self,
            "success_probability",
            _bounded_weight(self.success_probability, "success probability"),
        )
        object.__setattr__(
            self,
            "expected_return",
            Decimal(str(self.expected_return)),
        )
        object.__setattr__(
            self,
            "expected_drawdown",
            _bounded_weight(self.expected_drawdown, "expected drawdown"),
        )
        object.__setattr__(
            self,
            "correlation_to_portfolio",
            _bounded_weight(
                self.correlation_to_portfolio,
                "correlation to portfolio",
            ),
        )
        object.__setattr__(
            self,
            "liquidity_score",
            _bounded_weight(self.liquidity_score, "liquidity score"),
        )
        object.__setattr__(
            self,
            "conviction_score",
            _bounded_weight(self.conviction_score, "conviction score"),
        )
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(
            self,
            "recommendation_action",
            recommendation_action,
        )
        object.__setattr__(self, "final_signal", final_signal)

    @property
    def recommendation_strength(self) -> Decimal:
        return _quantize(self.recommendation_score / _HUNDRED)

    @property
    def conviction(self) -> AllocationConviction:
        return _conviction_from_score(self.recommendation_score)

    @property
    def is_allocation_eligible(self) -> bool:
        return (
            self.conviction.is_allocation_eligible
            and not self.has_blocked_recommendation_intent
        )

    @property
    def has_blocked_recommendation_intent(self) -> bool:
        blocked = {"AVOID", "SELL", "REJECT"}
        approved_deployment_actions = {"BUY", "ACCUMULATE"}
        trade_plan_valid = self.metadata.get("trade_plan_valid", "True") == "True"
        actionable_strategy_action = self.metadata.get("actionable_strategy_action")
        watchlist_allocation_allowed = (
            self.metadata.get("watchlist_allocation_allowed", "False") == "True"
        )
        return (
            self.recommendation_action not in approved_deployment_actions
            or self.final_signal in blocked
            or (
                actionable_strategy_action is not None
                and actionable_strategy_action != "BUY_NOW"
            )
            or (self.final_signal == "WATCHLIST" and not watchlist_allocation_allowed)
            or not trade_plan_valid
        )


@dataclass(frozen=True, slots=True)
class PositionSizingAssessment:
    symbol: str
    base_weight: Decimal
    probability_weight: Decimal
    reward_risk_weight: Decimal
    liquidity_weight: Decimal
    conviction_weight: Decimal
    suggested_weight: Decimal
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("sizing symbol cannot be empty")

        reasons = _normalized_reasons(self.reasons, "sizing reasons")

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(
            self,
            "base_weight",
            _bounded_weight(self.base_weight, "base weight"),
        )
        object.__setattr__(
            self,
            "probability_weight",
            _bounded_weight(self.probability_weight, "probability weight"),
        )
        object.__setattr__(
            self,
            "reward_risk_weight",
            _bounded_weight(self.reward_risk_weight, "reward risk weight"),
        )
        object.__setattr__(
            self,
            "liquidity_weight",
            _bounded_weight(self.liquidity_weight, "liquidity weight"),
        )
        object.__setattr__(
            self,
            "conviction_weight",
            _bounded_weight(self.conviction_weight, "conviction weight"),
        )
        object.__setattr__(
            self,
            "suggested_weight",
            _bounded_weight(self.suggested_weight, "suggested weight"),
        )
        object.__setattr__(self, "reasons", reasons)


@dataclass(frozen=True, slots=True)
class CorrelationAdjustment:
    symbol: str
    original_weight: Decimal
    adjusted_weight: Decimal
    penalty: Decimal
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("correlation adjustment symbol cannot be empty")

        reasons = _normalized_reasons(
            self.reasons,
            "correlation adjustment reasons",
        )

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(
            self,
            "original_weight",
            _bounded_weight(self.original_weight, "original weight"),
        )
        object.__setattr__(
            self,
            "adjusted_weight",
            _bounded_weight(self.adjusted_weight, "adjusted weight"),
        )
        object.__setattr__(
            self,
            "penalty",
            _bounded_weight(self.penalty, "correlation penalty"),
        )
        object.__setattr__(self, "reasons", reasons)


@dataclass(frozen=True, slots=True)
class RiskBudgetAssessment:
    symbol: str
    approved_weight: Decimal
    blocked_weight: Decimal
    constraints: tuple[AllocationConstraint, ...]
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("risk assessment symbol cannot be empty")

        reasons = _normalized_reasons(self.reasons, "risk assessment reasons")

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(
            self,
            "approved_weight",
            _bounded_weight(self.approved_weight, "approved weight"),
        )
        object.__setattr__(
            self,
            "blocked_weight",
            _bounded_weight(self.blocked_weight, "blocked weight"),
        )
        object.__setattr__(self, "constraints", tuple(dict.fromkeys(self.constraints)))
        object.__setattr__(self, "reasons", reasons)

    @property
    def is_approved(self) -> bool:
        return self.approved_weight > _ZERO


@dataclass(frozen=True, slots=True)
class AllocationReport:
    symbol: str
    sector: str
    observed_on: date
    decision: AllocationDecision
    target_weight: Decimal
    target_amount: Decimal
    sizing: PositionSizingAssessment
    correlation: CorrelationAdjustment
    risk_budget: RiskBudgetAssessment
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        sector = self.sector.strip().upper()
        reasons = _normalized_reasons(self.reasons, "allocation report reasons")

        if not symbol:
            raise ValueError("allocation report symbol cannot be empty")
        if not sector:
            raise ValueError("allocation report sector cannot be empty")

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "sector", sector)
        object.__setattr__(
            self,
            "target_weight",
            _bounded_weight(self.target_weight, "target weight"),
        )
        object.__setattr__(
            self,
            "target_amount",
            Decimal(str(self.target_amount)),
        )
        object.__setattr__(self, "reasons", reasons)


@dataclass(frozen=True, slots=True)
class CapitalAllocationPlan:
    generated_on: date
    reports: tuple[AllocationReport, ...]
    total_allocated_weight: Decimal
    total_allocated_amount: Decimal
    remaining_cash: Decimal
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        reasons = _normalized_reasons(self.reasons, "allocation plan reasons")

        object.__setattr__(self, "reports", tuple(self.reports))
        object.__setattr__(
            self,
            "total_allocated_weight",
            _bounded_weight(self.total_allocated_weight, "allocated weight"),
        )
        object.__setattr__(
            self,
            "total_allocated_amount",
            Decimal(str(self.total_allocated_amount)),
        )
        object.__setattr__(
            self,
            "remaining_cash",
            Decimal(str(self.remaining_cash)),
        )
        object.__setattr__(self, "reasons", reasons)

    @property
    def approved_reports(self) -> tuple[AllocationReport, ...]:
        return tuple(report for report in self.reports if report.target_weight > _ZERO)


class KellySizingEngine:
    """Deterministic capped Kelly-inspired position sizing."""

    def assess(
        self,
        candidate: AllocationCandidate,
        *,
        max_position_weight: Decimal,
    ) -> PositionSizingAssessment:
        cap = _bounded_weight(max_position_weight, "max position weight")
        reward_to_risk = _reward_to_risk(
            expected_return=candidate.expected_return,
            expected_drawdown=candidate.expected_drawdown,
        )
        edge = max(candidate.success_probability - Decimal("0.50"), _ZERO)
        reward_risk_weight = min(reward_to_risk / Decimal("5"), _ONE)
        probability_weight = min(edge * Decimal("2"), _ONE)
        quality_weight = _weighted_average(
            (
                (candidate.recommendation_strength, Decimal("0.30")),
                (probability_weight, Decimal("0.25")),
                (reward_risk_weight, Decimal("0.25")),
                (candidate.liquidity_score, Decimal("0.10")),
                (candidate.conviction_score, Decimal("0.10")),
            )
        )
        suggested_weight = min(cap * quality_weight, cap)

        if candidate.conviction.requires_reduced_allocation:
            suggested_weight *= Decimal("0.50")

        if not candidate.is_allocation_eligible:
            suggested_weight = _ZERO

        return PositionSizingAssessment(
            symbol=candidate.symbol,
            base_weight=cap,
            probability_weight=probability_weight,
            reward_risk_weight=reward_risk_weight,
            liquidity_weight=candidate.liquidity_score,
            conviction_weight=candidate.conviction_score,
            suggested_weight=_quantize(suggested_weight),
            reasons=(
                f"recommendation conviction: {candidate.conviction.value}",
                f"recommendation action: {candidate.recommendation_action}",
                "recommendation strength: "
                f"{_as_percent(candidate.recommendation_strength)}",
                f"success probability: {_as_percent(candidate.success_probability)}",
                f"reward to risk: {_quantize(reward_to_risk)}",
                f"capped position weight: {_as_percent(cap)}",
            ),
        )


class PortfolioConstraintEngine:
    """Apply deterministic portfolio-level limits to proposed allocations."""

    def assess(
        self,
        candidate: AllocationCandidate,
        context: PortfolioContext,
        requested_weight: Decimal,
    ) -> RiskBudgetAssessment:
        requested = _bounded_weight(requested_weight, "requested weight")
        budget = context.risk_budget
        constraints: list[AllocationConstraint] = []
        reasons: list[str] = [
            f"recommendation conviction: {candidate.conviction.value}",
        ]

        current_position = context.current_position_weight(candidate.symbol)
        sector_weight = context.sector_weight(candidate.sector)
        capacity = min(
            budget.max_position_weight - current_position,
            budget.max_sector_weight - sector_weight,
            context.cash_weight,
            budget.max_portfolio_risk_weight,
        )
        approved = min(requested, max(capacity, _ZERO))

        if candidate.has_blocked_recommendation_intent:
            constraints.append(AllocationConstraint.LOW_CONVICTION)
            reasons.append("recommendation action or final signal blocks deployment")
            approved = _ZERO
        elif not candidate.conviction.is_allocation_eligible:
            constraints.append(AllocationConstraint.LOW_CONVICTION)
            reasons.append("recommendation conviction is not allocation eligible")
            approved = _ZERO
        elif candidate.recommendation_score < budget.min_recommendation_score:
            constraints.append(AllocationConstraint.LOW_CONVICTION)
            reasons.append("recommendation score is below required threshold")
            approved = _ZERO

        if context.cash_weight <= _ZERO:
            constraints.append(AllocationConstraint.CASH_LIMIT)
            reasons.append("no available cash remains")

        if current_position >= budget.max_position_weight:
            constraints.append(AllocationConstraint.POSITION_LIMIT)
            reasons.append("position already reached maximum allowed weight")

        if sector_weight >= budget.max_sector_weight:
            constraints.append(AllocationConstraint.SECTOR_LIMIT)
            reasons.append("sector already reached maximum allowed weight")

        if approved < requested:
            constraints.extend(
                self._breached_constraints(
                    requested=requested,
                    current_position=current_position,
                    sector_weight=sector_weight,
                    context=context,
                )
            )

        if approved > _ZERO:
            reasons.append(f"approved weight: {_as_percent(approved)}")
        else:
            reasons.append("allocation blocked by portfolio constraints")

        return RiskBudgetAssessment(
            symbol=candidate.symbol,
            approved_weight=_quantize(approved),
            blocked_weight=_quantize(max(requested - approved, _ZERO)),
            constraints=tuple(dict.fromkeys(constraints)),
            reasons=tuple(reasons),
        )

    def _breached_constraints(
        self,
        *,
        requested: Decimal,
        current_position: Decimal,
        sector_weight: Decimal,
        context: PortfolioContext,
    ) -> tuple[AllocationConstraint, ...]:
        budget = context.risk_budget
        constraints: list[AllocationConstraint] = []

        if context.cash_weight < requested:
            constraints.append(AllocationConstraint.CASH_LIMIT)
        if current_position + requested > budget.max_position_weight:
            constraints.append(AllocationConstraint.POSITION_LIMIT)
        if sector_weight + requested > budget.max_sector_weight:
            constraints.append(AllocationConstraint.SECTOR_LIMIT)
        if requested > budget.max_portfolio_risk_weight:
            constraints.append(AllocationConstraint.RISK_BUDGET)

        return tuple(constraints)


class CapitalAllocationEngine:
    """Build explainable capital allocation reports from ranked candidates."""

    def __init__(
        self,
        *,
        sizing_engine: KellySizingEngine | None = None,
        constraint_engine: PortfolioConstraintEngine | None = None,
    ) -> None:
        self._sizing_engine = sizing_engine or KellySizingEngine()
        self._constraint_engine = constraint_engine or PortfolioConstraintEngine()

    def allocate(
        self,
        candidates: Iterable[AllocationCandidate],
        context: PortfolioContext,
    ) -> CapitalAllocationPlan:
        ordered = self._rank_candidates(candidates)
        if len(ordered) == 0:
            return CapitalAllocationPlan(
                generated_on=date.today(),
                reports=(),
                total_allocated_weight=_ZERO,
                total_allocated_amount=_ZERO,
                remaining_cash=context.available_cash,
                reasons=("no allocation candidates were supplied",),
            )

        reports = self._build_reports(ordered, context)
        allocated_amount = sum((report.target_amount for report in reports), _ZERO)
        allocated_weight = sum((report.target_weight for report in reports), _ZERO)
        remaining_cash = context.available_cash - allocated_amount
        deployed_count = sum(1 for report in reports if report.target_weight > _ZERO)

        return CapitalAllocationPlan(
            generated_on=ordered[0].observed_on,
            reports=reports,
            total_allocated_weight=_quantize(allocated_weight),
            total_allocated_amount=_quantize_money(allocated_amount),
            remaining_cash=_quantize_money(remaining_cash),
            reasons=(
                f"candidate count: {len(ordered)}",
                f"approved capital deployments: {deployed_count}",
                f"remaining cash: {_quantize_money(remaining_cash)}",
            ),
        )

    def _build_reports(
        self,
        candidates: tuple[AllocationCandidate, ...],
        context: PortfolioContext,
    ) -> tuple[AllocationReport, ...]:
        remaining_cash = context.available_cash
        reports: list[AllocationReport] = []
        shadow_context = context

        for candidate in candidates:
            sizing = self._sizing_engine.assess(
                candidate,
                max_position_weight=shadow_context.risk_budget.max_position_weight,
            )
            correlation = self._adjust_for_correlation(candidate, sizing)
            risk = self._constraint_engine.assess(
                candidate,
                shadow_context,
                correlation.adjusted_weight,
            )
            current_position = shadow_context.current_position_weight(candidate.symbol)
            decision = self._decision(
                candidate=candidate,
                correlation=correlation,
                risk=risk,
                sizing=sizing,
                current_position=current_position,
            )
            target_amount = risk.approved_weight * context.total_capital
            remaining_cash = max(remaining_cash - target_amount, _ZERO)

            reports.append(
                AllocationReport(
                    symbol=candidate.symbol,
                    sector=candidate.sector,
                    observed_on=candidate.observed_on,
                    decision=decision,
                    target_weight=risk.approved_weight,
                    target_amount=_quantize_money(target_amount),
                    sizing=sizing,
                    correlation=correlation,
                    risk_budget=risk,
                    reasons=self._report_reasons(
                        candidate=candidate,
                        decision=decision,
                        correlation=correlation,
                        sizing=sizing,
                        risk=risk,
                        current_position=current_position,
                    ),
                )
            )
            shadow_context = self._next_context(
                context=context,
                shadow_context=shadow_context,
                candidate=candidate,
                risk=risk,
                remaining_cash=remaining_cash,
            )

        return tuple(reports)

    def _adjust_for_correlation(
        self,
        candidate: AllocationCandidate,
        sizing: PositionSizingAssessment,
    ) -> CorrelationAdjustment:
        penalty = _ZERO
        reasons = ["correlation is within acceptable range"]

        if not candidate.is_allocation_eligible:
            reasons = ["recommendation intent blocked allocation"]
        elif candidate.correlation_to_portfolio >= Decimal("0.85"):
            penalty = Decimal("0.50")
            reasons = ["very high portfolio correlation reduced allocation"]
        elif candidate.correlation_to_portfolio >= Decimal("0.75"):
            penalty = Decimal("0.30")
            reasons = ["high portfolio correlation reduced allocation"]
        elif candidate.correlation_to_portfolio >= Decimal("0.65"):
            penalty = Decimal("0.15")
            reasons = ["moderate portfolio correlation reduced allocation"]

        adjusted = sizing.suggested_weight * (_ONE - penalty)

        return CorrelationAdjustment(
            symbol=candidate.symbol,
            original_weight=sizing.suggested_weight,
            adjusted_weight=_quantize(adjusted),
            penalty=penalty,
            reasons=tuple(reasons),
        )

    def _decision(
        self,
        *,
        candidate: AllocationCandidate,
        correlation: CorrelationAdjustment,
        risk: RiskBudgetAssessment,
        sizing: PositionSizingAssessment,
        current_position: Decimal,
    ) -> AllocationDecision:
        if not risk.is_approved:
            return AllocationDecision.SKIP

        if candidate.conviction.requires_reduced_allocation:
            return AllocationDecision.REDUCE
        if correlation.adjusted_weight < sizing.suggested_weight:
            return AllocationDecision.REDUCE
        if risk.approved_weight < sizing.suggested_weight:
            return AllocationDecision.REDUCE
        if current_position <= _ZERO:
            return AllocationDecision.ALLOCATE
        return AllocationDecision.ALLOCATE

    def _next_context(
        self,
        *,
        context: PortfolioContext,
        shadow_context: PortfolioContext,
        candidate: AllocationCandidate,
        risk: RiskBudgetAssessment,
        remaining_cash: Decimal,
    ) -> PortfolioContext:
        current_weight = shadow_context.current_position_weight(candidate.symbol)
        return PortfolioContext(
            total_capital=context.total_capital,
            available_cash=remaining_cash,
            current_positions={
                **dict(shadow_context.current_positions),
                candidate.symbol: current_weight + risk.approved_weight,
            },
            sector_exposures=_updated_sector_exposures(
                shadow_context,
                sector=candidate.sector,
                added_weight=risk.approved_weight,
            ),
            risk_budget=context.risk_budget,
        )

    def _report_reasons(
        self,
        *,
        candidate: AllocationCandidate,
        decision: AllocationDecision,
        correlation: CorrelationAdjustment,
        sizing: PositionSizingAssessment,
        risk: RiskBudgetAssessment,
        current_position: Decimal,
    ) -> tuple[str, ...]:
        return (
            f"capital action: {self._capital_action(decision, risk, current_position)}",
            f"decision: {decision.value}",
            f"recommendation conviction: {candidate.conviction.value}",
            f"recommendation action: {candidate.recommendation_action}",
            f"recommendation final signal: {candidate.final_signal or 'UNAVAILABLE'}",
            f"recommendation score: {candidate.recommendation_score}",
            f"success probability: {_as_percent(candidate.success_probability)}",
            f"requested allocation: {_as_percent(sizing.suggested_weight)}",
            "correlation-adjusted allocation: "
            f"{_as_percent(correlation.adjusted_weight)}",
            f"approved allocation: {_as_percent(risk.approved_weight)}",
        )

    def _capital_action(
        self,
        decision: AllocationDecision,
        risk: RiskBudgetAssessment,
        current_position: Decimal,
    ) -> str:
        if not risk.is_approved:
            return "skip"
        if (
            decision is AllocationDecision.REDUCE
            and current_position > _ZERO
            and risk.approved_weight < current_position
        ):
            return "existing_position_reduction"
        if decision is AllocationDecision.REDUCE:
            return "reduced_deployment"
        if current_position > _ZERO:
            return "add_to_existing_position"
        return "fresh_allocation"

    def _rank_candidates(
        self,
        candidates: Iterable[AllocationCandidate],
    ) -> tuple[AllocationCandidate, ...]:
        return tuple(
            sorted(
                candidates,
                key=lambda candidate: (
                    -candidate.recommendation_score,
                    -candidate.success_probability,
                    -_reward_to_risk(
                        expected_return=candidate.expected_return,
                        expected_drawdown=candidate.expected_drawdown,
                    ),
                    -candidate.expected_return,
                    candidate.symbol,
                ),
            )
        )


class PortfolioConstructionEngine:
    """Facade for portfolio construction from allocation candidates."""

    def __init__(
        self,
        allocation_engine: CapitalAllocationEngine | None = None,
    ) -> None:
        self._allocation_engine = allocation_engine or CapitalAllocationEngine()

    def construct(
        self,
        candidates: Iterable[AllocationCandidate],
        context: PortfolioContext,
    ) -> CapitalAllocationPlan:
        return self._allocation_engine.allocate(candidates, context)


def _updated_sector_exposures(
    context: PortfolioContext,
    *,
    sector: str,
    added_weight: Decimal,
) -> tuple[SectorExposure, ...]:
    normalized_sector = sector.strip().upper()
    exposures: dict[str, Decimal] = {
        exposure.sector: exposure.current_weight
        for exposure in context.sector_exposures
    }
    current_weight = exposures.get(normalized_sector, _ZERO)
    exposures[normalized_sector] = current_weight + added_weight

    return tuple(
        SectorExposure(sector=name, current_weight=_quantize(weight))
        for name, weight in sorted(exposures.items())
    )


def _normalized_reasons(
    reasons: Iterable[str],
    label: str,
) -> tuple[str, ...]:
    normalized = tuple(reason.strip() for reason in reasons)
    if len(normalized) == 0 or any(not reason for reason in normalized):
        raise ValueError(f"{label} cannot be empty")
    return normalized


__all__ = [
    "AllocationCandidate",
    "AllocationConstraint",
    "AllocationConviction",
    "AllocationDecision",
    "AllocationReport",
    "CapitalAllocationEngine",
    "CapitalAllocationPlan",
    "CorrelationAdjustment",
    "KellySizingEngine",
    "PositionSizingAssessment",
    "PortfolioConstraintEngine",
    "PortfolioConstructionEngine",
    "PortfolioContext",
    "RiskBudget",
    "RiskBudgetAssessment",
    "SectorExposure",
]
