import pandas as pd


class Normalizer:
    """
    Converts raw bhavcopy format → staging schema.
    """

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        # normalize column names
        df.columns = [c.strip().lower() for c in df.columns]

        # bhavcopy mappings
        rename_map = {
            "tottrdqty": "volume",
            "totaltradedquantity": "volume",
            "tottrdval": "turnover",
            "prevclose": "prev_close",
            "timestamp": "trade_date",
        }

        df = df.rename(columns=rename_map)

        # trade_date parsing (bhavcopy format fallback)
        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
        elif "timestamp" in df.columns:
            df["trade_date"] = pd.to_datetime(df["timestamp"], errors="coerce")
        else:
            raise ValueError("[NORMALIZER] trade_date not found in input")

        return df
