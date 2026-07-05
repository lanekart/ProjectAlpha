CREATE_SYMBOLS_TABLE = """
CREATE TABLE IF NOT EXISTS symbols (
    symbol VARCHAR,
    series VARCHAR,
    company_name VARCHAR,
    exchange VARCHAR,
    is_active BOOLEAN,
    created_at TIMESTAMP,

    PRIMARY KEY (symbol, exchange)
);
"""

CREATE_DAILY_PRICES_TABLE = """
CREATE TABLE IF NOT EXISTS daily_prices (
    trade_date DATE,
    symbol VARCHAR,
    exchange VARCHAR,

    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    last DOUBLE,
    previous_close DOUBLE,

    volume BIGINT,
    turnover DOUBLE,
    trades BIGINT,

    deliverable_qty BIGINT,
    deliverable_percent DOUBLE,

    created_at TIMESTAMP,

    PRIMARY KEY (trade_date, symbol, exchange)
);
"""

CREATE_DOWNLOADS_TABLE = """
CREATE TABLE IF NOT EXISTS downloads (
    trade_date DATE,
    exchange VARCHAR,

    downloaded_at TIMESTAMP,
    filename VARCHAR,
    checksum VARCHAR,
    status VARCHAR,

    PRIMARY KEY (trade_date, exchange)
);
"""

SCHEMA_STATEMENTS = [
    CREATE_SYMBOLS_TABLE,
    CREATE_DAILY_PRICES_TABLE,
    CREATE_DOWNLOADS_TABLE,
]
