# HTR-010B1C Session Coverage and Residual Attribution

HTR-010B1C closes the remaining diagnostic gaps exposed by the governed HTR-010B1B runs.

## Governed session coverage

- Verifies the checksum of the governed NSE session-calendar report.
- Requires the calendar report to cover the requested audit window.
- Compares every expected regular and special session with canonical DuckDB observations.
- Reports missing expected sessions, unexpected observed sessions, unresolved weekdays, and calendar/database disagreements.
- Prohibits declaring a window complete merely because the first and last dates match.

## Residual factor attribution

Implementation defects are investigated diagnostically for:

- possible factor-orientation defects;
- possible effective-date offsets;
- possible same-day cumulative-action factors;
- possible thin-trading distortion;
- unexplained transformation defects.

Official factors remain immutable. An inverse or cumulative factor calculated from market behavior is diagnostic evidence only and is never applied automatically.

## Admission policy

- HTR-010B1B admission intervals remain unchanged.
- New attribution does not admit any previously quarantined interval.
- Missing governed sessions and residual transformation defects remain replay-readiness blockers.
- No benchmark replay is executed.
- `PRODUCTION_INFLUENCE=false`.
