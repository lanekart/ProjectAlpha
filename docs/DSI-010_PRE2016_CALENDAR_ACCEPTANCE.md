# DSI-010 — Pre-2016 Calendar Acceptance Boundary

## Purpose

DSI-010 must distinguish an archive request that returned HTTP 404 from an
exchange holiday supported by official evidence. A missing archive is not, by
itself, permission to classify a weekday as a holiday.

## Local empirical boundary

The governed 2005-01-01 through 2015-12-31 raw population contains:

- 2,869 planned weekdays;
- 2,716 downloaded candle sessions;
- 153 archive-unavailable weekdays;
- 0 failed requests;
- 3,581,376 canonical raw candle rows.

The archive manifest stores status values in lowercase. DSI-010 normalizes the
status before reconciliation and preserves every unavailable date in the audit
ledger.

## Required official evidence

The operator supplies one or more immutable official NSE calendar JSON sources.
Together they must cover every year from 2005 through 2015 and may contain:

```json
{
  "covered_years": [2005],
  "holidays": [
    {
      "trading_date": "2005-01-26",
      "description": "Republic Day"
    }
  ],
  "special_sessions": [],
  "source_url": "OFFICIAL_SOURCE_LOCATOR"
}
```

Source bytes are retained outside Git, SHA-256 bound into the calendar report,
and revalidated before DSI-010 reads adjusted market data.

## Certification requirements

A ready pre-2016 calendar requires:

- exact window 2005-01-01 through 2015-12-31;
- official source coverage for all eleven years;
- zero unresolved weekdays;
- zero unconfirmed or missing official special sessions;
- zero holiday/candle conflicts;
- all archive-unavailable weekdays reconciled to official holidays;
- checksum-valid report and source files.

The final DSI-010 external-validation command requires this certified calendar
report as an explicit input. Missing, partial, uncertified, or tampered calendar
evidence fails closed before market replay.

## Source boundary

Calendar-gate source boundary:

`f5508bd2c047763861347fb756a332f00a043c37`

Permanent GitHub CI must pass on a later owner-authored publication head before
local calendar acceptance begins.

## Governance

```text
CALENDAR_INFERENCE_FROM_HTTP_404_PERMITTED=false
SYNTHETIC_HOLIDAYS_PERMITTED=false
PRODUCTION_INFLUENCE=false
```
