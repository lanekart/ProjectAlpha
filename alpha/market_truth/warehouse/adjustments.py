from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from alpha.market_truth.warehouse.models import (
    AdjustedDailyRecord,
    AdjustmentMode,
    CanonicalDailyRecord,
    CorporateActionKind,
    CorporateActionRecord,
    DividendMode,
    ReconciliationStatus,
    stable_hash,
)
from alpha.market_truth.warehouse.storage import WarehouseStore

ADJUSTMENT_POLICY_VERSION = "ADJUSTMENT_POLICY_1.0.0"


@dataclass(frozen=True, slots=True)
class AdjustmentBuildResult:
    mode: AdjustmentMode
    records: tuple[AdjustedDailyRecord, ...]
    applied_events: tuple[str, ...]
    skipped_events: tuple[str, ...]
    corporate_action_version: str


@dataclass(frozen=True, slots=True)
class AdjustmentAudit:
    actions: int
    confirmed: int
    conflicting: int
    incomplete: int
    quarantined: int
    adjustable: int
    adjusted_rows: int


class CorporateActionAdjustmentService:
    def __init__(self, store: WarehouseStore) -> None:
        self.store = store

    def build(
        self,
        *,
        mode: AdjustmentMode,
        adjustment_as_of: date,
        dividend_mode: DividendMode = DividendMode.UNADJUSTED,
    ) -> AdjustmentBuildResult:
        raw = self.store.daily_records()
        actions = self.store.corporate_action_records(
            announced_as_of=(
                adjustment_as_of if mode is AdjustmentMode.POINT_IN_TIME else None
            )
        )
        corporate_action_version = (
            "corporate-actions-"
            + stable_hash(
                [
                    (
                        item.corporate_action_id,
                        item.version,
                        item.reconciliation_status.value,
                    )
                    for item in actions
                ]
            )[:20]
        )
        previous_close = _previous_close_by_event(raw, actions)
        output: list[AdjustedDailyRecord] = []
        applied: set[str] = set()
        skipped: set[str] = set()
        eligible_raw = tuple(
            bar
            for bar in raw
            if mode is not AdjustmentMode.POINT_IN_TIME
            or bar.trading_date <= adjustment_as_of
        )
        for bar in eligible_raw:
            price_factor = Decimal("1")
            volume_factor = Decimal("1")
            event_ids: list[str] = []
            for action in () if mode is AdjustmentMode.RAW else actions:
                if action.security_id != bar.security_id:
                    continue
                if action.ex_date is None or action.ex_date > adjustment_as_of:
                    continue
                if bar.trading_date >= action.ex_date:
                    continue
                if action.reconciliation_status not in {
                    ReconciliationStatus.CONFIRMED,
                    ReconciliationStatus.REVISED,
                }:
                    skipped.add(action.corporate_action_id)
                    continue
                factors = _event_factors(
                    action,
                    previous_close=previous_close.get(action.corporate_action_id),
                    dividend_mode=dividend_mode,
                )
                if factors is None:
                    skipped.add(action.corporate_action_id)
                    continue
                price_factor *= factors[0]
                volume_factor *= factors[1]
                event_ids.append(action.corporate_action_id)
                applied.add(action.corporate_action_id)
            if mode is AdjustmentMode.RAW:
                price_factor = volume_factor = Decimal("1")
                event_ids = []
            output.append(
                AdjustedDailyRecord(
                    raw=bar,
                    open=_price(bar.open * price_factor),
                    high=_price(bar.high * price_factor),
                    low=_price(bar.low * price_factor),
                    close=_price(bar.close * price_factor),
                    volume=_volume(bar.volume * volume_factor),
                    adjustment_policy_version=ADJUSTMENT_POLICY_VERSION,
                    corporate_action_version=corporate_action_version,
                    cumulative_price_factor=price_factor,
                    cumulative_volume_factor=volume_factor,
                    adjustment_as_of=adjustment_as_of,
                    source_event_ids=tuple(event_ids),
                    mode=mode,
                )
            )
        records = tuple(output)
        with self.store.transaction() as database:
            self.store.replace_adjusted(records, mode=mode, database=database)
        return AdjustmentBuildResult(
            mode=mode,
            records=records,
            applied_events=tuple(sorted(applied)),
            skipped_events=tuple(sorted(skipped)),
            corporate_action_version=corporate_action_version,
        )

    def audit(self) -> AdjustmentAudit:
        actions = self.store.corporate_action_records()
        adjustable = {
            CorporateActionKind.STOCK_SPLIT,
            CorporateActionKind.REVERSE_SPLIT,
            CorporateActionKind.BONUS,
            CorporateActionKind.RIGHTS,
            CorporateActionKind.DIVIDEND,
            CorporateActionKind.INTERIM_DIVIDEND,
            CorporateActionKind.FINAL_DIVIDEND,
            CorporateActionKind.SPECIAL_DIVIDEND,
        }
        return AdjustmentAudit(
            actions=len(actions),
            confirmed=sum(
                item.reconciliation_status is ReconciliationStatus.CONFIRMED
                for item in actions
            ),
            conflicting=sum(
                item.reconciliation_status is ReconciliationStatus.CONFLICTING
                for item in actions
            ),
            incomplete=sum(
                item.reconciliation_status is ReconciliationStatus.INCOMPLETE
                for item in actions
            ),
            quarantined=sum(
                item.reconciliation_status is ReconciliationStatus.QUARANTINED
                for item in actions
            ),
            adjustable=sum(item.action_type in adjustable for item in actions),
            adjusted_rows=sum(
                len(self.store.adjusted_records(mode))
                for mode in (
                    AdjustmentMode.ADJUSTED,
                    AdjustmentMode.TOTAL_RETURN,
                    AdjustmentMode.POINT_IN_TIME,
                )
            ),
        )


def _event_factors(
    action: CorporateActionRecord,
    *,
    previous_close: Decimal | None,
    dividend_mode: DividendMode,
) -> tuple[Decimal, Decimal] | None:
    numerator = action.ratio_numerator
    denominator = action.ratio_denominator
    if action.action_type in {
        CorporateActionKind.STOCK_SPLIT,
        CorporateActionKind.REVERSE_SPLIT,
    }:
        if numerator is None or denominator is None or min(numerator, denominator) <= 0:
            return None
        return denominator / numerator, numerator / denominator
    if action.action_type is CorporateActionKind.BONUS:
        if numerator is None or denominator is None or min(numerator, denominator) <= 0:
            return None
        return denominator / (denominator + numerator), (
            denominator + numerator
        ) / denominator
    if action.action_type is CorporateActionKind.RIGHTS:
        if (
            numerator is None
            or denominator is None
            or action.cash_amount is None
            or previous_close is None
            or min(numerator, denominator, previous_close) <= 0
        ):
            return None
        factor = (denominator + numerator * action.cash_amount / previous_close) / (
            denominator + numerator
        )
        return factor, (denominator + numerator) / denominator
    if action.action_type in {
        CorporateActionKind.DIVIDEND,
        CorporateActionKind.INTERIM_DIVIDEND,
        CorporateActionKind.FINAL_DIVIDEND,
        CorporateActionKind.SPECIAL_DIVIDEND,
    }:
        if dividend_mode is DividendMode.UNADJUSTED:
            return None
        if (
            action.cash_amount is None
            or previous_close is None
            or previous_close <= action.cash_amount
        ):
            return None
        return (previous_close - action.cash_amount) / previous_close, Decimal("1")
    return None


def _previous_close_by_event(
    raw: tuple[CanonicalDailyRecord, ...], actions: tuple[CorporateActionRecord, ...]
) -> dict[str, Decimal]:
    output: dict[str, Decimal] = {}
    for action in actions:
        if action.ex_date is None:
            continue
        candidates = tuple(
            item
            for item in raw
            if item.security_id == action.security_id
            and item.trading_date < action.ex_date
        )
        if candidates:
            latest = max(candidates, key=lambda item: item.trading_date)
            output[action.corporate_action_id] = latest.close
    return output


def _price(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


def _volume(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


__all__ = [
    "ADJUSTMENT_POLICY_VERSION",
    "AdjustmentAudit",
    "AdjustmentBuildResult",
    "CorporateActionAdjustmentService",
]
