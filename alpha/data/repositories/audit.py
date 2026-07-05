from alpha.data.repositories.database import Database


class AuditRepository:
    """
    Tracks ingestion lifecycle with status visibility.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    def has_processed(self, file_name: str) -> bool:
        result = self.db.execute(
            """
            SELECT 1
            FROM ingestion_audit
            WHERE file_name = ?
            AND status = 'SUCCESS'
            """,
            (file_name,),
        ).fetchone()

        return result is not None

    def mark_success(self, file_name: str) -> None:
        self.db.execute(
            """
            INSERT OR REPLACE INTO ingestion_audit (file_name, status)
            VALUES (?, 'SUCCESS')
            """,
            (file_name,),
        )

    def mark_failed(self, file_name: str, error: str) -> None:
        self.db.execute(
            """
            INSERT OR REPLACE INTO ingestion_audit (file_name, status, error)
            VALUES (?, 'FAILED', ?)
            """,
            (file_name, error),
        )
