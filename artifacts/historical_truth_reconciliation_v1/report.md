# Historical Truth Reconciliation v1

**DIAGNOSTIC_ONLY / PRODUCTION_INFLUENCE=false**

- Period: **2026-01-01 to 2026-07-20**
- Recoverable without download: **7**
- Truly missing: **1**
- Apparent missing sessions: **10**

## Dataset Reconciliation

| Dataset | Inventory | Classification | Canonical rows | Recoverable |
|---|---|---|---:|---:|
| Corporate Actions | PRESENT_EMPTY | RAW_DATA_PRESENT | 0 | YES |
| Security Identity History | PARTIAL | RAW_DATA_PRESENT | 0 | YES |
| Listing History | MISSING | RAW_DATA_PRESENT | UNKNOWN | YES |
| Delisting/Suspension History | MISSING | TRULY_MISSING | UNKNOWN | NO |
| Trading Calendar | DERIVED_ONLY | CERTIFICATION_LOGIC_GAP | UNKNOWN | YES |
| Benchmark History | MISSING | RAW_DATA_PRESENT | UNKNOWN | YES |
| Historical Sector Mapping | MISSING | RAW_DATA_PRESENT | UNKNOWN | YES |
| Historical Index Constituents | MISSING | RAW_DATA_PRESENT | UNKNOWN | YES |

## Apparent Missing Sessions

| Date | Classification | Evidence |
|---|---|---|
| 2026-01-15 | UNRESOLVED | Absent from daily_candle and no certified holiday evidence found |
| 2026-01-26 | UNRESOLVED | Absent from daily_candle and no certified holiday evidence found |
| 2026-03-03 | UNRESOLVED | Absent from daily_candle and no certified holiday evidence found |
| 2026-03-26 | UNRESOLVED | Absent from daily_candle and no certified holiday evidence found |
| 2026-03-31 | UNRESOLVED | Absent from daily_candle and no certified holiday evidence found |
| 2026-04-03 | UNRESOLVED | Absent from daily_candle and no certified holiday evidence found |
| 2026-04-14 | UNRESOLVED | Absent from daily_candle and no certified holiday evidence found |
| 2026-05-01 | UNRESOLVED | Absent from daily_candle and no certified holiday evidence found |
| 2026-05-28 | UNRESOLVED | Absent from daily_candle and no certified holiday evidence found |
| 2026-06-26 | UNRESOLVED | Absent from daily_candle and no certified holiday evidence found |

## Required Conclusion

- Recoverable without downloads: **corporate_actions, security_identity, listing_history, trading_calendar, benchmark_history, sector_mapping, index_constituents**
- Truly missing: **delisting_history**
- Unresolved OHLCV dates: **2026-01-15, 2026-01-26, 2026-03-03, 2026-03-26, 2026-03-31, 2026-04-03, 2026-04-14, 2026-05-01, 2026-05-28, 2026-06-26**
- Corporate Actions remains next milestone: **True**

No production signal, gate, portfolio, or risk policy was changed.

**PRODUCTION_INFLUENCE=false**
