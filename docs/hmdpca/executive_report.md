# Alpha Historical Data Procurement Decision

**Audit:** HMDPCA v1.0  
**Decision date:** 19 July 2026  
**PRODUCTION_INFLUENCE=false**

## Executive Summary

- **Buy an official NSE core first, but only after contract and sample gates.** The
  best-value starting point is Capital Market EOD plus Master Data. Their published
  annual floor is INR 315,000 before tax; that figure excludes historical backfill,
  index history, corporate actions, extra delivery channels, implementation, and
  legal review.
- **Compete corporate actions and index history separately.** Adding NSE EOD
  Corporate Data raises the visible floor to INR 815,000 before tax, while NSE
  Indices history and constituents remain quote-required. A normalized vendor can
  win the corporate-action role if it proves better lifecycle coverage and complete
  retained-use rights at lower total cost.
- **Do not buy BSE by assumption.** Obtain a representative sample first and measure
  BSE-only tradable coverage, corporate-action conflict resolution, and impact on
  Alpha's missed opportunities. Buy it only if those gains are material.
- **Do not mistake convenience for authority.** Broker APIs, public archives, and
  `nse-archives` are useful operational or ingestion tools. None supplies legal data
  rights, point-in-time inactive identity, and correction lineage by itself.

## The Lowest-Cost Defensible Stack

| Layer | Recommendation | Current cost knowledge | Decision |
| --- | --- | --- | --- |
| NSE daily equity | NSE CM EOD | INR 100,000/year/site before tax | Contract and sample |
| NSE identity | NSE Master Data | INR 215,000/year/site before tax | Contract and sample |
| Corporate actions | RFP: NSE/BSE/GFDL/TrueData/institutional specialist | NSE EOD CA is INR 500,000/year/site before tax; others quote | Compete |
| Index levels and membership | NSE Indices | Quote required | Mandatory quote and sample |
| Historical backfill | NSE Data & Analytics | Product and exact backfill quote required | Mandatory quote and sample |
| BSE | BSE direct | Selected tariffs public; complete package quote required | Sample before purchase |
| Live overlap | Upstox | API usage documented as free with account | Operational only |

The lowest visible official floor is therefore **INR 315,000**, not the total
Warehouse v2 budget. The core plus NSE EOD CA visible floor is **INR 815,000**.
Alpha cannot state a complete yearly cost until NSE Indices, backfill, intended-use,
BSE, and vendor quotations are returned.

## Why This Order Improves Decision Quality

**Identity and action safety are more urgent than adding alternative features.**
Without listing/delisting, historical symbol/ISIN/series, and corporate-action
lineage, a larger price dataset can still contain survivorship, discontinuity, and
future-mapping errors. The minimum coherent purchase is price plus identity plus
calendar plus listing status plus corporate actions.

**Delivery and breadth come next.** Official delivery files can strengthen Alpha's
price-volume research, while breadth can strengthen regime evidence. Both need stable
definitions and point-in-time denominators before use.

**Ownership and earnings enrichment should be deferred.** Exchange filings, SEBI,
and AMFI can support low-cost exploratory research. Enterprise point-in-time
ownership, estimates, guidance, and surprises should be purchased only after an
approved experiment demonstrates incremental benchmark value.

## Source Decisions

| Source class | Decision | Reason |
| --- | --- | --- |
| NSE Data & Analytics | Primary core candidate | Official authority and lowest visible official base cost |
| NSE Indices | Mandatory separate candidate | Only appropriate primary for official NIFTY levels and membership |
| BSE | Conditional complement | Official but incremental Alpha value is unmeasured |
| GFDL / TrueData | RFP shortlist | Potential normalization and API convenience; exact rights/depth unknown |
| LSEG / FactSet / Bloomberg / S&P | Institutional upgrade path | Strong identity/action/PIT capability; quote and India sample required |
| Upstox / Zerodha | Live or overlap only | Operational strength does not solve canonical identity and retention |
| `nse-archives` | Adapter only | MIT code license does not license NSE data |
| Yahoo / retail aggregators / GitHub | Reject as authority | Inadequate rights, provenance, corrections, or PIT continuity |

## Recommended Next Sprint

1. Issue one common data dictionary and intended-use schedule to NSE, NSE Indices,
   BSE, GFDL, TrueData, and one institutional vendor.
2. Obtain representative samples before accepting any annual contract.
3. Score samples on field/population coverage, inactive identity, event lineage,
   revision history, and deterministic delivery.
4. Measure BSE incremental contribution at ISIN level before broad procurement.
5. Produce a signed go/no-go memo with complete annualized cost, including taxes,
   exchange pass-throughs, sites/channels, implementation, and exit obligations.

## Open Questions Requiring Direct Confirmation

- What is the earliest complete NSE daily history for inactive and delisted equity
  series under the offered license?
- Does NSE Master Data include archival effective-dated symbol, series, ISIN, and
  listing-status history, or only daily snapshots after subscription begins?
- What exact NIFTY constituent history is available, and does it retain corrections
  and effective dates for additions and removals?
- Can Alpha retain raw and corrected history after contract termination for internal
  research and reproducibility?
- Does EOD Corporate Data fully encode rights, mergers, demergers, successor
  securities, and adjustment factors?
- How much BSE-only tradable and outcome coverage exists beyond Alpha's NSE universe?
- Which vendor supplies the lowest lifetime cost after exchange fees, normalization,
  correction operations, and identity exceptions are included?

## Caveats and Assumptions

- No data was downloaded and no provider sample was measured in this milestone.
- All coverage percentages remain `UNKNOWN_PENDING_SAMPLE`; historical-depth claims
  are documentary, not empirical.
- Published prices are not quotations and may exclude taxes, exchange fees, sites,
  users, channels, backfill, infrastructure, and implementation.
- Legal suitability is a procurement flag, not legal advice. Final rights require
  executed agreements reviewed for Alpha's exact entity and use.
- Quality grades are pre-procurement grades. No source can become grade A without a
  signed contract and deterministic evidence test.

## Deliverables

- [Historical data inventory](historical_data_inventory.md)
- [Coverage matrix](coverage_matrix.csv)
- [Procurement matrix](procurement_matrix.csv)
- [Licensing matrix](licensing_matrix.csv)
- [Cost matrix](cost_matrix.csv)
- [Quality matrix](quality_matrix.csv)
- [Warehouse impact](warehouse_impact.md)
- [Procurement roadmap](procurement_roadmap.md)

## Evidence

The cost decision uses the [NSE domestic tariff effective 1 April
2026](https://nsearchives.nseindia.com/web/mediaattachment/2026-04/Download_Pricing_file_-_Domestic_clients_20260424122229.pdf).
The separate index decision follows the [NSE Indices data subscription
description](https://www.niftyindices.com/offerings/data-subscription). The BSE
sample-first decision is based on its [information-products tariff](https://www.bseindia.com/downloads1/Information_Products_Pricing_Sheet.pdf)
and [self-data portal](https://marketdata.bseindia.com/). Use rights remain subject
to the [NSE Data Sharing and Usage Policy](https://www.nseindia.com/static/market-data/nse-data-policy)
and provider-specific agreements.

