from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import Decimal

import duckdb

from alpha.market_truth.models import (
    CorporateAction,
    CorporateActionType,
    DatasetKind,
    EvidenceClass,
    IdentityAuthority,
    IndexObservation,
    MarketBar,
    MarketTruthRecord,
    MarketTruthRequest,
    PriceHistoryMode,
    ProviderClass,
    ProviderDataset,
    ProviderDescriptor,
    SecurityIdentity,
    SecurityStatus,
    TradingSession,
    TradingSessionType,
    UniverseObservation,
)
from alpha.market_truth.provider_registry import MarketTruthProviderError
from alpha.market_truth.warehouse.models import (
    AdjustmentMode,
    CorporateActionKind,
    SessionState,
    WarehousePaths,
)
from alpha.market_truth.warehouse.storage import WarehouseStore


class WarehouseMarketTruthProvider:
    def __init__(
        self,
        *,
        paths: WarehousePaths,
        provider_id: str,
        mode: PriceHistoryMode,
        priority: int,
        include_reference_data: bool,
    ) -> None:
        self.paths = paths
        self.mode = mode
        capabilities = [DatasetKind.DAILY]
        if include_reference_data:
            capabilities.extend(
                (
                    DatasetKind.IDENTITY,
                    DatasetKind.CORPORATE_ACTIONS,
                    DatasetKind.CALENDAR,
                    DatasetKind.UNIVERSE,
                    DatasetKind.INDEX,
                )
            )
        self._descriptor = ProviderDescriptor(
            provider_id=provider_id,
            provider_class=ProviderClass.LOCAL_CACHE,
            display_name=provider_id.replace("_", " ").title(),
            capabilities=tuple(capabilities),
            priority=priority,
            authoritative=True,
            configured=_has_published_version(paths),
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    def fetch(self, request: MarketTruthRequest) -> ProviderDataset:
        if not self.paths.database.exists():
            raise MarketTruthProviderError("historical warehouse is absent")
        if request.dataset is DatasetKind.DAILY and request.price_mode is not self.mode:
            raise MarketTruthProviderError(
                f"provider requires {self.mode.value} price mode"
            )
        store = WarehouseStore(self.paths, read_only=True)
        version = store.latest_published_version()
        if version is None:
            raise MarketTruthProviderError(
                "warehouse has no explicitly published dataset version"
            )
        if (
            request.warehouse_version is not None
            and request.warehouse_version != version
        ):
            raise MarketTruthProviderError(
                f"requested warehouse version {request.warehouse_version} "
                "is unavailable"
            )
        records = self._records(store, request)
        if not records:
            raise MarketTruthProviderError("warehouse returned no matching records")
        end = request.end or request.as_of or datetime.now(tz=UTC)
        return ProviderDataset(
            request_id=request.request_id,
            provider_id=self.descriptor.provider_id,
            source="Project Alpha authoritative NSE/BSE historical warehouse",
            evidence_class=EvidenceClass.CACHED_AUTHORITATIVE,
            observed_at=end,
            records=records,
            reported_completeness=Decimal("1"),
            source_reference=f"warehouse:{version}:{self.mode.value}",
        )

    def _records(
        self, store: WarehouseStore, request: MarketTruthRequest
    ) -> tuple[MarketTruthRecord, ...]:
        if request.dataset is DatasetKind.DAILY:
            return self._daily(store, request)
        if request.dataset is DatasetKind.IDENTITY:
            return self._identity(store, request)
        if request.dataset is DatasetKind.CORPORATE_ACTIONS:
            return self._actions(store, request)
        if request.dataset is DatasetKind.CALENDAR:
            return self._calendar(store, request)
        if request.dataset is DatasetKind.UNIVERSE:
            return self._universe(store, request)
        if request.dataset is DatasetKind.INDEX:
            return self._indices(store, request)
        raise MarketTruthProviderError(
            f"warehouse does not support {request.dataset.value}"
        )

    def _daily(
        self, store: WarehouseStore, request: MarketTruthRequest
    ) -> tuple[MarketBar, ...]:
        start = None if request.start is None else request.start.date()
        end = None if request.end is None else request.end.date()
        if self.mode is PriceHistoryMode.RAW:
            rows = store.daily_records(symbols=request.symbols, start=start, end=end)
            return tuple(
                MarketBar(
                    symbol=item.symbol_as_traded,
                    observed_at=datetime.combine(
                        item.trading_date, time.min, tzinfo=UTC
                    ),
                    open_price=item.open,
                    high_price=item.high,
                    low_price=item.low,
                    close_price=item.close,
                    volume=item.volume,
                    interval=DatasetKind.DAILY,
                    exchange=item.exchange.value,
                    series=item.series,
                )
                for item in rows
            )
        mode = AdjustmentMode(self.mode.value)
        adjustment_as_of = (
            request.as_of.date()
            if self.mode is PriceHistoryMode.POINT_IN_TIME and request.as_of is not None
            else None
        )
        adjusted_rows = tuple(
            item
            for item in store.adjusted_records(mode, as_of=adjustment_as_of)
            if (not request.symbols or item.raw.symbol_as_traded in request.symbols)
            and (start is None or item.raw.trading_date >= start)
            and (end is None or item.raw.trading_date <= end)
        )
        return tuple(
            MarketBar(
                symbol=item.raw.symbol_as_traded,
                observed_at=datetime.combine(
                    item.raw.trading_date, time.min, tzinfo=UTC
                ),
                open_price=item.open,
                high_price=item.high,
                low_price=item.low,
                close_price=item.close,
                volume=item.volume,
                interval=DatasetKind.DAILY,
                exchange=item.raw.exchange.value,
                series=item.raw.series,
            )
            for item in adjusted_rows
        )

    @staticmethod
    def _identity(
        store: WarehouseStore, request: MarketTruthRequest
    ) -> tuple[SecurityIdentity, ...]:
        as_of = (request.as_of or request.end or datetime.now(tz=UTC)).date()
        return tuple(
            SecurityIdentity(
                symbol=item.symbol,
                series=item.series,
                isin=item.isin,
                security_id=item.security_id,
                status=(
                    SecurityStatus.DELISTED
                    if item.delisting_date and as_of > item.delisting_date
                    else SecurityStatus.SUSPENDED
                    if any(
                        start <= as_of and (end is None or as_of <= end)
                        for start, end in item.suspension_intervals
                    )
                    else SecurityStatus.ACTIVE
                ),
                effective_from=item.symbol_valid_from,
                effective_to=item.symbol_valid_to,
                continuity_id=item.security_id,
                authority=IdentityAuthority.EXCHANGE,
            )
            for item in store.identity_records()
            if (not request.symbols or item.symbol in request.symbols)
            and item.symbol_valid_from <= as_of
            and (item.symbol_valid_to is None or as_of <= item.symbol_valid_to)
        )

    @staticmethod
    def _actions(
        store: WarehouseStore, request: MarketTruthRequest
    ) -> tuple[CorporateAction, ...]:
        start = None if request.start is None else request.start.date()
        end = None if request.end is None else request.end.date()
        as_of = None if request.as_of is None else request.as_of.date()
        identities = {
            item.security_id: item.symbol for item in store.identity_records()
        }
        output: list[CorporateAction] = []
        for item in store.corporate_action_records(announced_as_of=as_of):
            symbol = identities.get(
                item.security_id, item.old_symbol or item.new_symbol or ""
            )
            event_date = item.ex_date or item.effective_date or item.announcement_date
            if request.symbols and symbol not in request.symbols:
                continue
            if start is not None and event_date < start:
                continue
            if end is not None and event_date > end:
                continue
            output.append(
                CorporateAction(
                    action_id=item.corporate_action_id,
                    security_id=item.security_id,
                    symbol=symbol,
                    action_type=_mte_action(item.action_type),
                    ex_date=event_date,
                    record_date=item.record_date,
                    ratio=(
                        None
                        if item.ratio_numerator is None
                        else f"{item.ratio_numerator}:{item.ratio_denominator}"
                    ),
                    predecessor_symbol=item.old_symbol,
                    successor_symbol=item.new_symbol,
                )
            )
        return tuple(output)

    @staticmethod
    def _calendar(
        store: WarehouseStore, request: MarketTruthRequest
    ) -> tuple[TradingSession, ...]:
        start = None if request.start is None else request.start.date()
        end = None if request.end is None else request.end.date()
        return tuple(
            TradingSession(
                session_date=item.session_date,
                session_type=(
                    TradingSessionType.HOLIDAY
                    if item.state is SessionState.HOLIDAY
                    else TradingSessionType.HALF
                    if item.state is SessionState.SPECIAL_SESSION
                    else TradingSessionType.FULL
                ),
                settlement_date=None,
                exchange=item.exchange.value,
            )
            for item in store.sessions()
            if (start is None or item.session_date >= start)
            and (end is None or item.session_date <= end)
        )

    @staticmethod
    def _universe(
        store: WarehouseStore, request: MarketTruthRequest
    ) -> tuple[UniverseObservation, ...]:
        as_of = (request.as_of or request.end or datetime.now(tz=UTC)).date()
        return tuple(
            UniverseObservation(
                security_id=item.security_id,
                symbol=item.symbol,
                exchange=item.exchange.value,
                observed_on=item.trading_date,
                series=item.series,
                listed=item.listed,
                suspended=item.suspended,
                tradable=item.tradable,
                eligible_for_research=item.eligible_for_research,
                eligibility_reason=item.eligibility_reason,
                identity_version=item.identity_version,
                universe_version=item.universe_version,
            )
            for item in store.universe(session_date=as_of)
            if not request.symbols or item.symbol in request.symbols
        )

    @staticmethod
    def _indices(
        store: WarehouseStore, request: MarketTruthRequest
    ) -> tuple[IndexObservation, ...]:
        start = None if request.start is None else request.start.date()
        end = None if request.end is None else request.end.date()
        return tuple(
            IndexObservation(
                index_id=item.index_id,
                observed_at=datetime.combine(item.trading_date, time.min, tzinfo=UTC),
                value=item.close,
            )
            for item in store.index_records()
            if (not request.symbols or item.index_id in request.symbols)
            and (start is None or item.trading_date >= start)
            and (end is None or item.trading_date <= end)
        )


def warehouse_market_truth_providers(
    paths: WarehousePaths,
) -> tuple[WarehouseMarketTruthProvider, ...]:
    return (
        WarehouseMarketTruthProvider(
            paths=paths,
            provider_id="NSE_BSE_RAW_WAREHOUSE",
            mode=PriceHistoryMode.RAW,
            priority=5,
            include_reference_data=True,
        ),
        WarehouseMarketTruthProvider(
            paths=paths,
            provider_id="NSE_BSE_ADJUSTED_WAREHOUSE",
            mode=PriceHistoryMode.ADJUSTED,
            priority=6,
            include_reference_data=False,
        ),
        WarehouseMarketTruthProvider(
            paths=paths,
            provider_id="NSE_BSE_TOTAL_RETURN_WAREHOUSE",
            mode=PriceHistoryMode.TOTAL_RETURN,
            priority=7,
            include_reference_data=False,
        ),
        WarehouseMarketTruthProvider(
            paths=paths,
            provider_id="NSE_BSE_POINT_IN_TIME_WAREHOUSE",
            mode=PriceHistoryMode.POINT_IN_TIME,
            priority=8,
            include_reference_data=False,
        ),
    )


def _mte_action(value: CorporateActionKind) -> CorporateActionType:
    if value is CorporateActionKind.STOCK_SPLIT:
        return CorporateActionType.SPLIT
    return CorporateActionType(value.value)


def _has_published_version(paths: WarehousePaths) -> bool:
    if not paths.database.exists():
        return False
    try:
        return (
            WarehouseStore(paths, read_only=True).latest_published_version() is not None
        )
    except (duckdb.Error, RuntimeError, OSError):
        return False


__all__ = ["WarehouseMarketTruthProvider", "warehouse_market_truth_providers"]
