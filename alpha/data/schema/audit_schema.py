AUDIT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ingestion_audit (
    file_name TEXT PRIMARY KEY,
    status TEXT,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    error TEXT
)
"""
