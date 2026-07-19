# Executive Report: Historical Truth Discovery

**Decision date:** 19 July 2026  
**Priority:** P0  
**Classification:** Research Infrastructure  
**Production influence:** None (`PRODUCTION_INFLUENCE=false`)

## Executive Decision

Do not replace Warehouse v1 and do not begin bulk acquisition yet. Alpha now has an
implementation-ready Historical Truth Layer blueprint, but procurement evidence is
still incomplete for the exact backfill range, historical identity, constituent and
sector history, correction policy, and data-retention rights.

The correct next step is a rights-and-sample procurement sprint followed by a bounded
NSE pilot. Warehouse v1 remains useful as `OBSERVED` research evidence and as a
reconciliation baseline. It is not certified as long-term official truth.

## Current Evidence

| Measure | Current state |
| --- | ---: |
| Legacy observations | 4,898,586 |
| Provisional security identities | 5,340 |
| Sessions | 2,466 |
| Observed date range | 8 July 2016 to 10 July 2026 |
| Observed-universe temporal failures | 0 detected |
| Historical Nifty constituent coverage | `UNKNOWN` |
| Effective-dated historical sector coverage | `UNKNOWN` |
| Corporate-action completeness | `UNKNOWN` |
| Official listing/suspension history | `UNKNOWN` |
| Overall current confidence | `LOW` |

The zero detected temporal failures proves that the existing point-in-time materializer
did not leak known future constituents within its provisional model. It does not prove
that the population is equity-only, survivorship-complete, or institutionally
authoritative.

## What Official Sources Establish

- NSE publicly exposes daily bhavcopy/UDiFF, delivery, security, corporate-action,
  calendar, and supporting reports. NSE also sells EOD/historical, master, and
  corporate products.
- NSE Indices explicitly offers historical constituent data, while public index pages
  mostly provide levels, current constituents, schedules, and dated change releases.
- BSE exposes security price history, corporate actions, security-master
  specifications, and notices, and offers registered exchange data products.
- NSDL and CDSL document ISIN and Corporate Action masters for participant-facing
  workflows.
- SEBI curates exchange disclosure/report sources and defines disclosure obligations,
  but is not the primary daily price warehouse source.

Key official references include [NSE All Reports](https://www.nseindia.com/all-reports),
[NSE paid historical data](https://www.nseindia.com/static/market-data/eod-historical-data-subscription),
[NSE Indices data subscriptions](https://www.niftyindices.com/offerings/data-subscription),
[BSE Stock Prices](https://www.bseindia.com/markets/equity/EQReports/StockPrcHistori.aspx?flag=sp),
[BSE Self Data Feed](https://marketdata.bseindia.com/),
[NSDL standardized masters](https://nsdl.co.in/downloadables/pdf/2024-0112-Policy-Standardization_of_File_Formats.pdf),
and [CDSL UDiFF masters](https://www.cdslindia.com/DP/Harmonization.html).

## What Is Still Unknown

Official pages do not, by themselves, establish:

- the earliest guaranteed, continuous bulk history for every required dataset;
- complete inactive and delisted security history;
- permanent cross-venue identity and old/new ISIN lineage;
- full listing, suspension, relisting, and delisting intervals;
- complete Nifty 50/100/200/500 constituent snapshots without subscription;
- effective-dated historical company sector assignments;
- full merger/demerger terms and correction/revision history;
- Alpha's right to automate, retain, back up, and use public files for proprietary
  commercial research.

[NSE's Data Sharing and Usage Policy](https://www.nseindia.com/static/market-data/nse-data-policy)
makes the relevant agreement central to permitted handling. Unknown rights therefore
remain a hard acquisition veto.

## Architecture Decision

The future Warehouse v2 is bitemporal and evidence-preserving:

```text
Raw Data
  -> Normalization
  -> Corporate Action Engine
  -> Security Master
  -> Identity Resolution
  -> Historical Universe
  -> Canonical Warehouse
  -> Research Layer
```

Every field carries one closed truth class: `OFFICIAL`, `OBSERVED`, `INFERRED`,
`CURRENT_ONLY`, or `UNKNOWN`. Resolution state, provenance, effective time, knowledge
time, and confidence are stored separately.

NSE and BSE observations remain venue-specific. Current constituent or sector files
cannot be backfilled. Official corrections create new immutable releases rather than
rewriting prior point-in-time knowledge.

## Confidence Decision

The confidence model separately evaluates source authority, reconciliation,
completeness, identity, corporate-action safety, and point-in-time safety. A high row
count cannot mask absent universe or action history. Critical conflict, unauthorized
use, unresolved identity, current-only leakage, or future information vetoes high
confidence.

The current baseline remains `LOW`. Warehouse v2 certification requires each mandatory
component to pass independently.

## Versioning Decision

Every immutable warehouse release pins component hashes and a complete run bundle:

```text
Warehouse Version
Feature Version
Policy Version
Decision Version
```

Warehouse v1 remains the observed baseline. Warehouse v2 will be official research
truth only after a candidate release is reconciled, independently reviewed, and
published for research. Production selection is a separate human decision.

## Recommended Next Sprint

### P0: source rights and representative samples

1. Request exact NSE EOD, master, corporate-action, and historical-constituent data
   dictionaries, earliest dates, correction policies, and sample files.
2. Confirm retention, backup, replay, non-display, derived-research, and exit rights.
3. Request equivalent BSE and depository details for gaps and cross-checks.
4. Build no acquisition code until the authorization and sample gate passes.

### P0: bounded architecture pilot after approval

Use a small, authorized sample spanning format transitions, delistings, symbol/ISIN
changes, splits, mergers, and dual listings. Measure real coverage and mismatch
populations before setting promotion tolerances or purchasing a full backfill.

## Roadmap

1. Historical Truth Engine: rights registry, immutable raw vault, truth kernel,
   identity, actions, calendar.
2. Canonical Warehouse v2: full authorized backfill, reconciliation, confidence,
   versioned research release.
3. Canonical Alpha Fund: survivorship-safe, version-pinned replay and shadow evidence.
4. Institutional Data Layer: premium identity/actions and BSE breadth only where
   measured gaps justify them.

## Go / No-Go

| Decision | Result |
| --- | --- |
| Continue using Warehouse v1 for labeled diagnostics | **GO** |
| Treat Warehouse v1 as official historical truth | **NO-GO** |
| Build an unlicensed website downloader | **NO-GO** |
| Replace the current warehouse now | **NO-GO** |
| Conduct procurement and bounded sample evaluation | **GO** |
| Implement Warehouse v2 after evidence gates pass | **CONDITIONAL GO** |

## Deliverables

- [historical_data_inventory.md](historical_data_inventory.md)
- [coverage_matrix.csv](coverage_matrix.csv)
- [warehouse_architecture.md](warehouse_architecture.md)
- [truth_classification.md](truth_classification.md)
- [confidence_engine.md](confidence_engine.md)
- [reconciliation_strategy.md](reconciliation_strategy.md)
- [warehouse_versioning.md](warehouse_versioning.md)
- [download_strategy.md](download_strategy.md)
- [risk_register.md](risk_register.md)
- [implementation_blueprint.md](implementation_blueprint.md)
- [executive_report.md](executive_report.md)

No data was downloaded, Warehouse v1 was not replaced, and no recommendation,
approval, replay, learning, allocation, live, or trading behavior changed.
