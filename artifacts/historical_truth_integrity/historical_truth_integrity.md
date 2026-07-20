# Historical Truth Integrity Audit

Period: 2026-01-01 to 2026-07-20
Expected trading days: 133
Observed trading days: 133
Coverage: 100.00%
Candle replay ready: True
Full-evidence replay ready: False

## Validation statistics

- Missing dates: 10
- Duplicate securities: 0
- Duplicate ISINs: 0
- Invalid OHLC relationships: 0
- Series-specific OHLC exceptions: 7
- Negative prices: 0
- Zero-volume anomalies: 0
- Source validation errors: 0
- Source validation warnings: 7
- Valid snapshots: 133/133

## Missing dates

| Date | Classification | Evidence |
|---|---|---|
| 2026-01-15 | holiday | date is present in the explicitly supplied holiday set |
| 2026-01-26 | holiday | date is present in the explicitly supplied holiday set |
| 2026-03-03 | holiday | date is present in the explicitly supplied holiday set |
| 2026-03-26 | holiday | date is present in the explicitly supplied holiday set |
| 2026-03-31 | holiday | date is present in the explicitly supplied holiday set |
| 2026-04-03 | holiday | date is present in the explicitly supplied holiday set |
| 2026-04-14 | holiday | date is present in the explicitly supplied holiday set |
| 2026-05-01 | holiday | date is present in the explicitly supplied holiday set |
| 2026-05-28 | holiday | date is present in the explicitly supplied holiday set |
| 2026-06-26 | holiday | date is present in the explicitly supplied holiday set |

## Security findings

| Date | Code | Severity | Security | Evidence |
|---|---|---|---|---|
| 2026-02-23 | SERIES_SPECIFIC_OHLC | warning | IDEA/T0 | open=11.27; high=11.27; low=11.27; close=10.98; violations=low>close |
| 2026-02-23 | VALIDATION_WARNING | warning | / | T0_CLOSE_RANGE_EXCEPTION; row=3207; symbol=IDEA; series=T0; open=11.27; high=11.27; low=11.27; close=10.98; violations=low>close |
| 2026-02-24 | SERIES_SPECIFIC_OHLC | warning | IDEA/T0 | open=10.98; high=10.98; low=10.98; close=10.91; violations=low>close |
| 2026-02-24 | VALIDATION_WARNING | warning | / | T0_CLOSE_RANGE_EXCEPTION; row=3197; symbol=IDEA; series=T0; open=10.98; high=10.98; low=10.98; close=10.91; violations=low>close |
| 2026-03-05 | SERIES_SPECIFIC_OHLC | warning | IDEA/T0 | open=9.88; high=9.88; low=9.88; close=10.22; violations=high<close |
| 2026-03-05 | VALIDATION_WARNING | warning | / | T0_CLOSE_RANGE_EXCEPTION; row=3259; symbol=IDEA; series=T0; open=9.88; high=9.88; low=9.88; close=10.22; violations=high<close |
| 2026-03-23 | SERIES_SPECIFIC_OHLC | warning | NHPC/T0 | open=75.0; high=75.0; low=75.0; close=75.28; violations=high<close |
| 2026-03-23 | VALIDATION_WARNING | warning | / | T0_CLOSE_RANGE_EXCEPTION; row=2117; symbol=NHPC; series=T0; open=75.0; high=75.0; low=75.0; close=75.28; violations=high<close |
| 2026-04-02 | SERIES_SPECIFIC_OHLC | warning | YESBANK/T0 | open=17.26; high=17.26; low=17.26; close=17.87; violations=high<close |
| 2026-04-02 | VALIDATION_WARNING | warning | / | T0_CLOSE_RANGE_EXCEPTION; row=3284; symbol=YESBANK; series=T0; open=17.26; high=17.26; low=17.26; close=17.87; violations=high<close |
| 2026-04-09 | SERIES_SPECIFIC_OHLC | warning | MAHABANK/T0 | open=70.0; high=70.0; low=70.0; close=70.03; violations=high<close |
| 2026-04-09 | VALIDATION_WARNING | warning | / | T0_CLOSE_RANGE_EXCEPTION; row=426; symbol=MAHABANK; series=T0; open=70.0; high=70.0; low=70.0; close=70.03; violations=high<close |
| 2026-04-23 | SERIES_SPECIFIC_OHLC | warning | RELIANCE/T0 | open=1346.0; high=1346.0; low=1346.0; close=1343.4; violations=low>close |
| 2026-04-23 | VALIDATION_WARNING | warning | / | T0_CLOSE_RANGE_EXCEPTION; row=2481; symbol=RELIANCE; series=T0; open=1346.0; high=1346.0; low=1346.0; close=1343.4; violations=low>close |

## Replay blockers

- NON_CANDLE_EVIDENCE_NOT_AUDITED

Full-evidence readiness remains false until the separately governed evidence layers are present and audited.
