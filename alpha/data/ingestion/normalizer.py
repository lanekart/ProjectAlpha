from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True, slots=True)
class SchemaDetectionResult:
    """Identifies the external market data schema represented by a DataFrame."""

    schema_name: str


class Normalizer:
    """
    Converts supported external bhavcopy formats into Project Alpha's
    canonical daily market data schema.

    Supported input schemas
    -----------------------
    - Legacy NSE CM bhavcopy CSV
    - NSE CM UDiFF Common Bhavcopy Final CSV

    Canonical output columns include:
    - symbol
    - trade_date
    - open
    - high
    - low
    - close
    - volume
    - turnover, when available
    - exchange
    """

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize a raw bhavcopy DataFrame into canonical columns."""

        normalized = df.copy()
        normalized.columns = [
            _normalize_column_name(column) for column in normalized.columns
        ]

        detection = _detect_schema(normalized)
        if detection.schema_name == "udiff":
            return _normalize_udiff(normalized)
        if detection.schema_name == "legacy":
            return _normalize_legacy(normalized)

        raise ValueError("[NORMALIZER] unsupported market data schema")


def _normalize_column_name(column: object) -> str:
    return str(column).strip().replace(" ", "").replace("_", "").lower()


LEGACY_RENAME_MAP: Mapping[str, str] = {
    "symbol": "symbol",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "tottrdqty": "volume",
    "totaltradedquantity": "volume",
    "tottrdval": "turnover",
    "prevclose": "prev_close",
    "timestamp": "trade_date",
    "trade_date": "trade_date",
}

UDIFF_RENAME_MAP: Mapping[str, str] = {
    "tradDt": "trade_date",
    "bizDt": "business_date",
    "tckrSymb": "symbol",
    "sctySrs": "series",
    "sgmt": "segment",
    "opnPric": "open",
    "hghPric": "high",
    "lwPric": "low",
    "clsPric": "close",
    "lastPric": "last",
    "prvsClsgPric": "prev_close",
    "ttlTradgVol": "volume",
    "ttlTrfVal": "turnover",
    "ttlNbOfTxsExctd": "trades",
    "isin": "isin",
}

# Lower-case lookup because transform normalizes incoming column names.
UDIFF_RENAME_LOOKUP: Mapping[str, str] = {
    _normalize_column_name(source): target
    for source, target in UDIFF_RENAME_MAP.items()
}
LEGACY_RENAME_LOOKUP: Mapping[str, str] = {
    _normalize_column_name(source): target
    for source, target in LEGACY_RENAME_MAP.items()
}

REQUIRED_CANONICAL_COLUMNS = (
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
)


def _detect_schema(df: pd.DataFrame) -> SchemaDetectionResult:
    columns = set(df.columns)

    udiff_markers = {
        "tckrsymb",
        "traddt",
        "opnpric",
        "hghpric",
        "lwpric",
        "clspric",
        "ttltradgvol",
    }
    if udiff_markers.issubset(columns):
        return SchemaDetectionResult(schema_name="udiff")

    legacy_markers = {"symbol", "open", "high", "low", "close"}
    legacy_date_markers = {"timestamp", "trade_date"}
    if legacy_markers.issubset(columns) and columns.intersection(legacy_date_markers):
        return SchemaDetectionResult(schema_name="legacy")

    return SchemaDetectionResult(schema_name="unknown")


def _normalize_legacy(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.rename(columns=LEGACY_RENAME_LOOKUP).copy()
    normalized = _ensure_required_columns(normalized)
    normalized = _coerce_canonical_types(normalized)
    return normalized


def _normalize_udiff(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.rename(columns=UDIFF_RENAME_LOOKUP).copy()

    if "series" in normalized.columns:
        normalized = normalized[normalized["series"].astype(str).str.strip() == "EQ"]

    normalized["exchange"] = "NSE"
    normalized = _ensure_required_columns(normalized)
    normalized = _coerce_canonical_types(normalized)
    return normalized


def _ensure_required_columns(df: pd.DataFrame) -> pd.DataFrame:
    missing = [
        column for column in REQUIRED_CANONICAL_COLUMNS if column not in df.columns
    ]
    if missing:
        raise ValueError(f"[NORMALIZER] Missing canonical columns: {missing}")

    return df


def _coerce_canonical_types(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()

    normalized["symbol"] = normalized["symbol"].astype(str).str.strip()
    normalized["trade_date"] = pd.to_datetime(
        normalized["trade_date"],
        errors="coerce",
    )

    numeric_columns = ("open", "high", "low", "close", "volume", "turnover", "trades")
    for column in numeric_columns:
        if column in normalized.columns:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

    normalized = normalized.dropna(
        subset=["symbol", "trade_date", "open", "high", "low", "close", "volume"],
    )

    if "exchange" not in normalized.columns:
        normalized["exchange"] = "NSE"

    return normalized


__all__ = ["Normalizer", "SchemaDetectionResult"]
