from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from alpha.market_opportunity_truth.comparison import (
    AlphaOpportunityComparisonEngine,
)
from alpha.market_opportunity_truth.models import (
    DetectionStatus,
    MarketOpportunity,
    OpportunityQuality,
)
from alpha.market_opportunity_truth.opportunity_calendar import (
    build_opportunity_calendar,
)
from alpha.market_opportunity_truth.opportunity_density import (
    build_opportunity_density,
)


def test_calendar_and_density_include_zero_opportunity_sessions(
    market_opportunities: tuple[MarketOpportunity, ...],
) -> None:
    sessions = (
        date(2024, 1, 2),
        date(2024, 1, 3),
        date(2024, 2, 1),
        date(2024, 3, 1),
    )
    calendar = build_opportunity_calendar(market_opportunities, sessions=sessions)
    by_month = {item.month: item for item in calendar}
    assert by_month["2024-01"].opportunities == 2
    assert by_month["2024-01"].institutional_quality == 2
    assert by_month["2024-03"].opportunities == 0
    density = build_opportunity_density(market_opportunities, sessions=sessions)
    monthly = {item.period: item for item in density if item.period_type == "MONTH"}
    assert monthly["2024-02"].medium_quality == 1
    assert monthly["2024-03"].opportunities == 0


def test_alpha_comparison_uses_bounded_one_to_one_matching(
    tmp_path: Path,
    market_opportunities: tuple[MarketOpportunity, ...],
) -> None:
    sessions = tuple(date(2024, 1, day) for day in range(2, 11)) + (
        date(2024, 2, 1),
        date(2024, 2, 2),
    )
    candidate_path = tmp_path / "candidate_rankings.csv"
    with candidate_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "observed_on",
                "symbol",
                "final_signal",
                "approval_candidate",
                "institutional_approved",
            ),
        )
        writer.writeheader()
        writer.writerows(
            (
                {
                    "observed_on": "2024-01-02",
                    "symbol": "AAA",
                    "final_signal": "WATCHLIST",
                    "approval_candidate": "False",
                    "institutional_approved": "False",
                },
                {
                    "observed_on": "2024-01-03",
                    "symbol": "AAA",
                    "final_signal": "BUY",
                    "approval_candidate": "True",
                    "institutional_approved": "False",
                },
                {
                    "observed_on": "2024-01-08",
                    "symbol": "BBB",
                    "final_signal": "BUY",
                    "approval_candidate": "True",
                    "institutional_approved": "True",
                },
            )
        )
    trade_path = tmp_path / "trade_log.csv"
    trade_path.write_text(
        "trade_id,symbol,decision_date,entry_date\n", encoding="utf-8"
    )
    rows, capture = AlphaOpportunityComparisonEngine().compare(
        opportunities=market_opportunities,
        sessions=sessions,
        candidate_rankings_path=candidate_path,
        trade_log_path=trade_path,
        matching_window_sessions=5,
    )
    by_id = {item.opportunity_id: item for item in rows}
    assert by_id["op-1"].detected_status is DetectionStatus.DETECTED
    assert by_id["op-1"].candidate_created is True
    assert by_id["op-1"].candidate_delay_sessions == 1
    assert by_id["op-2"].candidate_created is False
    assert capture.institutional_quality_opportunities == 2
    assert capture.institutional_candidate_recall_percent == 50
    assert capture.institutional_approval_recall_percent == 0
    assert capture.detection_trace_complete is False


def test_quality_distribution_is_outcome_conditioned_only_after_grading(
    market_opportunities: tuple[MarketOpportunity, ...],
) -> None:
    assert [item.quality for item in market_opportunities] == [
        OpportunityQuality.A_PLUS,
        OpportunityQuality.A,
        OpportunityQuality.B,
    ]
