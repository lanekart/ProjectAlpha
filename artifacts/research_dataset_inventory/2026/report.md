# Research Dataset Inventory — 2026

**DIAGNOSTIC_ONLY / PRODUCTION_INFLUENCE=false**

- Period end: **2026-07-20**
- Certification: **NOT_CERTIFIED**
- Coverage score: **11.11%**
- Blocking datasets: **7**
- Recommended next action: **Corporate Actions**

## Dataset Readiness

| Dataset | Status | Observed | Expected | Coverage | Blocking |
|---|---|---:|---:|---:|---:|
| Daily OHLCV | COMPLETE_CANDIDATE | 133 | 143 | 93.01% | YES |
| Corporate Actions | PRESENT_EMPTY | UNKNOWN | UNKNOWN | UNKNOWN | YES |
| Security Identity History | PARTIAL | UNKNOWN | UNKNOWN | 100.00% | YES |
| Listing History | MISSING | UNKNOWN | UNKNOWN | UNKNOWN | YES |
| Delisting/Suspension History | MISSING | UNKNOWN | UNKNOWN | UNKNOWN | YES |
| Trading Calendar | DERIVED_ONLY | 133 | 143 | 93.01% | YES |
| Benchmark History | MISSING | UNKNOWN | UNKNOWN | UNKNOWN | YES |
| Historical Sector Mapping | MISSING | UNKNOWN | UNKNOWN | UNKNOWN | YES |
| Historical Index Constituents | MISSING | UNKNOWN | UNKNOWN | UNKNOWN | NO |
| Market Breadth | MISSING | UNKNOWN | UNKNOWN | UNKNOWN | NO |
| Delivery Percentage | MISSING | UNKNOWN | UNKNOWN | UNKNOWN | NO |
| Volatility Index | MISSING | UNKNOWN | UNKNOWN | UNKNOWN | NO |

## Scientific Boundary

- This command inventories evidence; it does not download data.
- Weekdays are a provisional expected-session proxy until the official trading calendar is certified.
- Daily OHLCV readiness requires warehouse/snapshot reconciliation.
- Embedded candle ISINs do not replace effective-dated identity history.
- Unknown coverage is never treated as complete.
- No production signal, gate, or portfolio policy is changed.

**PRODUCTION_INFLUENCE=false**
