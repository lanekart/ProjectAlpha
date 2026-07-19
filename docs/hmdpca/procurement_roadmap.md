# Warehouse v2 Procurement Roadmap

**PRODUCTION_INFLUENCE=false**

## Recommended Acquisition Order

### P0 - Contract and Sample Before Purchase

1. Freeze Alpha's intended-use schedule: permanent local retention, internal
   non-display research, replay, derived analytics, backup, correction reprocessing,
   and exit export. Redistribution is out of scope.
2. Request NSE samples and contracts for Capital Market EOD, Master Data, historical
   backfill, EOD Corporate Data, delivery data, and correction files.
3. Request NSE Indices samples and a quote for historical index levels, total-return
   values, and effective-dated constituents for NIFTY 50, Next 50, 100, 200, 500,
   Midcap, Smallcap, and sector indices.
4. Run a corporate-action RFP across NSE, BSE, GFDL/TrueData, and one institutional
   normalization vendor. Compare field completeness and identity lineage, not labels.
5. Obtain a BSE sample and measure its incremental ISIN, liquidity, corporate-action,
   and missed-opportunity contribution before buying a broad package.

### P1 - Authoritative Core

Purchase only after P0 gates pass:

- NSE Capital Market EOD and Master Data;
- licensed historical backfill with original/revision metadata;
- the winning corporate-action package;
- NSE Indices levels/TRI/constituent history; and
- official trading calendars, listing status, and delivery fields included in the
  contracted files.

Load these into a quarantined Warehouse v2 candidate. Do not replace Warehouse v1.

### P2 - Reconciliation and Coverage Expansion

- Add BSE if the sample proves material incremental value.
- Add a normalized identity/corporate-action vendor if official sources leave
  unresolved lineage above the acceptance threshold.
- Retain Upstox or another broker as a live/overlap source, never as historical
  authority.
- Pin and fixture-test `nse-archives` only as an ingestion adapter for data Alpha is
  already entitled to retrieve.

### Deferred - Enrichment

- security-level institutional ownership;
- mutual-fund portfolio normalization;
- point-in-time earnings estimates, guidance, and surprises;
- tick/order-book history; and
- premium global terminal/data-license bundles.

These move forward only when a named research experiment can justify the cost and the
core warehouse is certified.

## Published Cost Envelope

The visible NSE tariff establishes floors, not complete project budgets:

| Stack | Published annual floor before tax | Excluded and still unknown |
| --- | ---: | --- |
| NSE CM EOD + Master | INR 315,000 | Historical backfill, index data, CA, setup, extra sites/channels |
| NSE CM EOD + Master + EOD CA | INR 815,000 | Historical backfill, index data, setup, extra sites/channels |
| NSE CM EOD + Master + full Corporate Data | INR 1,375,000 | Historical backfill, index data, setup, extra sites/channels |

The EOD CA and full Corporate Data products are alternatives for budgeting purposes;
Alpha should not assume it needs both. Taxes, levies, implementation, storage,
support, and legal review are outside these figures.

## Procurement Gates

Every source must pass all gates:

| Gate | Pass condition | Failure result |
| --- | --- | --- |
| Rights | Signed terms cover retention, internal research, non-display, backup, derived analytics, corrections, and exit export | Reject or renegotiate |
| Coverage | Representative sample measures required symbols, dates, series, and fields | Keep coverage unknown; do not buy |
| Identity | Permanent IDs and effective-dated symbol/ISIN/series history pass edge cases | Reject as authority |
| Point in time | Publication and revision timestamps prevent future leakage | Research-only |
| Corporate action | Raw/adjusted series and event terms reconcile known events | Quarantine |
| Reproducibility | Bulk/API delivery is checksummed, versioned, restart-safe, and documented | Reject operationally |
| Corrections | Provider exposes correction cadence and reproducible restatements | Reject as canonical source |
| Economics | Incremental subsystem value exceeds duplication and operating burden | Defer |

## Representative Sample Design

The sample should include at least:

- active large-, mid-, small-, and illiquid securities;
- IPO, delisting, suspension, relisting, symbol reuse, and series-change cases;
- split, bonus, dividend, rights, merger, and demerger events;
- NSE-only, BSE-only, and dual-listed securities;
- index additions/removals and sector reclassifications;
- pre-2016, Warehouse v1 overlap, and current periods; and
- known source conflicts and corrected sessions.

The sample produces measured field and population coverage. Marketing statements do
not substitute for it.

## RFP Questions

1. What is the exact earliest date for every required field and inactive security?
2. Are original and revised observations both available with publication timestamps?
3. Are security, company, listing, series, ISIN, and successor identities effective
   dated?
4. What adjustments are applied to price and volume, and can raw data be retained?
5. Which rights survive termination, and can Alpha retain an archival copy?
6. Are internal research outputs and non-reversible derived analytics permitted?
7. What exchange pass-through fees, site, user, medium, API, cloud, and backup fees
   apply?
8. What are the correction SLA, support hours, delivery guarantees, and exit process?

## Stop Conditions

Procurement stops when rights are ambiguous, samples exclude inactive securities,
historical constituents are reconstructed from current membership, data cannot be
retained after termination, or pricing is presented without the applicable exchange
fees. No downloader or warehouse migration belongs in this milestone.

