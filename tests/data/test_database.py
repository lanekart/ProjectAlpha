from pathlib import Path

import duckdb

from alpha.data.repositories.audit import AuditRepository
from alpha.data.repositories.database import Database


def test_database_connection(tmp_path: Path) -> None:
    db = Database(str(tmp_path / "test.duckdb"))

    result = db.execute("SELECT 1").fetchone()

    assert result == (1,)

    db.close()


def test_database_migrates_legacy_audit_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.duckdb"
    connection = duckdb.connect(str(db_path))
    connection.execute(
        """
        CREATE TABLE ingestion_audit (
            file_name TEXT PRIMARY KEY,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        INSERT INTO ingestion_audit (file_name)
        VALUES ('legacy.zip')
        """
    )
    connection.close()

    db = Database(str(db_path))
    columns = {
        str(row[1])
        for row in db.execute("PRAGMA table_info('ingestion_audit')").fetchall()
    }

    assert {"file_name", "processed_at", "status", "error"}.issubset(columns)
    assert AuditRepository(db).has_processed("legacy.zip")

    db.close()
