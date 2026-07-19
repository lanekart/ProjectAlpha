from __future__ import annotations

import csv
from dataclasses import replace
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from alpha.adaptive_weights.models import (
    AblationObservation,
    AblationRole,
    AlphaComponent,
    EvidencePartition,
    ResearchPerformance,
)
from alpha.adaptive_weights.policy_registry import CandidateWeightPolicyRegistry
from alpha.tradingview_research.baseline import canonical_baseline_configuration
from alpha.tradingview_research.models import (
    ComponentWeight,
    ExperimentObservation,
    LabConfiguration,
    ObservationRole,
    PerformanceMetrics,
    ResearchPartition,
    TradingViewExperiment,
)

_TRL_TO_ALPHA = {
    "price_structure": AlphaComponent.PRICE_STRUCTURE,
    "volume": AlphaComponent.VOLUME,
    "trend": AlphaComponent.TREND,
    "relative_strength": AlphaComponent.RELATIVE_STRENGTH,
    "retracement": AlphaComponent.RETRACEMENT,
    "candle": AlphaComponent.CANDLESTICK,
    "breakout": AlphaComponent.BREAKOUT_SETUP,
    "market_regime": AlphaComponent.MARKET_REGIME,
    "sector": AlphaComponent.SECTOR,
    "risk": AlphaComponent.RISK_VOLATILITY,
}
_ALPHA_TO_TRL = {value: key for key, value in _TRL_TO_ALPHA.items()}


def frozen_weight_presets(
    policy_registry: CandidateWeightPolicyRegistry | None = None,
) -> tuple[LabConfiguration, ...]:
    baseline = canonical_baseline_configuration()
    presets = [
        replace(baseline, name="ALPHA_CANONICAL"),
        _preset(baseline, "NO_RETRACEMENT", {"retracement": Decimal("0")}),
        _only(baseline, "PRICE_ONLY", ("price_structure",)),
        _only(baseline, "PRICE_VOLUME", ("price_structure", "volume")),
        _only(
            baseline,
            "PRICE_VOLUME_TREND",
            ("price_structure", "volume", "trend"),
        ),
        _only(
            baseline,
            "MINIMAL_ALPHA",
            ("price_structure", "volume", "trend", "relative_strength"),
        ),
    ]
    if policy_registry is not None:
        for policy in policy_registry.load():
            trl_weights = {
                _ALPHA_TO_TRL[item.component]: item.weight
                for item in policy.proposed_weights.weights
            }
            presets.append(
                _preset(
                    baseline,
                    f"ADAPTIVE_CANDIDATE_{policy.policy_id}",
                    trl_weights,
                    replace_all=True,
                )
            )
    return tuple(presets)


class TradingViewStrategyTesterImporter:
    """Imports measured TradingView rows without inferring missing performance."""

    def import_csv(
        self,
        path: Path,
        *,
        research_id: str,
        baseline: LabConfiguration,
        treatment: LabConfiguration,
        title: str = "TradingView component-weight experiment",
    ) -> TradingViewExperiment:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            raw_rows = list(csv.DictReader(handle))
        if not raw_rows:
            raise ValueError("TradingView Strategy Tester CSV contains no rows")
        observations = tuple(self._observation(row) for row in raw_rows)
        dates = [item.period_end for item in observations]
        return TradingViewExperiment(
            experiment_id=research_id,
            title=title,
            purpose="measured component-weight or ablation comparison",
            experiment_date=max(dates),
            baseline=baseline,
            treatment=treatment,
            observations=observations,
        )

    def _observation(self, raw: dict[str, str]) -> ExperimentObservation:
        row = {_normalize_key(key): value for key, value in raw.items()}
        role = ObservationRole(_required(row, "role").upper())
        partition = ResearchPartition(_required(row, "partition").upper())
        return ExperimentObservation(
            role=role,
            partition=partition,
            symbol=_required(row, "symbol"),
            sector=_required(row, "sector"),
            period_start=date.fromisoformat(_required(row, "period_start")),
            period_end=date.fromisoformat(_required(row, "period_end")),
            metrics=PerformanceMetrics(
                trade_count=_required_int(row, "total_closed_trades", "trade_count"),
                win_rate_pct=_optional_decimal(
                    row, "percent_profitable", "win_rate_pct"
                ),
                profit_factor=_optional_decimal(row, "profit_factor"),
                expectancy=_optional_decimal(row, "expectancy_r", "expectancy"),
                maximum_drawdown_pct=_optional_decimal(
                    row, "max_drawdown_pct", "maximum_drawdown_pct"
                ),
                net_return_pct=_optional_decimal(
                    row, "net_profit_pct", "net_return_pct"
                ),
                average_winner=_optional_decimal(
                    row, "average_winner_r", "average_winner"
                ),
                average_loser=_optional_decimal(
                    row, "average_loser_r", "average_loser"
                ),
                stop_out_rate_pct=_optional_decimal(row, "stop_out_rate_pct"),
                average_holding_period=_optional_decimal(
                    row, "average_bars_in_trades", "average_holding_period"
                ),
            ),
        )


class TradingViewWeightEvidenceAdapter:
    def to_matched_ablation(
        self, experiment: TradingViewExperiment
    ) -> tuple[AblationObservation, ...]:
        component, baseline_contains_component = _single_changed_component(
            experiment.baseline, experiment.treatment
        )
        observations = []
        for item in experiment.observations:
            metrics = item.metrics
            required = (
                metrics.win_rate_pct,
                metrics.profit_factor,
                metrics.expectancy,
                metrics.maximum_drawdown_pct,
                metrics.average_winner,
                metrics.average_loser,
                metrics.average_holding_period,
            )
            if any(value is None for value in required):
                raise ValueError(
                    "ablation evidence requires R-normalized expectancy, payoff, "
                    "drawdown, win rate, and holding period"
                )
            assert metrics.win_rate_pct is not None
            assert metrics.expectancy is not None
            assert metrics.maximum_drawdown_pct is not None
            assert metrics.average_winner is not None
            assert metrics.average_loser is not None
            assert metrics.average_holding_period is not None
            observations.append(
                AblationObservation(
                    research_id=experiment.experiment_id,
                    component=component,
                    role=(
                        AblationRole.WITH_COMPONENT
                        if (
                            item.role is ObservationRole.ALPHA_BASELINE
                            and baseline_contains_component
                        )
                        or (
                            item.role is ObservationRole.TREATMENT
                            and not baseline_contains_component
                        )
                        else AblationRole.WITHOUT_COMPONENT
                    ),
                    symbol=item.symbol,
                    decision_date=item.period_start,
                    strategy_family=experiment.treatment.name,
                    setup_family="ALL_ENABLED_TRL_SETUPS",
                    stop_policy=experiment.treatment.stop_model,
                    exit_policy=experiment.treatment.exit_model,
                    cost_profile="TRADINGVIEW_STRATEGY_PROPERTIES_EMBEDDED",
                    dataset_version="TRADINGVIEW_CHART_DATA",
                    partition=EvidencePartition(item.partition.value),
                    performance=ResearchPerformance(
                        expectancy=metrics.expectancy,
                        win_rate=metrics.win_rate_pct / Decimal("100"),
                        average_winner_r=metrics.average_winner,
                        average_loser_r=metrics.average_loser,
                        profit_factor=metrics.profit_factor,
                        max_drawdown=metrics.maximum_drawdown_pct,
                        trade_count=metrics.trade_count,
                        average_holding_period=metrics.average_holding_period,
                        turnover=None,
                        transaction_costs=None,
                        sector_concentration=Decimal("1"),
                        setup_concentration=Decimal("1"),
                    ),
                )
            )
        return tuple(observations)


def _single_changed_component(
    baseline: LabConfiguration, treatment: LabConfiguration
) -> tuple[AlphaComponent, bool]:
    baseline_weights = {item.component: item.weight for item in baseline.weights}
    treatment_weights = {item.component: item.weight for item in treatment.weights}
    removed = tuple(
        _TRL_TO_ALPHA[name]
        for name, weight in baseline_weights.items()
        if weight > Decimal("0")
        and treatment_weights.get(name, Decimal("0")) == Decimal("0")
    )
    if len(removed) == 1:
        return removed[0], True
    added = tuple(
        _TRL_TO_ALPHA[name]
        for name, weight in treatment_weights.items()
        if weight > Decimal("0")
        and baseline_weights.get(name, Decimal("0")) == Decimal("0")
    )
    if len(added) != 1:
        raise ValueError(
            "matched ablation requires exactly one removed or introduced component"
        )
    return added[0], False


def _preset(
    baseline: LabConfiguration,
    name: str,
    replacements: dict[str, Decimal],
    *,
    replace_all: bool = False,
) -> LabConfiguration:
    source = {item.component: item.weight for item in baseline.weights}
    if replace_all:
        source = dict(replacements)
    else:
        source.update(replacements)
    normalized = _normalize_weights(source)
    return replace(
        baseline,
        name=name,
        weights=tuple(
            ComponentWeight(component=component, weight=weight)
            for component, weight in normalized.items()
        ),
    )


def _only(
    baseline: LabConfiguration, name: str, included: tuple[str, ...]
) -> LabConfiguration:
    source = {
        item.component: item.weight if item.component in included else Decimal("0")
        for item in baseline.weights
    }
    return _preset(baseline, name, source, replace_all=True)


def _normalize_weights(values: dict[str, Decimal]) -> dict[str, Decimal]:
    total = sum(values.values(), start=Decimal("0"))
    if total <= Decimal("0"):
        raise ValueError("weight preset must retain at least one component")
    normalized = {
        component: weight * Decimal("100") / total
        for component, weight in sorted(values.items())
    }
    residual = Decimal("100") - sum(normalized.values(), start=Decimal("0"))
    first = next(iter(normalized))
    normalized[first] += residual
    return normalized


def _normalize_key(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("%", "pct")


def _required(row: dict[str, str], *names: str) -> str:
    for name in names:
        value = row.get(name, "").strip()
        if value:
            return value
    raise ValueError(f"TradingView CSV requires one of: {', '.join(names)}")


def _required_int(row: dict[str, str], *names: str) -> int:
    return int(_required(row, *names))


def _optional_decimal(row: dict[str, str], *names: str) -> Decimal | None:
    for name in names:
        value = row.get(name, "").strip().replace(",", "")
        if not value:
            continue
        try:
            return Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"invalid decimal in TradingView field {name}") from exc
    return None


__all__ = [
    "TradingViewStrategyTesterImporter",
    "TradingViewWeightEvidenceAdapter",
    "frozen_weight_presets",
]
