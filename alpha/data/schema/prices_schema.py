import pandas as pd

PRICES_COLUMNS = [
    "symbol",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "exchange",
]


def enforce_prices_schema(df: pd.DataFrame) -> pd.DataFrame:
    """
    Hard contract with controlled defaults.

    Rules:
    - Missing critical market data → FAIL
    - Missing operational metadata (exchange) → DEFAULT (NSE)
    """

    df = df.copy()

    # --- critical validation ---
    critical_cols = [
        "symbol",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]

    missing_critical = [c for c in critical_cols if c not in df.columns]
    if missing_critical:
        raise ValueError(
            f"[SCHEMA VIOLATION] Missing critical columns: {missing_critical}"
        )

    # --- controlled default injection (only metadata) ---
    if "exchange" not in df.columns:
        df["exchange"] = "NSE"

    # reorder + enforce schema
    df = df[PRICES_COLUMNS]

    # strict typing enforcement
    df["symbol"] = df["symbol"].astype(str).str.strip()
    df["exchange"] = df["exchange"].astype(str)

    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="raise").dt.date

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="raise")

    return df
