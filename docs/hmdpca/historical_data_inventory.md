# Historical Market Data Procurement Inventory

**Audit:** HMDPCA v1.0  
**Evidence date:** 19 July 2026  
**Classification:** Research / Procurement  
**Production influence:** None  
**PRODUCTION_INFLUENCE=false**

## Decision

Alpha should procure a licensed, exchange-authoritative NSE core and treat every
other source as either a complement or a verifier. The initial commercial package
should be NSE Capital Market EOD plus Master Data, followed by separately competed
corporate-action and index-history packages. BSE should be purchased only after an
ISIN-level sample proves incremental coverage or materially different outcomes.

No source is warehouse-approved by this audit. Approval requires a signed use-rights
schedule and a representative data sample. Public availability, a working API, or an
open-source client does not prove permanent storage, internal non-display research,
backup, derived-data, or correction-reprocessing rights.

## Existing Alpha Baseline

The last measured Warehouse v1 baseline contains 4,898,586 daily observations,
5,340 historical symbol labels, 2,466 sessions, and a date range from 8 July 2016 to
10 July 2026. It is NSE-labelled research evidence, not certified historical truth.
It lacks effective-dated security identity, listing and delisting history, historical
index membership, and a complete corporate-action ledger.

This audit does not alter or replace Warehouse v1 and downloads no market data.

## Evaluation Method

Each candidate is evaluated across three independent questions:

1. **Technical availability:** does documentation describe the required dataset?
2. **Contractual usability:** do written terms permit Alpha's intended storage and
   internal research use?
3. **Empirical coverage:** does a representative, checksummed sample contain the
   required population and fields?

Coverage is recorded as `UNKNOWN_PENDING_SAMPLE` unless Alpha has measured it. A
vendor's statement that data is comprehensive or goes back to a given year is a
documented capability, not a coverage percentage.

Quality grades are intentionally conservative:

| Grade | Meaning |
| --- | --- |
| A | Signed rights, representative coverage test, point-in-time proof, correction lineage, and reproducible delivery all pass |
| B | Strong authoritative or institutional candidate; contract or sample evidence remains open |
| C | Useful complement with material point-in-time, normalization, or rights gaps |
| D | Operational or research-only source; unsuitable as historical authority |
| UNUSABLE | Provenance, permission, continuity, or reproducibility is inadequate for Warehouse v2 |

No dataset receives grade A before procurement and empirical validation.

## Domain Inventory

| Domain | Best primary candidate | Useful complement | Largest unresolved fact |
| --- | --- | --- | --- |
| A. Daily equity | NSE licensed EOD; BSE licensed EOD if justified | Upstox or licensed vendor for overlap checks | Exact inactive/delisted coverage and retained-use rights |
| B. Index history | NSE Indices subscription | Public index OHLC/TR downloads for verification | Earliest complete constituent history and license scope |
| C. Index membership | NSE Indices EOD constituent history | Institutional vendor | Effective-date depth, corrections, and historical removals |
| D. Corporate actions | NSE EOD Corporate Data; BSE licensed corporate data | GFDL, TrueData, LSEG, FactSet, S&P, Bloomberg | Complete merger/demerger/rights/symbol lineage and revision history |
| E. Security master | NSE Master Data plus BSE reference data | CDSL/NSDL current ISIN masters; institutional symbology | Historical symbol reuse, delistings, relistings, and series history |
| F. Delivery | NSE and BSE official security-wise delivery files | Licensed Indian vendor | Complete historical bulk depth and correction policy |
| G. Breadth | Official NSE/BSE daily market reports | Derived from a certified universe | Historical denominator and unchanged/suspended treatment |
| H. Institutional | Exchange shareholding filings, SEBI/NSDL aggregates, AMFI portfolios | FactSet/LSEG/S&P/Bloomberg | Security-level, point-in-time normalized ownership history |
| I. Earnings | NSE/BSE filings and event notices | FactSet/LSEG/Bloomberg for estimates and surprises | Revision-safe consensus, guidance normalization, and India coverage |

## Source Findings

### Official Exchanges

**NSE Data & Analytics is the primary authority for Alpha's existing NSE scope.**
The current tariff publishes Capital Market EOD at INR 100,000 per site/year,
Master Data at INR 215,000, EOD Corporate Data at INR 500,000, and Historical Trade
Data at INR 110,000, exclusive of taxes and with additional-channel rules. EOD and
historical delivery documentation describes SFTP and an online historical platform.
The governing agreement remains decisive for use and retention.

**NSE Indices is a separate procurement.** Public pages provide historical index
OHLC and total-return values. Historical constituent data, including company names,
identifiers, capitalization, weights, and prices, is offered by subscription. Public
current constituent files must not be treated as historical membership.

**BSE is the authoritative complement, not an automatic duplicate purchase.** Its
current tariff and self-data portal describe EOD, historical trade, delivery-volume,
index OHLC, corporate, and reference products. BSE should first supply a sample
covering BSE-only securities, dual-listed names, delistings, and corporate-action
conflicts. Alpha should buy it when the measured incremental value justifies the
cost and operational complexity.

### Depositories and Regulators

CDSL documents current ISIN and corporate-action master formats. SEBI provides
curated links to exchange price/delivery datasets and archives of FPI and mutual-fund
statistics. AMFI publishes long-running industry statistics and fund portfolio
disclosures. These are valuable official evidence, but they do not by themselves
form a complete effective-dated equity identity or security-level ownership feed.

### Broker APIs

Upstox V3 documents daily history from January 2000 and intraday history from January
2022. Zerodha provides historical candles and live data under a published retail API
price. These feeds are appropriate for live operations and bounded price overlap
checks. They are not the authoritative Warehouse v2 source because current instrument
masters, corporate-action lineage, inactive securities, correction history, and
permanent commercial retention are incomplete or contract-dependent.

### Open-Source Wrappers

`nse-archives` 1.2.4 was released on 6 July 2026, is MIT-licensed, and documents 91
datasets sourced from `nsearchives.nseindia.com`. It is a credible ingestion utility
candidate after security review and fixture-based testing. Its software license covers
the wrapper code only. It does not change NSE ownership, terms, entitlement, or
redistribution restrictions. Alpha may use a pinned wrapper to automate an already
licensed source; it may not use the wrapper as the legal or provenance authority.

Other scraping-oriented wrappers and GitHub datasets remain research-only until the
upstream source, rights, version pin, checksums, correction behavior, and maintenance
plan are proven. Code that evades access controls is excluded.

### Licensed Indian Vendors

Global Datafeeds and TrueData document exchange-authorized live products and broad
historical/corporate capabilities. GFDL explicitly distinguishes individual use from
commercial use requiring exchange agreements. Both belong in the RFP as potential
normalization or operational suppliers, subject to exact history, inactive identity,
corporate-action revisions, retention rights, and a full-population sample.

Symphony XTS is better suited to live infrastructure than deep historical truth.
Spider is a research terminal candidate, not a demonstrated bulk point-in-time
warehouse source.

### Premium Institutional Vendors

LSEG, FactSet, Bloomberg, and S&P Global offer the strongest normalized identity,
corporate-action, ownership, event, and point-in-time capabilities. LSEG documents
equity history from 2000; FactSet documents decades of pricing/reference history,
point-in-time fundamentals and estimates, and long ownership history; Bloomberg Data
License provides 20+ years of bulk data; S&P offers normalized managed corporate
actions and point-in-time fundamentals. All require package-specific India coverage,
exchange entitlement, retention, and pricing confirmation.

These products are an upgrade path, not the cheapest first purchase. They become
economically sensible when Alpha's capital, research breadth, and data operations
justify buying normalized history rather than building and maintaining it internally.

### Public and Community Sources

Yahoo Finance, Alpha Vantage retail, Twelve Data personal plans, Stooq, and GitHub
datasets must not be authoritative. Yahoo prohibits redistribution and is intended
for informational use. Alpha Vantage classifies investment research beyond personal
use as commercial. Twelve Data separates personal, business, internal, non-display,
storage, and redistribution rights and can require exchange-specific agreements.
Public endpoints remain useful only for bounded research or anomaly triage under
their applicable terms.

## Required Procurement Data Contract

Every shortlisted provider must answer and contractually bind the following:

- exact first and last date by exchange, segment, series, and field;
- active, inactive, suspended, delisted, relisted, and renamed coverage;
- permanent identifiers and effective-dated symbol, name, ISIN, series, and venue;
- raw and adjusted OHLCV definitions and every adjustment factor;
- event terms for dividend, split, bonus, rights, merger, demerger, and symbol change;
- original publication time, valid time, correction time, and revision history;
- delivery, delivery percentage, trades, turnover, and unit definitions;
- calendar, holiday, no-trade, suspension, and missing-value semantics;
- local retention, internal non-display research, backup, disaster recovery,
  correction reprocessing, derived analytics, and contract-exit export rights;
- redistribution and external display exclusions;
- API/bulk/SFTP limits, SLA, support, correction cadence, and termination process;
- data dictionary, sample, checksums, reconciliation rules, and price schedule.

## Evidence Register

- [NSE 2026 domestic tariff](https://nsearchives.nseindia.com/web/mediaattachment/2026-04/Download_Pricing_file_-_Domestic_clients_20260424122229.pdf)
- [NSE EOD and historical products](https://www.nseindia.com/static/market-data/eod-historical-data-subscription)
- [NSE Data Sharing and Usage Policy](https://www.nseindia.com/static/market-data/nse-data-policy)
- [NSE all reports](https://www.nseindia.com/all-reports/)
- [NSE Indices data subscription](https://www.niftyindices.com/offerings/data-subscription)
- [NSE Indices historical reports](https://www.niftyindices.com/reports/historical-data)
- [BSE information products tariff](https://www.bseindia.com/downloads1/Information_Products_Pricing_Sheet.pdf)
- [BSE self data feed](https://marketdata.bseindia.com/)
- [SEBI equity cash-market source curation](https://www.sebi.gov.in/curation/equity_cash_market.html)
- [CDSL harmonized masters](https://www.cdslindia.com/DP/Harmonization.html)
- [SEBI statistics](https://www.sebi.gov.in/statistics/statistics.html)
- [AMFI research information](https://www.amfiindia.com/research-information)
- [Upstox V3 historical candles](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/)
- [Zerodha API charges](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/what-are-the-charges-for-kite-apis)
- [`nse-archives` package](https://pypi.org/project/nse-archives/)
- [Global Datafeeds commercial-use guidance](https://globaldatafeeds.in/global-datafeeds-apis/global-datafeeds-apis/pricing-sales/who-can-purchase/)
- [TrueData market-data API](https://www.truedata.in/market-data-apis)
- [LSEG equity data](https://www.lseg.com/en/data-analytics/financial-data/pricing-and-market-data/equities-pricing-data)
- [FactSet pricing and reference data](https://www.factset.com/marketplace/catalog/product/factset-pricing-and-reference-data)
- [Bloomberg Data License](https://professional.bloomberg.com/products/data/data-management/data-license/)
- [S&P Managed Corporate Actions](https://www.spglobal.com/market-intelligence/en/solutions/mca)
- [Twelve Data commercial terms](https://support.twelvedata.com/en/articles/5332349-commercial-and-personal-usage)
- [Alpha Vantage terms](https://www.alphavantage.co/terms_of_service/)
- [Yahoo Finance data availability](https://uk.help.yahoo.com/kb/finance/data-availability-yahoo-finance-sln2310.html)

## Audit Boundary

This work is procurement research only. It performs no download, API call, data
ingestion, migration, replay, recommendation change, or production-policy change.

