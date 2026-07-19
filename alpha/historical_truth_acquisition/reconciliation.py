from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb

from alpha.historical_truth_acquisition.models import (
    DiscrepancyType,
    ReconciliationFinding,
    ReconciliationSummary,
    stable_hash,
)
from alpha.market_truth.warehouse import HistoricalMarketWarehouse


@dataclass(frozen=True, slots=True)
class PriceObservation:
    source: str
    observation_key: str
    observed_on: date
    symbol: str
    close: Decimal
    volume: Decimal


class HistoricalTruthReconciler:
    """Compare sources without choosing a winner or mutating observations."""

    def __init__(
        self,
        warehouse: HistoricalMarketWarehouse,
        *,
        legacy_database: Path = Path("data/ingestion.duckdb"),
    ) -> None:
        self.warehouse = warehouse
        self.legacy_database = legacy_database

    def reconcile(self) -> ReconciliationSummary:
        nse = self._candidate("NSE")
        bse = self._candidate("BSE")
        candidate_rows = (*nse, *bse)
        sources = {
            "NSE": nse,
            "BSE": bse,
            "LEGACY": self._legacy(candidate_rows) if candidate_rows else (),
        }
        findings: list[ReconciliationFinding] = []
        for source, observations in sources.items():
            if not observations:
                findings.append(
                    _finding(
                        DiscrepancyType.SOURCE_UNAVAILABLE,
                        "daily-market-history",
                        source,
                        (source,),
                        "WARNING",
                        f"{source} has no comparable observations in this candidate.",
                    )
                )
        available = {
            source: {item.observation_key: item for item in rows}
            for source, rows in sources.items()
            if rows
        }
        keys = tuple(
            sorted(set().union(*(set(rows) for rows in available.values())))
            if available
            else ()
        )
        matching = 0
        for key in keys:
            present = {
                source: records[key]
                for source, records in available.items()
                if key in records
            }
            missing = tuple(sorted(set(available) - set(present)))
            if missing:
                findings.append(
                    _finding(
                        DiscrepancyType.MISSING_OBSERVATION,
                        "daily-market-history",
                        key,
                        tuple(sorted(available)),
                        "WARNING",
                        "Missing from: " + ", ".join(missing),
                    )
                )
            if len(present) < 2:
                continue
            price_values = tuple(item.close for item in present.values())
            volume_values = tuple(item.volume for item in present.values())
            mismatched = False
            if max(price_values) - min(price_values) > Decimal("0.01"):
                mismatched = True
                findings.append(
                    _finding(
                        DiscrepancyType.PRICE_MISMATCH,
                        "daily-market-history",
                        key,
                        tuple(sorted(present)),
                        "ERROR",
                        "Close prices differ by more than INR 0.01.",
                    )
                )
            largest_volume = max(volume_values)
            if largest_volume > 0:
                difference = (largest_volume - min(volume_values)) / largest_volume
                if difference > Decimal("0.01"):
                    mismatched = True
                    findings.append(
                        _finding(
                            DiscrepancyType.VOLUME_MISMATCH,
                            "daily-market-history",
                            key,
                            tuple(sorted(present)),
                            "ERROR",
                            "Volumes differ by more than one percent.",
                        )
                    )
            if not mismatched and not missing:
                matching += 1
        return ReconciliationSummary(
            compared_observations=len(keys),
            matching_observations=matching,
            findings=tuple(
                sorted(
                    findings,
                    key=lambda item: (item.discrepancy_type, item.finding_id),
                )
            ),
            automatic_overwrites=0,
        )

    def _candidate(self, exchange: str) -> tuple[PriceObservation, ...]:
        with self.warehouse.store.connection() as database:
            rows = database.execute(
                """
                SELECT trading_date, UPPER(symbol_as_traded), close, volume
                FROM canonical_daily
                WHERE exchange = ?
                ORDER BY trading_date, symbol_as_traded
                """,
                (exchange,),
            ).fetchall()
        return tuple(
            PriceObservation(
                source=exchange,
                observation_key=f"{row[0]}|{str(row[1]).upper()}",
                observed_on=row[0],
                symbol=str(row[1]).upper(),
                close=Decimal(str(row[2])),
                volume=Decimal(str(row[3])),
            )
            for row in rows
            if isinstance(row[0], date)
        )

    def _legacy(
        self, candidate_rows: tuple[PriceObservation, ...]
    ) -> tuple[PriceObservation, ...]:
        if not self.legacy_database.exists():
            return ()
        start = min(item.observed_on for item in candidate_rows)
        end = max(item.observed_on for item in candidate_rows)
        symbols = tuple(sorted({item.symbol for item in candidate_rows}))
        try:
            with duckdb.connect(str(self.legacy_database), read_only=True) as database:
                tables = {
                    str(row[0]) for row in database.execute("SHOW TABLES").fetchall()
                }
                if "daily_prices" not in tables:
                    return ()
                rows = database.execute(
                    """
                    SELECT trade_date, UPPER(symbol), close, volume
                    FROM daily_prices
                    WHERE trade_date BETWEEN ? AND ?
                      AND UPPER(symbol) IN (SELECT UNNEST(?))
                    ORDER BY trade_date, symbol
                    """,
                    (start, end, list(symbols)),
                ).fetchall()
        except duckdb.Error:
            return ()
        return tuple(
            PriceObservation(
                source="LEGACY",
                observation_key=f"{row[0]}|{str(row[1]).upper()}",
                observed_on=row[0],
                symbol=str(row[1]).upper(),
                close=Decimal(str(row[2])),
                volume=Decimal(str(row[3])),
            )
            for row in rows
            if isinstance(row[0], date) and row[2] is not None and row[3] is not None
        )


def _finding(
    discrepancy_type: DiscrepancyType,
    dataset_id: str,
    observation_key: str,
    sources: tuple[str, ...],
    severity: str,
    explanation: str,
) -> ReconciliationFinding:
    finding_id = (
        "hta-reconciliation-"
        + stable_hash(
            (discrepancy_type.value, dataset_id, observation_key, sources, explanation)
        )[:24]
    )
    return ReconciliationFinding(
        finding_id=finding_id,
        discrepancy_type=discrepancy_type,
        dataset_id=dataset_id,
        observation_key=observation_key,
        sources=sources,
        severity=severity,
        explanation=explanation,
    )


__all__ = ["HistoricalTruthReconciler", "PriceObservation"]
