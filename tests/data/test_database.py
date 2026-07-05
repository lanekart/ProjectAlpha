from alpha.data.repositories.database import Database


def test_database_connection():
    db = Database("data/test.duckdb")

    result = db.execute("SELECT 1").fetchone()

    assert result == (1,)

    db.close()
