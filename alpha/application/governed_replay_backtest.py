"""Governed backtest entrypoint backed by canonical historical replay truth."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
from alpha.analysis.signals.daily_report import DailyMarketReport
from alpha.application.backtest import (
    BacktestApplicationService,
    BacktestRun,
    BacktestSummary,
    MarketReportGenerator,
)
from alpha.application.ingestion import IngestionService
from alpha.backtest.broker import BrokerSimulator
from alpha.backtest.engine import BacktestEngine
from alpha.backtest.equity_curve import EquityCurveBuilder
from alpha.backtest.ledger import ExecutionLedger
from alpha.backtest.models import BacktestOrder
from alpha.market.resolver import TradingDateResolver
from alpha.market_truth.historical_service import (
    MarketTruthArchiveDownloader as BhavcopyDownloader,
)
from alpha.recovery.consumer_attestation import (
    CanonicalReplayConsumerAttestation,
    export_consumer_attestations,
)
from alpha.recovery.consumer_guard import CanonicalReplayConsumerGuard
from alpha.recovery.replay_frame import CanonicalReplayFrameAdapter


class CanonicalReplayIngestionService(IngestionService):
    """Decorate ingestion so every non-empty frame is canonicalized first."""

    def __init__(
        self,
        source: IngestionService,
        canonicalizer: CanonicalReplayFrameAdapter,
    ) -> None:
        self._source = source
        self._canonicalizer = canonicalizer
        self._guard = CanonicalReplayConsumerGuard()
        self._attestations: list[CanonicalReplayConsumerAttestation] = []

    @property
    def attestations(self) -> tuple[CanonicalReplayConsumerAttestation, ...]:
        """Return immutable attestations for frames released to the consumer."""

        return tuple(self._attestations)

    def ingest(self, zip_path: Path) -> pd.DataFrame:
        frame = self._source.ingest(zip_path)
        if frame.empty:
            return frame.copy()
        trading_day = _single_trade_date(frame)
        return self._canonicalize(frame, trading_day)

    def load_prices_for_trade_date(self, trade_date: date) -> pd.DataFrame:
        frame = self._source.load_prices_for_trade_date(trade_date)
        if frame.empty:
            return frame.copy()
        return self._canonicalize(frame, trade_date)

    def _canonicalize(self, frame: pd.DataFrame, trade_date: date) -> pd.DataFrame:
        result = self._canonicalizer.canonicalize(
            frame,
            trade_date=trade_date,
            as_of=trade_date,
        )
        if not result.audit.passed:
            raise ValueError("canonical replay audit did not pass")
        attestation = self._guard.validate(
            result.frame,
            expected_trade_date=trade_date,
            expected_as_of=trade_date,
        )
        if attestation != result.attestation:
            raise ValueError("canonical replay attestation changed before consumption")
        self._attestations.append(attestation)
        return result.frame.copy()


@dataclass(frozen=True, slots=True)
class GovernedReplayBacktestRun:
    """Backtest result coupled to the replay attestations it consumed."""

    backtest: BacktestRun
    replay_attestations: tuple[CanonicalReplayConsumerAttestation, ...]

    def __post_init__(self) -> None:
        if not self.replay_attestations:
            raise ValueError("governed backtest requires replay attestations")
        if any(
            not attestation.canonical_replay_enforced
            for attestation in self.replay_attestations
        ):
            raise ValueError("governed backtest contains an unenforced replay frame")

    @property
    def summary(self) -> BacktestSummary:
        """Expose the existing backtest summary contract."""

        return self.backtest.summary

    @property
    def orders(self) -> tuple[BacktestOrder, ...]:
        """Expose the existing immutable order sequence."""

        return self.backtest.orders

    @property
    def canonical_snapshot_sha256s(self) -> tuple[str, ...]:
        """Return the distinct immutable replay snapshots consumed."""

        return tuple(
            sorted(
                {
                    attestation.canonical_snapshot_sha256
                    for attestation in self.replay_attestations
                }
            )
        )

    @property
    def canonical_frame_sha256s(self) -> tuple[str, ...]:
        """Return the distinct consumer-frame digests released to the backtest."""

        return tuple(
            sorted(
                {
                    attestation.canonical_frame_sha256
                    for attestation in self.replay_attestations
                }
            )
        )


@dataclass(slots=True)
class GovernedReplayBacktestService:
    """Run the existing backtest pipeline with canonical replay enforced."""

    canonicalizer: CanonicalReplayFrameAdapter
    resolver: TradingDateResolver = field(default_factory=TradingDateResolver)
    downloader: BhavcopyDownloader = field(default_factory=BhavcopyDownloader)
    ingestion: IngestionService = field(default_factory=IngestionService)
    report: MarketReportGenerator = field(default_factory=DailyMarketReport)
    engine: BacktestEngine = field(default_factory=BacktestEngine)
    broker: BrokerSimulator = field(default_factory=BrokerSimulator)
    ledger: ExecutionLedger = field(default_factory=ExecutionLedger)
    equity_curve_builder: EquityCurveBuilder = field(default_factory=EquityCurveBuilder)

    def run(
        self,
        *,
        strategy: str,
        start: date,
        end: date,
        starting_cash: Decimal,
    ) -> GovernedReplayBacktestRun:
        governed_ingestion = CanonicalReplayIngestionService(
            source=self.ingestion,
            canonicalizer=self.canonicalizer,
        )
        service = BacktestApplicationService(
            resolver=self.resolver,
            downloader=self.downloader,
            ingestion=governed_ingestion,
            report=self.report,
            engine=self.engine,
            broker=self.broker,
            ledger=self.ledger,
            equity_curve_builder=self.equity_curve_builder,
        )
        backtest = service.run(
            strategy=strategy,
            start=start,
            end=end,
            starting_cash=starting_cash,
        )
        return GovernedReplayBacktestRun(
            backtest=backtest,
            replay_attestations=governed_ingestion.attestations,
        )


def export_governed_replay_backtest_attestations(
    run: GovernedReplayBacktestRun,
    output: Path,
) -> tuple[Path, ...]:
    """Export the exact replay proofs associated with a governed backtest."""

    return export_consumer_attestations(run.replay_attestations, output)


def _single_trade_date(frame: pd.DataFrame) -> date:
    if "trade_date" not in frame.columns:
        raise ValueError("governed replay frame is missing trade_date")
    parsed = pd.to_datetime(frame["trade_date"], errors="coerce")
    if parsed.isna().any():
        raise ValueError("governed replay frame contains invalid trade_date values")
    dates = {item.date() for item in parsed}
    if len(dates) != 1:
        rendered = ", ".join(sorted(item.isoformat() for item in dates))
        raise ValueError(f"governed replay frame spans multiple dates: {rendered}")
    return next(iter(dates))
