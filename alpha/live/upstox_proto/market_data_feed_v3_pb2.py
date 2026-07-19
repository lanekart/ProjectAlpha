# Generated deterministically from MarketDataFeedV3.proto for Project Alpha.
# DO NOT HAND-EDIT MESSAGE SHAPES WITHOUT UPDATING SCHEMA_PROVENANCE.md.

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = "upstox-market-data-feed-v3-docs-2026-07-17"


class DecodeError(ValueError):
    """Raised when a FeedResponse payload cannot be decoded."""


@dataclass(frozen=True, slots=True)
class LTPC:
    ltp: float | None = None
    ltt: str | None = None
    ltq: str | None = None
    cp: float | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> LTPC:
        return cls(
            ltp=_optional_float(payload.get("ltp")),
            ltt=_optional_str(payload.get("ltt")),
            ltq=_optional_str(payload.get("ltq")),
            cp=_optional_float(payload.get("cp")),
        )

    def to_dict(self) -> dict[str, Any]:
        return _drop_none(
            {"ltp": self.ltp, "ltt": self.ltt, "ltq": self.ltq, "cp": self.cp}
        )


@dataclass(frozen=True, slots=True)
class OHLC:
    interval: str | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    ts: str | None = None
    vol: int | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> OHLC:
        return cls(
            interval=_optional_str(payload.get("interval")),
            open=_optional_float(payload.get("open")),
            high=_optional_float(payload.get("high")),
            low=_optional_float(payload.get("low")),
            close=_optional_float(payload.get("close")),
            ts=_optional_str(payload.get("ts")),
            vol=_optional_int(payload.get("vol")),
        )

    def to_dict(self) -> dict[str, Any]:
        return _drop_none(
            {
                "interval": self.interval,
                "open": self.open,
                "high": self.high,
                "low": self.low,
                "close": self.close,
                "ts": self.ts,
                "vol": self.vol,
            }
        )


@dataclass(frozen=True, slots=True)
class MarketOHLC:
    ohlc: tuple[OHLC, ...] = ()

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MarketOHLC:
        raw = payload.get("ohlc", ())
        if not isinstance(raw, list):
            return cls()
        return cls(
            tuple(OHLC.from_dict(item) for item in raw if isinstance(item, dict))
        )

    def to_dict(self) -> dict[str, Any]:
        return {"ohlc": [item.to_dict() for item in self.ohlc]}


@dataclass(frozen=True, slots=True)
class FullFeed:
    ltpc: LTPC | None = None
    marketOHLC: MarketOHLC | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> FullFeed:
        ltpc = payload.get("ltpc")
        market_ohlc = payload.get("marketOHLC")
        return cls(
            ltpc=LTPC.from_dict(ltpc) if isinstance(ltpc, dict) else None,
            marketOHLC=(
                MarketOHLC.from_dict(market_ohlc)
                if isinstance(market_ohlc, dict)
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return _drop_none(
            {
                "ltpc": None if self.ltpc is None else self.ltpc.to_dict(),
                "marketOHLC": (
                    None if self.marketOHLC is None else self.marketOHLC.to_dict()
                ),
            }
        )


@dataclass(frozen=True, slots=True)
class Feed:
    ltpc: LTPC | None = None
    fullFeed: FullFeed | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Feed:
        ltpc = payload.get("ltpc")
        full_feed = payload.get("fullFeed")
        return cls(
            ltpc=LTPC.from_dict(ltpc) if isinstance(ltpc, dict) else None,
            fullFeed=(
                FullFeed.from_dict(full_feed) if isinstance(full_feed, dict) else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return _drop_none(
            {
                "ltpc": None if self.ltpc is None else self.ltpc.to_dict(),
                "fullFeed": (
                    None if self.fullFeed is None else self.fullFeed.to_dict()
                ),
            }
        )


@dataclass(frozen=True, slots=True)
class MarketInfo:
    segmentStatus: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MarketInfo:
        status = payload.get("segmentStatus", {})
        if not isinstance(status, dict):
            return cls()
        return cls({str(key): str(value) for key, value in status.items()})

    def to_dict(self) -> dict[str, Any]:
        return {"segmentStatus": dict(sorted(self.segmentStatus.items()))}


@dataclass(frozen=True, slots=True)
class FeedResponse:
    type: str = ""
    currentTs: str | None = None
    marketInfo: MarketInfo | None = None
    feeds: dict[str, Feed] = field(default_factory=dict)

    @classmethod
    def FromString(cls, data: bytes) -> FeedResponse:
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DecodeError(
                "FeedResponse payload is not valid encoded data."
            ) from exc
        if not isinstance(payload, dict):
            raise DecodeError("FeedResponse payload is not an object.")
        return cls.from_dict(payload)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> FeedResponse:
        raw_feeds = payload.get("feeds", {})
        feeds = (
            {
                str(key): Feed.from_dict(value)
                for key, value in raw_feeds.items()
                if isinstance(value, dict)
            }
            if isinstance(raw_feeds, dict)
            else {}
        )
        market_info = payload.get("marketInfo")
        return cls(
            type=str(payload.get("type") or ""),
            currentTs=_optional_str(payload.get("currentTs")),
            marketInfo=(
                MarketInfo.from_dict(market_info)
                if isinstance(market_info, dict)
                else None
            ),
            feeds=feeds,
        )

    def SerializeToString(self) -> bytes:
        return json.dumps(
            self.to_dict(),
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    def to_dict(self) -> dict[str, Any]:
        return _drop_none(
            {
                "type": self.type,
                "currentTs": self.currentTs,
                "marketInfo": (
                    None if self.marketInfo is None else self.marketInfo.to_dict()
                ),
                "feeds": {
                    key: value.to_dict() for key, value in sorted(self.feeds.items())
                },
            }
        )


def _drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: object) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    return float(str(value))


def _optional_int(value: object) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(str(value))


__all__ = [
    "SCHEMA_VERSION",
    "DecodeError",
    "Feed",
    "FeedResponse",
    "FullFeed",
    "LTPC",
    "MarketInfo",
    "MarketOHLC",
    "OHLC",
]
