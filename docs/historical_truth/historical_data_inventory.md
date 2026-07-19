# Historical Data Inventory

**Specification:** Historical Truth Discovery & Canonical Data Architecture v1.0  
**Evidence review date:** 19 July 2026  
**Classification:** Research Infrastructure  
**Production influence:** None (`PRODUCTION_INFLUENCE=false`)

## Purpose

This inventory records official Indian-market datasets that could supply a future
Alpha Warehouse v2. It documents existence and suitability; it does not authorize,
download, ingest, or promote any data.

An official web page proves that a product or report exists. It does **not** by
itself prove complete historical coverage, automated access, local retention rights,
point-in-time correctness, or a service-level commitment. Those attributes remain
`UNKNOWN` until supported by a contract, data dictionary, and representative sample.

The machine-readable companion is [coverage_matrix.csv](coverage_matrix.csv).

## Inventory Rules

1. `Official` means published by the exchange, index administrator, depository, or
   regulator responsible for that fact.
2. `Public` means visible through an official public interface. It does not imply a
   right to automate, retain, redistribute, or use commercially.
3. `Licensed` means the official source advertises a subscription or participant
   product. Exact entitlements remain contract-specific.
4. `Coverage start: UNKNOWN` is intentional when the official documentation does not
   guarantee an earliest date.
5. A current master is `CURRENT_ONLY` unless archived effective-dated copies are
   supplied. It must never be projected backward.
6. Exchange price observations are venue-specific. NSE and BSE closes for the same
   ISIN are separate official observations, not duplicates to be collapsed.

## NSE Data & Analytics / National Stock Exchange

### Daily prices and trading activity

| Dataset | What is officially evidenced | Historical certainty | Intended Warehouse v2 role |
| --- | --- | --- | --- |
| CM UDiFF Common Bhavcopy Final | Daily capital-market price and volume report; the legacy CM bhavcopy formats were discontinued from 8 July 2024 in favor of UDiFF | Public report interface exists; exact earliest complete archive is `UNKNOWN` | Primary official NSE raw EOD observation from 8 July 2024 onward after entitlement review |
| Legacy CM bhavcopy / PR files | Official daily security summaries and press files | Format lineage exists; complete retained history and earliest date require verification | Pre-UDiFF backfill source, preserved under its own schema version |
| Full Bhavcopy and Security Deliverable Data | Combined daily security and deliverable report appears in NSE All Reports | Earliest continuous availability is `UNKNOWN` | Convenience cross-check; never overwrite atomic bhavcopy and delivery sources |
| Security-wise Delivery Positions | Daily deliverable quantity report appears in NSE All Reports | Earliest continuous archive is `UNKNOWN` | Official delivery-volume fact keyed by venue, session, symbol, and series |
| Paid EOD / historical data | NSE advertises EOD security/trade data and historical order/trade data through controlled delivery | Exact start date, corrections, and retained backfill are quote/contract items | Preferred bulk backfill if licensed rights and sample pass |
| Market Activity / press reports | Daily supporting market activity files and report descriptions | File-level history varies; exact completeness is `UNKNOWN` | Secondary totals and reconciliation evidence |

Official evidence:

- [NSE All Reports](https://www.nseindia.com/all-reports) lists bhavcopy,
  UDiFF, full bhavcopy/deliverables, security files, and delivery positions.
- [NSE report descriptions](https://www.nseindia.com/static/market-data/description-of-market-activity-reports)
  document press-file contents.
- [Paid EOD and Historical Data](https://www.nseindia.com/static/market-data/eod-historical-data-subscription)
  describes EOD and historical products; dataset-level earliest coverage is not
  guaranteed on the page.
- [Historical Data Dissemination of Capital Market Segment](https://nsearchives.nseindia.com/content/press/Data_details_CM.pdf)
  describes bhavcopy, index, master, snapshot, trade, and circular directories.

### Security identity, listing, and tradability

| Dataset | What is officially evidenced | Historical certainty | Intended role |
| --- | --- | --- | --- |
| CM MII Security File | Daily listed-security file with symbol, series, instrument and related fields | A current daily snapshot; archived continuity is `UNKNOWN` | Official session-level tradable/security state |
| Paid Master Data | Daily post-EOD security/contract masters delivered by SFTP to subscribers | Historical master backfill and inactive coverage require contract confirmation | Primary NSE identity input if effective-dated archives are included |
| Securities Available for Trading | Current downloadable equity, SME, ETF, preference, warrant and other lists | Current state only unless dated copies are retained | Current verification; not historical proof |
| Changes in Symbols / Company Names | Current downloadable change lists | Historical completeness and effective-date semantics require sample validation | Supporting identity events, never a permanent key by themselves |
| Delisted-company lists and orders | NSE publishes delisted lists, proposed delistings, and dated delisting orders | Useful historical events; completeness across all eras is `UNKNOWN` | Delisting evidence joined to permanent identity |
| Suspended-company lists and listing circulars | Current suspension lists and dated notices are published | Complete suspension/revocation intervals are `UNKNOWN` | Tradability intervals after event reconstruction and reconciliation |
| IPO tracker / issue pages | Listing dates and issue information are visible for covered issues | Full history and all listing routes are `UNKNOWN` | Supporting first-listing evidence, not sole listing authority |

Official evidence:

- [Securities available for trading](https://www.nseindia.com/static/market-data/securities-available-for-trading)
  includes current security lists plus name and symbol changes.
- [NSE Masters Data](https://www.nseindia.com/static/market-data/paid-master-data)
  documents the subscribed master product.
- [Delisting of companies](https://www.nseindia.com/static/list/list-of-companies-proposed-to-be-delisted)
  publishes downloadable delisted-company information.
- [Orders of the Delisting Committee](https://www.nseindia.com/static/list/orders-of-delisting)
  exposes dated historical orders.
- [Listing compliance information](https://www.nseindia.com/static/regulations/listing-compliance)
  includes current suspension-related lists.

### Corporate actions and issuer events

| Dataset | What is officially evidenced | Historical certainty | Intended role |
| --- | --- | --- | --- |
| Public Corporate Actions | Symbol, company, series, purpose, face value, ex-date, record date, and book-closure dates with CSV export | Search range exists; earliest complete history and revision behavior are `UNKNOWN` | Official exchange action announcement evidence |
| Daily press-file corporate actions | Daily `Bc...csv` corporate-action details are documented | Exact archive completeness is `UNKNOWN` | Publication-time evidence for point-in-time reconstruction |
| Clearing corporate-action report | Symbol/series action list with record, book-closure, no-delivery, and ex-dates | Access can be member/report specific; full archive `UNKNOWN` | Confirmation of operational treatment |
| Paid Corporate Data / EOD Corporate Announcements | Licensed fundamentals, announcements, shareholding, and corporate disclosures | Exact backfill depth and action normalization require contract and sample | Bulk official issuer-event evidence |
| Listing and scheme circulars | Dated split, bonus, merger, demerger, symbol and ISIN notices | Searchable but not proven exhaustive as a machine dataset | Terms and lineage evidence for complex events |

Official evidence:

- [NSE Corporate Actions](https://www.nseindia.com/companies-listing/corporate-filings-actions)
  exposes official action fields and CSV download.
- [NSE Equity Market Data Reports](https://www.nseindia.com/static/products-services/equity-market-data-reports-download)
  describes security-master and corporate-action reports.
- [Paid Corporate Data](https://www.nseindia.com/static/market-data/corporate-data-subscription)
  documents licensed delivery and pricing categories.

### Trading calendar

Annual NSE holiday pages and exchange circulars are official evidence for declared
holidays, special sessions, and changes. Warehouse v2 must construct sessions from
dated calendar evidence plus actual bhavcopy presence. A weekend rule alone is not a
calendar.

- [NSE Market Timings and Holidays](https://www.nseindia.com/resources/exchange-communication-holidays)

### Nifty indices and industry classification

| Dataset | What is officially evidenced | Historical certainty | Intended role |
| --- | --- | --- | --- |
| Historical index levels | NSE Indices provides historical OHLC/index reports | Index-specific start varies; Nifty 50 base date is 3 November 1995 | Benchmark price series, not constituent history |
| Historical constituent subscription | NSE Indices advertises ongoing and historical constituent data with identifiers, weights, prices, and market capitalization | Exact earliest constituent snapshot and correction policy require subscription confirmation | Authoritative Nifty 50/100/200/500 membership history |
| Reconstitution calendar | Official review schedule for Nifty broad-market indices | Current methodology only | Expected review schedule, not proof of actual members |
| Press-release archive | Dated additions, deletions, and ad hoc changes | Public archive exists; exhaustiveness must be proven | Event reconstruction and cross-check |
| Current index constituent downloads | Current constituent files on index pages | `CURRENT_ONLY` | Present-state verification; never historical backfill |
| NSE Indices industry classification | Four-tier current macro-sector/sector/industry/basic-industry taxonomy | Effective-dated company history is not offered on the cited public page | Current classification and taxonomy; historical sector mapping remains `UNKNOWN` |

Official evidence:

- [NSE Indices Data Subscription](https://www.niftyindices.com/offerings/data-subscription)
  explicitly offers ongoing and historical constituent data.
- [NSE Indices historical reports](https://www.niftyindices.com/reports/historical-data)
  provides historical index values.
- [Index reconstitution calendar](https://www.niftyindices.com/resources/index-rebalancing-schedule)
  records review timing.
- [NSE Indices media archive](https://www.niftyindices.com/media) contains dated
  constituent-change releases.
- [NSE Industry Classification](https://www.nseindia.com/static/products-services/industry-classification)
  defines the current four-tier taxonomy.

## BSE Limited / BSE Index Services

| Dataset | What is officially evidenced | Historical certainty | Intended Warehouse v2 role |
| --- | --- | --- | --- |
| Public stock-price history | Daily, monthly, and yearly security history with OHLC, WAP, volume, trades, turnover, and deliverables | Security-level interface exists; guaranteed earliest bulk date is `UNKNOWN` | Official BSE venue observation and reconciliation source |
| BSE market-data products | Registered exchange-verified equity, corporate, delayed, and index feeds | Backfill, retention, and corrections are agreement-specific | Bulk official BSE source if licensed |
| Standardized Security Master | Scrip code, instrument code, group, name, ISIN, lot, face value, and security-type fields | Current/daily master; historical inactive archive is `UNKNOWN` | BSE permanent venue identity and session state |
| Corporate Actions | Security code/name, ex-date, purpose, record/book-closure/no-delivery/payment dates with CSV | Date filter exists; earliest complete range is `UNKNOWN` | Official action evidence and NSE cross-check |
| Notices and circulars | Dated symbol, name, ISIN, listing, delisting, merger, and index notices | Searchable event evidence; bulk completeness is `UNKNOWN` | Complex identity/action lineage evidence |
| Listings, suspensions, and delistings | New-listing pages and dated notices exist; BSE reports extensive compulsory delistings | No single proven complete PIT file identified | Required evidence family; procurement question remains open |
| Trading holidays | Dated annual equity trading notices | Year-by-year archive; exact earliest complete set `UNKNOWN` | BSE session calendar |
| BSE index levels/constituents/changes | Index pages expose levels/current constituents; index notices publish changes | Full historical constituent dataset and earliest date are `UNKNOWN` | BSE benchmark validation; not required for Nifty membership |

Official evidence:

- [BSE Stock Prices](https://www.bseindia.com/markets/equity/EQReports/StockPrcHistori.aspx?flag=sp)
  exposes price, trading, turnover, and delivery fields.
- [BSE Self Data Feed](https://marketdata.bseindia.com/) documents registered,
  agreement-based exchange feeds and trial access.
- [BSE standardized Security Master format](https://www.bseindia.com/markets/MarketInfo/DownloadAttach.aspx?attachedId=e99e2ca5-95d7-4173-83da-7774412bbb2d&id=20220531-44)
  documents security identifiers and types.
- [BSE Corporate Actions](https://www.bseindia.com/corporates/corporates_act.html)
  exposes dated action records and CSV output.

## Depositories

### NSDL

NSDL officially documents participant/issuer files for an ISIN Master, ISIN Rate
Master, clearing-corporation calendar, and Corporate Action Master. The public
documentation proves formats and operational existence, not public bulk access or a
complete historical ISIN lineage.

- The [NSDL standardized file-format circular](https://nsdl.co.in/downloadables/pdf/2024-0112-Policy-Standardization_of_File_Formats.pdf)
  lists ISIN and Corporate Action masters.
- The [NSDL Security (ISIN) Master format](https://nsdl.co.in/downloadables/pdf/08-Annexure-Circular-for-File-Format-of-Security-%28ISIN%29-Master-download.pdf)
  documents full/incremental files.

Future use: depository-authoritative ISIN state and corporate-action settlement
evidence, subject to participant eligibility, rights, historical depth, and an
effective-date sample.

### CDSL

CDSL documents an ISIN Master, ISIN Rate Master, Corporate Action Master, and
clearing calendar through participant-facing downloads and UDiFF harmonization. Its
own description says the ISIN Master gives **current** admitted ISIN details, so it
must not be treated as historical lineage without archived snapshots.

- [CDSL UDiFF Harmonization](https://www.cdslindia.com/DP/Harmonization.html)
- [CDSL file formats](https://www.cdslindia.com/DP/File%20format.html)

Future use: cross-depository identity and action reconciliation. Coverage and access
remain procurement questions.

## SEBI Disclosures

SEBI is a regulator and disclosure curator, not a daily OHLCV source. Its official
curation pages route users to exchange corporate filings, and its regulations define
the disclosure obligations that create those records.

- [SEBI Corporate Filings curation](https://www.sebi.gov.in/curation/corporate_filings.html)
- [SEBI Equity Cash Market curation](https://www.sebi.gov.in/curation/equity_cash_market.html)

Future use: authoritative rule/version evidence, discovery of exchange disclosures,
and a secondary completeness check. Exchange-disseminated event records remain the
primary warehouse facts.

## Explicitly Missing or Unproven

The official-source survey did not establish a complete, public, machine-ready source
for any of the following:

- effective-dated historical sector assignment for every security;
- complete Nifty 50/100/200/500 constituent history with a guaranteed earliest date
  without subscription;
- one permanent NSE/BSE cross-venue security ID spanning symbol and ISIN changes;
- complete listing, suspension, relisting, and delisting intervals for all eras;
- complete merger/demerger lineage with normalized exchange ratios;
- contractual automated-retention rights for public website files;
- official correction/revision logs for every public historical report.

These are procurement or evidence-reconstruction requirements. They are not gaps that
Alpha may fill with today's classifications or ticker-name guesses.

## Source-Use Gate

A source may enter Warehouse v2 only after all of the following are recorded:

1. source authority and exact dataset name;
2. legal basis for internal storage, research, retention, and backups;
3. delivery protocol and rate limits;
4. earliest guaranteed date and known gaps;
5. sample schema and field dictionary;
6. correction and revision policy;
7. point-in-time publication timestamps or a documented approximation policy;
8. deterministic checksum and duplicate behavior;
9. identity and corporate-action coverage results;
10. owner approval in a versioned source-authorization registry.

[NSE's Data Sharing and Usage Policy](https://www.nseindia.com/static/market-data/nse-data-policy)
states that permitted use and handling are governed by the relevant agreement. Public
availability therefore never bypasses this gate.
