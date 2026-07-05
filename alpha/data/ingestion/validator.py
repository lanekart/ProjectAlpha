import pandas as pd


class Validator:
    """
    Validates and enriches bhavcopy data.
    """

    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        required = ["symbol", "open", "close", "volume"]

        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"[VALIDATION] Missing columns: {missing}")

        # ----------------------------
        # CORE FEATURE ENGINEERING
        # ----------------------------
        df["momentum_score"] = (df["close"] - df["open"]) / df["open"]

        return df
