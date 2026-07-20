from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from alpha.historical_truth.canonical import (
    CanonicalCandle,
    CanonicalPointInTimeWarehouse,
)


@dataclass(frozen=True, slots=True)
class SnapshotAvailability:
    candles: bool
    identity: bool
    corporate_actions: bool
    delivery: bool = False
    indices: bool = False
    vix: bool = False


@dataclass(frozen=True, slots=True)
class SnapshotMetadata:
    snapshot_version: str
    trading_date: date
    exchange: str
    generated_at: datetime
    source_database: str
    symbol_count: int
    total_volume: int
    completeness_score: float
    availability: SnapshotAvailability


@dataclass(frozen=True, slots=True)
class ImmutableMarketSnapshot:
    metadata: SnapshotMetadata
    candles: tuple[CanonicalCandle, ...]
    content_sha256: str


@dataclass(frozen=True, slots=True)
class SnapshotVerification:
    valid: bool
    expected_sha256: str
    observed_sha256: str
    reason: str | None = None


class PointInTimeSnapshotEngine:
    """Build, persist, load, and verify immutable historical market snapshots."""

    SNAPSHOT_VERSION = "1.0"

    def __init__(
        self,
        warehouse: CanonicalPointInTimeWarehouse,
        snapshot_root: Path,
    ) -> None:
        self.warehouse = warehouse
        self.snapshot_root = snapshot_root

    def build(
        self,
        trading_date: date,
        *,
        exchange: str = "nse",
        generated_at: datetime | None = None,
    ) -> ImmutableMarketSnapshot:
        market = self.warehouse.snapshot(trading_date, exchange=exchange)
        availability = SnapshotAvailability(
            candles=bool(market.candles),
            identity=any(candle.isin is not None for candle in market.candles),
            corporate_actions=self._has_corporate_actions(
                trading_date,
                exchange=exchange,
            ),
        )
        score = self._completeness_score(availability)
        metadata = SnapshotMetadata(
            snapshot_version=self.SNAPSHOT_VERSION,
            trading_date=trading_date,
            exchange=exchange.lower(),
            generated_at=generated_at or datetime.now(UTC),
            source_database=str(self.warehouse.database_path),
            symbol_count=market.symbol_count,
            total_volume=market.total_volume,
            completeness_score=score,
            availability=availability,
        )
        checksum = self._content_sha256(metadata, market.candles)
        return ImmutableMarketSnapshot(
            metadata=metadata,
            candles=market.candles,
            content_sha256=checksum,
        )

    def persist(self, snapshot: ImmutableMarketSnapshot) -> Path:
        path = self.path_for(
            snapshot.metadata.trading_date,
            exchange=snapshot.metadata.exchange,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._serialise(snapshot)
        rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            if existing != rendered:
                raise FileExistsError(
                    f"immutable snapshot already exists with different content: {path}"
                )
            return path
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(path)
        return path

    def load(
        self,
        trading_date: date,
        *,
        exchange: str = "nse",
    ) -> ImmutableMarketSnapshot:
        path = self.path_for(trading_date, exchange=exchange)
        payload = json.loads(path.read_text(encoding="utf-8"))
        metadata_payload = payload["metadata"]
        availability_payload = metadata_payload["availability"]
        metadata = SnapshotMetadata(
            snapshot_version=str(metadata_payload["snapshot_version"]),
            trading_date=date.fromisoformat(metadata_payload["trading_date"]),
            exchange=str(metadata_payload["exchange"]),
            generated_at=datetime.fromisoformat(metadata_payload["generated_at"]),
            source_database=str(metadata_payload["source_database"]),
            symbol_count=int(metadata_payload["symbol_count"]),
            total_volume=int(metadata_payload["total_volume"]),
            completeness_score=float(metadata_payload["completeness_score"]),
            availability=SnapshotAvailability(
                candles=bool(availability_payload["candles"]),
                identity=bool(availability_payload["identity"]),
                corporate_actions=bool(
                    availability_payload["corporate_actions"]
                ),
                delivery=bool(availability_payload["delivery"]),
                indices=bool(availability_payload["indices"]),
                vix=bool(availability_payload["vix"]),
            ),
        )
        candles = tuple(
            CanonicalCandle(
                trading_date=date.fromisoformat(item["trading_date"]),
                exchange=str(item["exchange"]),
                symbol=str(item["symbol"]),
                series=str(item["series"]),
                isin=str(item["isin"]) if item["isin"] is not None else None,
                open_price=float(item["open_price"]),
                high_price=float(item["high_price"]),
                low_price=float(item["low_price"]),
                close_price=float(item["close_price"]),
                volume=int(item["volume"]),
            )
            for item in payload["candles"]
        )
        return ImmutableMarketSnapshot(
            metadata=metadata,
            candles=candles,
            content_sha256=str(payload["content_sha256"]),
        )

    def verify(self, snapshot: ImmutableMarketSnapshot) -> SnapshotVerification:
        observed = self._content_sha256(snapshot.metadata, snapshot.candles)
        valid = observed == snapshot.content_sha256
        return SnapshotVerification(
            valid=valid,
            expected_sha256=snapshot.content_sha256,
            observed_sha256=observed,
            reason=None if valid else "snapshot content checksum mismatch",
        )

    def path_for(self, trading_date: date, *, exchange: str = "nse") -> Path:
        return (
            self.snapshot_root
            / exchange.lower()
            / trading_date.strftime("%Y")
            / f"{trading_date.isoformat()}.json"
        )

    def _has_corporate_actions(
        self,
        trading_date: date,
        *,
        exchange: str,
    ) -> bool:
        self.warehouse.initialise()
        with self.warehouse._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*)
                FROM corporate_action
                WHERE exchange = ? AND ex_date <= ?
                """,
                [exchange.lower(), trading_date],
            ).fetchone()
        return bool(row and int(row[0]) > 0)

    @staticmethod
    def _completeness_score(availability: SnapshotAvailability) -> float:
        required = (
            availability.candles,
            availability.identity,
            availability.corporate_actions,
            availability.delivery,
            availability.indices,
            availability.vix,
        )
        return round(sum(required) / len(required), 6)

    @staticmethod
    def _content_sha256(
        metadata: SnapshotMetadata,
        candles: tuple[CanonicalCandle, ...],
    ) -> str:
        payload = {
            "metadata": PointInTimeSnapshotEngine._metadata_payload(metadata),
            "candles": [
                PointInTimeSnapshotEngine._candle_payload(candle)
                for candle in candles
            ],
        }
        rendered = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(rendered.encode("utf-8")).hexdigest()

    @staticmethod
    def _serialise(snapshot: ImmutableMarketSnapshot) -> dict[str, object]:
        return {
            "metadata": PointInTimeSnapshotEngine._metadata_payload(
                snapshot.metadata
            ),
            "candles": [
                PointInTimeSnapshotEngine._candle_payload(candle)
                for candle in snapshot.candles
            ],
            "content_sha256": snapshot.content_sha256,
        }

    @staticmethod
    def _metadata_payload(metadata: SnapshotMetadata) -> dict[str, object]:
        payload = asdict(metadata)
        payload["trading_date"] = metadata.trading_date.isoformat()
        payload["generated_at"] = metadata.generated_at.isoformat()
        payload["availability"] = asdict(metadata.availability)
        return payload

    @staticmethod
    def _candle_payload(candle: CanonicalCandle) -> dict[str, object]:
        payload = asdict(candle)
        payload["trading_date"] = candle.trading_date.isoformat()
        return payload
