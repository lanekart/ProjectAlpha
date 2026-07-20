# Historical Truth Reconciliation v1.1

**DIAGNOSTIC_ONLY / PRODUCTION_INFLUENCE=false**

- Confirmed raw datasets: **2**
- No usable raw data: **0**
- Verified exchange holidays: **10**
- Daily OHLCV coverage: **100.00%**

## Evidence Precision

| Dataset | Classification | Usable raw files | Excluded/generated |
|---|---|---:|---:|
| corporate_actions | EVIDENCE_ONLY_NO_USABLE_RAW_DATA | 0 | 0 |
| security_identity | RAW_DATA_CONFIRMED | 1 | 2 |
| listing_history | RAW_DATA_CONFIRMED | 1 | 0 |
| delisting_history | EVIDENCE_ONLY_NO_USABLE_RAW_DATA | 0 | 0 |
| benchmark_history | EVIDENCE_ONLY_NO_USABLE_RAW_DATA | 0 | 3 |
| sector_mapping | EVIDENCE_ONLY_NO_USABLE_RAW_DATA | 0 | 1 |
| index_constituents | EVIDENCE_ONLY_NO_USABLE_RAW_DATA | 0 | 0 |

## Missing Sessions

- 2026-01-15: VERIFIED_EXCHANGE_HOLIDAY — Maharashtra municipal corporation elections
- 2026-01-26: VERIFIED_EXCHANGE_HOLIDAY — Republic Day
- 2026-03-03: VERIFIED_EXCHANGE_HOLIDAY — Holi
- 2026-03-26: VERIFIED_EXCHANGE_HOLIDAY — Ram Navami
- 2026-03-31: VERIFIED_EXCHANGE_HOLIDAY — Mahavir Jayanti
- 2026-04-03: VERIFIED_EXCHANGE_HOLIDAY — Good Friday
- 2026-04-14: VERIFIED_EXCHANGE_HOLIDAY — Ambedkar Jayanti
- 2026-05-01: VERIFIED_EXCHANGE_HOLIDAY — Maharashtra Day
- 2026-05-28: VERIFIED_EXCHANGE_HOLIDAY — Bakri Id
- 2026-06-26: VERIFIED_EXCHANGE_HOLIDAY — Muharram

## Required Conclusion

- Confirmed raw datasets: **security_identity, listing_history**
- No usable raw data: **none**
- Unresolved sessions: **none**

No production signal, gate, portfolio, or risk policy was changed.

**PRODUCTION_INFLUENCE=false**
