"""Budget-constrained procurement strategies for DVRA."""

# ruff: noqa: E501

from __future__ import annotations

from alpha.data_value_audit.models import BudgetPlan, DatasetReportCard


class ProcurementPrioritizer:
    """Produce explicit evidence-gated portfolios for the four required budgets."""

    def plans(self, cards: tuple[DatasetReportCard, ...]) -> tuple[BudgetPlan, ...]:
        available = {card.candidate.dataset_id for card in cards}
        plans = (
            BudgetPlan(
                budget_id="budget_0",
                title="Budget A - INR 0",
                annual_budget_inr=0,
                selected_dataset_ids=_present(
                    available,
                    (
                        "trading_calendar",
                        "risk_free_rate",
                        "india_vix",
                        "market_breadth",
                    ),
                ),
                known_annual_spend_inr=0,
                unallocated_inr=0,
                procurement_instruction="Purchase nothing. Intake only official no-fee sources after retention and internal-research rights are confirmed.",
                rationale="Close calendar, risk-metric and market-context gaps without claiming that public access grants warehouse rights.",
                conditions=(
                    "Record source terms and checksums.",
                    "Keep all unconfirmed history classified UNKNOWN.",
                ),
            ),
            BudgetPlan(
                budget_id="budget_1L",
                title="Budget B - INR 1 lakh/year",
                annual_budget_inr=100_000,
                selected_dataset_ids=_present(
                    available, ("official_nse_daily_history",)
                ),
                known_annual_spend_inr=100_000,
                unallocated_inr=0,
                procurement_instruction="Buy Official NSE Daily History first, subject to a written license covering Alpha's intended historical retention and internal non-display research.",
                rationale="It replaces the provisional core used by replay, candidates, trade plans, attribution and learning; no other published INR 1 lakh option reaches as many critical paths.",
                conditions=(
                    "Confirm included historical depth.",
                    "Reject procurement if retention or internal research rights are absent.",
                ),
            ),
            BudgetPlan(
                budget_id="budget_5L",
                title="Budget C - INR 5 lakh/year",
                annual_budget_inr=500_000,
                selected_dataset_ids=_present(
                    available,
                    (
                        "official_nse_daily_history",
                        "security_master",
                        "official_bse_daily_history",
                    ),
                ),
                known_annual_spend_inr=435_000,
                unallocated_inr=65_000,
                procurement_instruction="Buy NSE daily history and the security master; add BSE daily history only after a bounded overlap sample confirms material coverage or reconciliation value.",
                rationale="Price truth plus identity is a coherent warehouse foundation. BSE is the next affordable coverage/reconciliation layer; INR 65,000 remains uncommitted.",
                conditions=(
                    "Run a symbol-overlap and BSE-only coverage sample before the BSE contract.",
                    "Do not substitute corporate actions for identity and core prices.",
                ),
            ),
            BudgetPlan(
                budget_id="budget_unlimited",
                title="Budget D - Unlimited institutional-grade",
                annual_budget_inr=None,
                selected_dataset_ids=_present(
                    available,
                    (
                        "official_nse_daily_history",
                        "security_master",
                        "corporate_actions",
                        "historical_index_ohlc",
                        "historical_index_membership",
                        "historical_sector_membership",
                        "delivery_data",
                        "market_breadth",
                        "ownership_data",
                        "earnings_data",
                        "official_bse_daily_history",
                    ),
                ),
                known_annual_spend_inr=935_000,
                unallocated_inr=None,
                procurement_instruction="Procure in dependency order: core NSE truth, identity, corporate actions, index context, delivery/breadth, then ownership and earnings. Add BSE after overlap evidence.",
                rationale="Institutional-grade means complete lineage and rights, not indiscriminate purchasing; quote-required datasets still require samples and contracts.",
                conditions=(
                    "Benchmark every layer against the frozen replay.",
                    "Do not promote a dataset without measured incremental decision value.",
                    "Keep reconstructed and official evidence separate.",
                ),
            ),
        )
        return plans


def _present(available: set[str], requested: tuple[str, ...]) -> tuple[str, ...]:
    missing = set(requested) - available
    if missing:
        raise ValueError(f"budget references unregistered datasets: {sorted(missing)}")
    return requested


__all__ = ["ProcurementPrioritizer"]
