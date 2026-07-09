import pandas as pd
import pytest

from alpha.data.ingestion.normalizer import Normalizer


def test_normalizer_supports_legacy_bhavcopy_schema() -> None:
    raw = pd.DataFrame(
        [
            {
                "SYMBOL": "ABC",
                "OPEN": 100,
                "HIGH": 110,
                "LOW": 95,
                "CLOSE": 108,
                "TOTTRDQTY": 1000,
                "TOTTRDVAL": 108000,
                "TIMESTAMP": "15-JAN-2024",
            }
        ]
    )

    normalized = Normalizer().transform(raw)

    assert normalized.loc[0, "symbol"] == "ABC"
    assert normalized.loc[0, "open"] == 100
    assert normalized.loc[0, "high"] == 110
    assert normalized.loc[0, "low"] == 95
    assert normalized.loc[0, "close"] == 108
    assert normalized.loc[0, "volume"] == 1000
    assert normalized.loc[0, "exchange"] == "NSE"
    assert normalized.loc[0, "trade_date"] == pd.Timestamp("2024-01-15")


def test_normalizer_canonicalizes_optional_sector_metadata() -> None:
    raw = pd.DataFrame(
        [
            {
                "SYMBOL": "ABC",
                "Sector Name": " banks ",
                "OPEN": 100,
                "HIGH": 110,
                "LOW": 95,
                "CLOSE": 108,
                "TOTTRDQTY": 1000,
                "TIMESTAMP": "15-JAN-2024",
            }
        ]
    )

    normalized = Normalizer().transform(raw)

    assert normalized.loc[0, "sector"] == "BANKS"


def test_normalizer_supports_udiff_common_bhavcopy_schema() -> None:
    raw = pd.DataFrame(
        [
            {
                "TradDt": "2026-07-06",
                "BizDt": "2026-07-06",
                "Sgmt": "CM",
                "TckrSymb": "RELIANCE",
                "SctySrs": "EQ",
                "OpnPric": "1400.50",
                "HghPric": "1425.00",
                "LwPric": "1390.00",
                "ClsPric": "1410.25",
                "TtlTradgVol": "1234567",
                "TtlTrfVal": "1740000000.50",
                "TtlNbOfTxsExctd": "25000",
            }
        ]
    )

    normalized = Normalizer().transform(raw)

    assert normalized.loc[0, "symbol"] == "RELIANCE"
    assert normalized.loc[0, "trade_date"] == pd.Timestamp("2026-07-06")
    assert normalized.loc[0, "open"] == 1400.50
    assert normalized.loc[0, "high"] == 1425.00
    assert normalized.loc[0, "low"] == 1390.00
    assert normalized.loc[0, "close"] == 1410.25
    assert normalized.loc[0, "volume"] == 1234567
    assert normalized.loc[0, "turnover"] == 1740000000.50
    assert normalized.loc[0, "trades"] == 25000
    assert normalized.loc[0, "exchange"] == "NSE"


def test_normalizer_filters_udiff_to_equity_series() -> None:
    raw = pd.DataFrame(
        [
            {
                "TradDt": "2026-07-06",
                "TckrSymb": "ABC",
                "SctySrs": "EQ",
                "OpnPric": 100,
                "HghPric": 110,
                "LwPric": 95,
                "ClsPric": 105,
                "TtlTradgVol": 1000,
            },
            {
                "TradDt": "2026-07-06",
                "TckrSymb": "ABC-BE",
                "SctySrs": "BE",
                "OpnPric": 100,
                "HghPric": 110,
                "LwPric": 95,
                "ClsPric": 105,
                "TtlTradgVol": 1000,
            },
        ]
    )

    normalized = Normalizer().transform(raw)

    assert normalized["symbol"].tolist() == ["ABC"]


def test_normalizer_rejects_unknown_schema() -> None:
    raw = pd.DataFrame([{"foo": "bar"}])

    with pytest.raises(ValueError, match="unsupported market data schema"):
        Normalizer().transform(raw)
