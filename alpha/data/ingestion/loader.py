from pathlib import Path

import pandas as pd


class CSVLoader:
    """
    Loads an extracted NSE bhavcopy CSV into a Pandas DataFrame.
    """

    def __init__(self) -> None:
        pass

    def load(self, csv_path: Path) -> pd.DataFrame:
        """
        Load a CSV file into a DataFrame.

        Args:
            csv_path: Path to the extracted bhavcopy CSV.

        Returns:
            A normalized pandas DataFrame.
        """

        if not csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")

        df = pd.read_csv(csv_path)

        # Basic non-destructive cleanup
        df.columns = [column.strip().lower() for column in df.columns]

        return df
