"""Acquisition, engineering, maintenance, and rights cost model for DVRA."""

# ruff: noqa: E501

from __future__ import annotations

from alpha.data_value_audit.models import (
    ComplexityLevel,
    CostAssessment,
    CostStatus,
    DatasetCandidate,
    RiskLevel,
)

HMDPCA_COST_SOURCE = "docs/hmdpca/cost_matrix.csv"

_PUBLISHED_ANNUAL_COSTS = {
    "official_nse_daily_history": 100_000,
    "official_bse_daily_history": 120_000,
    "corporate_actions": 500_000,
    "security_master": 215_000,
}
_NO_LICENSE_FEE_IDENTIFIED = {
    "india_vix",
    "risk_free_rate",
    "trading_calendar",
    "market_breadth",
}
_LOW_ENGINEERING = {"risk_free_rate", "india_vix", "trading_calendar"}
_HIGH_ENGINEERING = {
    "corporate_actions",
    "historical_index_membership",
    "historical_sector_membership",
    "ownership_data",
    "earnings_data",
}


class CostModel:
    """Return only documented or explicitly unknown cost facts."""

    def assess(self, candidate: DatasetCandidate) -> CostAssessment:
        dataset_id = candidate.dataset_id
        engineering = (
            ComplexityLevel.LOW
            if dataset_id in _LOW_ENGINEERING
            else ComplexityLevel.HIGH
            if dataset_id in _HIGH_ENGINEERING
            else ComplexityLevel.MEDIUM
        )
        maintenance = (
            ComplexityLevel.HIGH
            if dataset_id in {"corporate_actions", "ownership_data", "earnings_data"}
            else ComplexityLevel.LOW
            if dataset_id in _LOW_ENGINEERING
            else ComplexityLevel.MEDIUM
        )
        if candidate.package_parent is not None:
            return CostAssessment(
                dataset_id=dataset_id,
                status=CostStatus.BUNDLED,
                initial_cost_inr=None,
                annual_cost_inr=None,
                engineering_cost=engineering,
                maintenance_cost=maintenance,
                licensing_risk=RiskLevel.UNKNOWN,
                legal_risk=RiskLevel.MEDIUM,
                source=HMDPCA_COST_SOURCE,
                notes=(
                    f"No standalone price is assigned; evaluate within package "
                    f"{candidate.package_parent}."
                ),
            )
        if dataset_id in _PUBLISHED_ANNUAL_COSTS:
            annual = _PUBLISHED_ANNUAL_COSTS[dataset_id]
            return CostAssessment(
                dataset_id=dataset_id,
                status=CostStatus.PUBLISHED,
                initial_cost_inr=None,
                annual_cost_inr=annual,
                engineering_cost=engineering,
                maintenance_cost=maintenance,
                licensing_risk=RiskLevel.MEDIUM,
                legal_risk=RiskLevel.LOW,
                source=HMDPCA_COST_SOURCE,
                notes="Published reference price; scope, history and permitted use require contract confirmation.",
            )
        if dataset_id in _NO_LICENSE_FEE_IDENTIFIED:
            return CostAssessment(
                dataset_id=dataset_id,
                status=CostStatus.NO_LICENSE_FEE_IDENTIFIED,
                initial_cost_inr=0,
                annual_cost_inr=0,
                engineering_cost=engineering,
                maintenance_cost=maintenance,
                licensing_risk=RiskLevel.MEDIUM,
                legal_risk=RiskLevel.MEDIUM,
                source=HMDPCA_COST_SOURCE,
                notes="No license fee identified in the audit; retention and non-display rights remain to be confirmed.",
            )
        if dataset_id == "turnover_trade_count":
            return CostAssessment(
                dataset_id=dataset_id,
                status=CostStatus.BUNDLED,
                initial_cost_inr=None,
                annual_cost_inr=None,
                engineering_cost=engineering,
                maintenance_cost=maintenance,
                licensing_risk=RiskLevel.UNKNOWN,
                legal_risk=RiskLevel.MEDIUM,
                source=HMDPCA_COST_SOURCE,
                notes="Expected within an exchange market-data package; standalone price not established.",
            )
        return CostAssessment(
            dataset_id=dataset_id,
            status=CostStatus.QUOTE_REQUIRED,
            initial_cost_inr=None,
            annual_cost_inr=None,
            engineering_cost=engineering,
            maintenance_cost=maintenance,
            licensing_risk=RiskLevel.UNKNOWN,
            legal_risk=RiskLevel.MEDIUM,
            source=HMDPCA_COST_SOURCE,
            notes="Supplier quote and rights schedule required; DVRA does not invent a price.",
        )


__all__ = ["CostModel", "HMDPCA_COST_SOURCE"]
