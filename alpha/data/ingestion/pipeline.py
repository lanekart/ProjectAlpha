from pathlib import Path

import pandas as pd

from alpha.data.ingestion.extractor import ArchiveExtractor
from alpha.data.ingestion.normalizer import Normalizer
from alpha.data.ingestion.validator import Validator
from alpha.data.repositories.audit import AuditRepository
from alpha.data.repositories.database import Database


class BhavcopyIngestionPipeline:
    """
    Fault-tolerant ingestion pipeline.
    """

    def __init__(self, db: Database) -> None:
        self.db = db
        self.audit = AuditRepository(db)
        self.extractor = ArchiveExtractor()
        self.normalizer = Normalizer()
        self.validator = Validator()

    def run(self, zip_path: Path) -> pd.DataFrame:
        file_name = zip_path.name

        # -------------------------
        # SKIP IF SUCCESSFUL BEFORE
        # -------------------------
        if self.audit.has_processed(file_name):
            return pd.DataFrame()

        try:
            csv_path = self.extractor.extract(zip_path)

            df = pd.read_csv(csv_path)
            df = self.normalizer.transform(df)
            df = self.validator.validate(df)

            self.audit.mark_success(file_name)

            return df

        except Exception as e:
            self.audit.mark_failed(file_name, str(e))
            raise
