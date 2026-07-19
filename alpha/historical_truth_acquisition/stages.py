from __future__ import annotations

from alpha.historical_truth_acquisition.models import (
    CORPORATE_ACTIONS_VERSION,
    DAILY_MARKET_HISTORY_VERSION,
    DELIVERY_HISTORY_VERSION,
    INDEX_HISTORY_VERSION,
    INDEX_MEMBERSHIP_VERSION,
    SECURITY_MASTER_VERSION,
    TRADING_CALENDAR_VERSION,
    HTAStage,
    StageDefinition,
)

STAGES: tuple[StageDefinition, ...] = (
    StageDefinition(
        HTAStage.SECURITY_IDENTITY,
        1,
        SECURITY_MASTER_VERSION,
        (
            "nse-security-master",
            "nse-isin-mapping",
            "nse-symbol-history",
            "bse-security-master",
        ),
        (),
        False,
    ),
    StageDefinition(
        HTAStage.TRADING_CALENDAR,
        2,
        TRADING_CALENDAR_VERSION,
        ("nse-trading-calendar",),
        (HTAStage.SECURITY_IDENTITY,),
        True,
    ),
    StageDefinition(
        HTAStage.DAILY_EQUITY_HISTORY,
        3,
        DAILY_MARKET_HISTORY_VERSION,
        ("nse-equity-bhavcopy", "bse-equity-bhavcopy"),
        (HTAStage.SECURITY_IDENTITY, HTAStage.TRADING_CALENDAR),
        True,
    ),
    StageDefinition(
        HTAStage.INDEX_HISTORY,
        4,
        INDEX_HISTORY_VERSION,
        (
            "nse-index-nifty-50-ohlcv",
            "nse-index-nifty-next-50-ohlcv",
            "nse-index-nifty-100-ohlcv",
            "nse-index-nifty-200-ohlcv",
            "nse-index-nifty-500-ohlcv",
            "nse-index-nifty-midcap-ohlcv",
            "nse-index-nifty-smallcap-ohlcv",
            "nse-index-nifty-total-market-ohlcv",
            "nse-sector-indices-ohlcv",
        ),
        (HTAStage.TRADING_CALENDAR,),
        True,
    ),
    StageDefinition(
        HTAStage.INDEX_MEMBERSHIP,
        5,
        INDEX_MEMBERSHIP_VERSION,
        ("nse-historical-index-membership",),
        (HTAStage.SECURITY_IDENTITY,),
        True,
    ),
    StageDefinition(
        HTAStage.CORPORATE_ACTIONS,
        6,
        CORPORATE_ACTIONS_VERSION,
        ("nse-corporate-actions", "bse-corporate-actions"),
        (HTAStage.SECURITY_IDENTITY,),
        False,
    ),
    StageDefinition(
        HTAStage.DELIVERY_HISTORY,
        7,
        DELIVERY_HISTORY_VERSION,
        ("nse-delivery",),
        (HTAStage.DAILY_EQUITY_HISTORY,),
        True,
    ),
)


def stage_for_dataset(dataset_id: str) -> StageDefinition:
    normalized = dataset_id.strip().lower()
    for stage in STAGES:
        if normalized in stage.dataset_ids:
            return stage
    raise KeyError(f"HTA dataset is not assigned to a stage: {dataset_id}")


def selected_stages(dataset_id: str | None) -> tuple[StageDefinition, ...]:
    if dataset_id is None:
        return STAGES
    return (stage_for_dataset(dataset_id),)


__all__ = ["STAGES", "selected_stages", "stage_for_dataset"]
