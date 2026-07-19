# Project Alpha Data Vendor & Coverage Selection Audit

**Decision date:** 18 July 2026  
**Priority:** P0  
**Scope:** Research and procurement decision support only  
**Production influence:** None

## Executive decision

Alpha should not use a broker API or a public/community source as its permanent
authoritative warehouse. The best value design is a split stack:

1. license official NSE end-of-day prices and master data for the permanent raw
   warehouse;
2. procure corporate actions either from NSE or from a separately contracted
   specialist after a field-by-field backfill and retention test;
3. use a broker API only for current operational prices and live monitoring; and
4. add BSE only after an ISIN-level point-in-time overlap study proves incremental
   universe or outcome value.

The published annual floor for NSE cash-market EOD plus master data is **₹3.15
lakh before tax**. Adding NSE corporate data raises the published annual total to
**₹8.15 lakh before tax**. Historical backfill, setup, additional sites, and the
precise rights Alpha requires remain quote- and contract-dependent. The applicable
[NSE domestic pricing schedule](https://nsearchives.nseindia.com/web/mediaattachment/2026-04/Download_Pricing_file_-_Domestic_clients_20260424122229.pdf)
lists cash-market EOD at ₹1 lakh, master data at ₹2.15 lakh, and corporate data at
₹5 lakh per site per year.

This recommendation is conditional. Alpha must receive written rights for local
retention, internal non-display research, derived analytics, replay, backup and
disaster recovery, correction reprocessing, and an exit export. Public access or
API access alone does not establish those rights. The [NSE Data Policy](https://www.nseindia.com/static/market-data/nse-data-policy)
places use, handling, transmission, and redistribution under the applicable
agreement.

## Decision in one page

| Decision | Recommendation |
| --- | --- |
| Best overall choice | Official NSE warehouse, specialist corporate-action feed if cheaper and contract-complete, broker live feed |
| Best value for money | NSE EOD + master at the ₹3.15 lakh published floor, with CA-only competitive RFP and Upstox/FYERS/Angel live |
| Best MVP stack | Preserve legacy data as quarantined evidence, buy official NSE data going forward, broker live, do not claim historical authority until backfill and identity are licensed |
| Best long-term institutional stack | NSE + BSE authoritative feeds, plus LSEG/FactSet/Bloomberg-class identity and corporate-action normalization where justified |
| Do not use as authoritative warehouse | Upstox, Zerodha, Angel One, FYERS, Alice Blue, Yahoo Finance, Alpha Vantage retail, Twelve Data retail, Stooq, GitHub datasets |
| Procurement gate | No source enters the authoritative zone until rights, point-in-time identity, revisions, backfill, and correction SLAs pass a sample and contract review |

## Method and scoring

Evidence was taken from official exchange, provider, regulator, and product
documentation available on the decision date. Marketing claims are treated as
claims, not observed service quality. Unknown permissions and prices remain
unknown.

Compatibility scores use this deterministic scale:

- **5:** authoritative or institutionally complete for the stated role;
- **4:** strong fit, subject to a signed entitlement schedule;
- **3:** workable with material gaps or a second source;
- **2:** partial or operational use only;
- **1:** incidental capability, unsuitable as system of record;
- **0:** unavailable, unproven, or incompatible.

Scores do not override legal terms. A technically excellent feed with no written
retention right is not warehouse-approved.

## Alpha's present coverage baseline

The local `data/ingestion.duckdb` warehouse was inspected read-only:

| Measure | Observed value |
| --- | ---: |
| Daily price rows | 4,898,586 |
| Distinct symbols | 5,340 |
| Sessions | 2,466 |
| Date range | 8 Jul 2016 to 10 Jul 2026 |
| Exchange labels | NSE only |
| Latest-session symbols | 2,370 |
| Symbols on 28 Mar 2025 | 2,108 |
| Median bars per symbol | 547 |

The warehouse therefore covers **100% of Alpha's current universe by its own NSE
label**, but that is a construction fact, not proof of national-market completeness.
On 28 March 2025 Alpha held 2,108 symbols, equal to 77.5% of the 2,720 companies NSE
reported listed for FY 2024-25. This is an approximate company-to-symbol comparison;
series and security multiplicity prevent treating it as an exact security coverage
ratio. NSE reported over 2,700 listed securities and FY 2024-25 average daily equity
turnover of ₹112,963 crore on its [equity market overview](https://www.nseindia.com/static/products-services/about-equity-market).

The current table contains OHLCV, exchange, and sector. It does not contain
effective-dated ISIN, series, security ID, listing history, symbol history, or a
versioned corporate-action ledger. Those omissions, rather than raw candle volume,
are Alpha's largest warehouse-quality gap.

## Consolidated provider matrix

| Provider | Historical | Live | Corporate actions | Identity | Warehouse fit | Legal clarity | Published cost | Overall |
| --- | --- | --- | --- | --- | ---: | ---: | --- | --- |
| NSE Data & Analytics | EOD and historical products; earliest licensed backfill to confirm | L1/L2/L3/TBT, snapshots, delayed | Strong exchange source | Master data; historical lineage must be contracted | 5/5 | 4/5 | EOD ₹1L; master ₹2.15L; CA ₹5L/yr/site | **Authoritative core** |
| BSE Market Data | Daily/monthly/yearly pages and licensed products; earliest bulk backfill to confirm | L1/L2/L3 and delayed feeds | Strong exchange source | ISIN on CA/search; historical lineage to confirm | 4/5 | 3/5 | Selected live tariffs published; warehouse package quote | **Authoritative complement** |
| Upstox | Daily/weekly/monthly from Jan 2000; intraday from Jan 2022 | REST/WebSocket, LTPC/full/depth | Not a complete CA ledger | Current instrument keys/ISIN, not PIT inactive history | 2/5 | 1/5 | Data API free | Operational/secondary only |
| Zerodha Kite Connect | Multi-year candles; exact earliest date varies | REST/WebSocket | Not complete | Current tokens/master, not historical identity | 1/5 | 4/5 restrictive | ₹500/month | Operational only; external data-platform use restricted |
| Angel One SmartAPI | Historical candles; earliest date not promised | WebSocket/REST | Not complete | Current instruments | 1/5 | 1/5 | Free | Operational/secondary only |
| FYERS API | Historical API; earliest date not promised | REST/WebSocket | Not complete | Current symbol master | 1/5 | 1/5 | Free | Operational/secondary only |
| Alice Blue | NSE day/minute history documented for two years | WebSocket market/depth | Not complete | Current contracts | 1/5 | 1/5 | Broker access | Weak historical fit |
| Global Datafeeds | NSE EOD from 2010; BSE from 2007; short tick/minute windows | REST/WebSocket/FIX and other APIs | Broad API taxonomy; public history window only 30 days | ISIN in CA payload; full PIT lineage unproven | 4/5 | 4/5 | Quote required | **Licensed shortlist** |
| TrueData | Historical/EOD advertised; public depth not fully specified | Authorized real-time/tick/depth APIs | Advertised | Reference support advertised; PIT depth to prove | 3/5 | 4/5 | Quote required | **Licensed shortlist** |
| Symphony Fintech XTS | Intraday archive from date of access; not a deep backfill source | Strong market-data gateway | Limited | Current master includes series/ISIN | 1/5 | 3/5 | Quote required | Live infrastructure, not warehouse source |
| Spider Software | EOD/intraday chart history, bulk depth unclear | Terminal/feed products | Product-dependent | Not evidenced for PIT identity | 1/5 | 1/5 | Quote required | Research terminal, not system of record |
| LSEG / Refinitiv | Daily history from 2000; tick history 30+ years | Broad L1/L2 and real-time feeds | Deep normalized coverage | Strong cross-reference and inactive security data | 5/5 | 5/5 | Quote required | **Premium institutional** |
| FactSet | APAC price history from 1985; active/inactive global coverage | Snapshot and exchange feeds | Splits/dividends/events and adjustments | Strong symbology and permanent IDs | 5/5 | 4/5 | Quote required | **Premium institutional** |
| Morningstar | Scheduled equity/reference feeds; exact India depth to quote | Not the strongest primary India live option | Strong reference/fund data; equity CA package-dependent | Strong reference data, package-dependent | 3/5 | 4/5 | Quote required | Specialist complement |
| S&P Capital IQ | Price package-dependent | Data delivery/feed package-dependent | Managed CA covers broad global securities | Strong reference/CA identifiers | 3/5 | 4/5 | Quote required | CA/reference specialist |
| Bloomberg | 20+ years bulk; 17-year PIT product; broad tick/reference | B-PIPE real-time/non-display | Deep enterprise CA | Strong security master and identifiers | 5/5 | 5/5 | Quote required | **Premium institutional** |
| Yahoo Finance | Unofficial/unsupported bulk history | Delayed/website-oriented | Adjustment lineage not contractual | Weak | 1/5 | 1/5 | Free | Research-only; reject as authority |
| Alpha Vantage | 20+ years claimed; India coverage not fully evidenced | API, plan-dependent | Splits/dividends in adjusted series | Weak PIT identity | 2/5 | 4/5 | Retail from US$49.99/month; commercial quote | Research/validation only |
| Twelve Data | NSE/BSE EOD listed; full history exchange-dependent | India shown as EOD, not live | CA/reference fields advertised | ISIN/MIC, PIT history unproven | 3/5 | 4/5 | Individual from US$790/yr; business from US$4,990/yr | Secondary EOD only after rights confirmation |
| Stooq | India coverage and provenance not established | Not established | Not established | Not established | 0/5 | 0/5 | Free | Reject as authority |
| GitHub datasets | Dataset-specific snapshots | None reliable | Usually absent or undocumented | Usually absent | 0/5 | 0/5 | Usually free | Research-only; provenance risk |

## Compatibility scorecard

| Provider | MTE | Historical warehouse | Corporate action | Identity | Live feed |
| --- | ---: | ---: | ---: | ---: | ---: |
| NSE Data & Analytics | 5 | 5 | 5 | 4 | 5 |
| BSE Market Data | 5 | 4 | 5 | 4 | 5 |
| Upstox | 2 | 2 | 1 | 2 | 4 |
| Zerodha Kite Connect | 2 | 1 | 1 | 2 | 4 |
| Angel One SmartAPI | 2 | 1 | 1 | 1 | 4 |
| FYERS API | 2 | 1 | 1 | 2 | 4 |
| Alice Blue | 1 | 1 | 0 | 1 | 3 |
| Global Datafeeds | 4 | 4 | 3 | 3 | 4 |
| TrueData | 4 | 3 | 3 | 3 | 5 |
| Symphony Fintech | 3 | 1 | 1 | 3 | 5 |
| Spider Software | 1 | 1 | 1 | 1 | 3 |
| LSEG / Refinitiv | 5 | 5 | 5 | 5 | 5 |
| FactSet | 5 | 5 | 5 | 5 | 4 |
| Morningstar | 3 | 3 | 4 | 4 | 2 |
| S&P Capital IQ | 4 | 3 | 5 | 5 | 3 |
| Bloomberg | 5 | 5 | 5 | 5 | 5 |
| Yahoo Finance | 1 | 1 | 1 | 1 | 1 |
| Alpha Vantage | 2 | 2 | 2 | 1 | 2 |
| Twelve Data | 3 | 3 | 3 | 3 | 2 |
| Stooq | 0 | 0 | 0 | 0 | 0 |
| GitHub datasets | 0 | 0 | 0 | 0 | 0 |

## Provider findings

### Official exchanges

**NSE Data & Analytics.** The [EOD and historical subscription](https://www.nseindia.com/static/market-data/eod-historical-data-subscription)
supports EOD security and trade data through licensed delivery. The [real-time
product](https://www.nseindia.com/static/market-data/real-time-data-subscription)
supports L1, L2, L3, tick-by-tick, snapshots, and delayed feeds. NSE is the best
primary source for Alpha's present NSE-only universe. The procurement package must
explicitly include historical master, effective-dated symbol/series/ISIN changes,
inactive and delisted records, raw prices, deliverable volume, corrections, and
point-in-time publication metadata. Current master data alone is insufficient.

**BSE Market Data.** BSE offers exchange-verified equity, derivatives, corporate,
indices, and delayed products through its [self-service data portal](https://marketdata.bseindia.com/).
Its [stock price history](https://www.bseindia.com/markets/equity/EQReports/StockPrcHistori.aspx?flag=sp)
includes price, turnover, trades, and deliverable quantity, while [corporate action
search](https://www.bseindia.com/corporates/corporates_act.html) supports security
name/ISIN and CSV. Public pages are useful for verification, not proof of automated
retention rights. A bulk internal-use package and historical identity schedule need
a direct quote.

### Broker APIs

**Upstox.** The [V3 historical API](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/)
documents daily, weekly, and monthly candles from January 2000 and intraday history
from January 2022. The [V3 market feed](https://upstox.com/developer/api-documentation/v3/get-market-data-feed/)
provides WebSocket LTPC, full, and depth modes. Upstox is Alpha's strongest free
operational feed candidate, but public documentation does not grant the permanent,
commercial, non-display warehouse rights required here.

**Zerodha.** Kite Connect costs [₹500 per month](https://zerodha.com/products/api/)
and supplies WebSocket and historical candles. Zerodha's [API FAQ](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/kite-connect-api-faqs)
says Kite data cannot be used on other platforms and cites exchange redistribution
policy. That clarity makes it unsuitable for Alpha's authoritative platform data,
even though it is operationally mature.

**Angel One and FYERS.** [SmartAPI](https://smartapi.angelone.in/faq) and the
[FYERS API](https://fyers.in/products/api) offer free live and historical access.
Their public materials do not establish inactive-security history, complete
corporate actions, or Alpha's required permanent retention and derived-use rights.
They are live-feed alternatives, not systems of record.

**Alice Blue.** The [historical documentation](https://ant.aliceblueonline.com/productdocumentation/Historical%20Data/)
describes only two years of NSE daily/minute history and no equivalent BSE chart
history. It has a [WebSocket feed](https://ant.aliceblueonline.com/productdocumentation/Websocket/),
but is a poor fit for Alpha's ten-year replay warehouse.

### Licensed Indian vendors

**Global Datafeeds.** Public documentation states NSE daily/weekly/monthly history
from 2010 and BSE from 2007, with shorter tick and minute windows. It offers
[real-time, historical, EOD, and full-exchange APIs](https://globaldatafeeds.in/apis/).
Its [commercial-use guidance](https://globaldatafeeds.in/global-datafeeds-apis/global-datafeeds-apis/pricing-sales/who-can-purchase/)
distinguishes personal retail use from commercial use requiring exchange agreements.
The corporate API is promising, but the currently documented [history availability](https://docs.globaldatafeeds.in/type-of-corporate-data-available-1142925m0)
is only 30 days. Global Datafeeds should be invited to the RFP only if it can supply
a complete historical backfill, point-in-time identity, corrections, and contractual
retention.

**TrueData.** Its [market-data API](https://www.truedata.in/market-data-apis)
advertises authorized NSE/BSE real-time, tick, depth, EOD, and corporate feeds and
states that redistribution requires exchange and TrueData approval. It is a credible
licensed shortlist candidate, but public documentation is insufficient to score
earliest history, inactive identities, revision lineage, and corporate-action
backfill. Those need a sample and data dictionary.

**Symphony and Spider.** [Symphony XTS](https://symphonyfintech.com/xts-market-data-front-end-api-v2/)
is a capable live market-data gateway with current series/ISIN master data, but its
archived intraday history begins from access and it is not a deep historical source.
[Spider Software](https://spidersoftwareindia.com/products.php) is a charting and
terminal product; public evidence does not establish a bulk, point-in-time,
commercial warehouse license.

### Premium institutional vendors

**LSEG / Refinitiv.** LSEG documents [equity history from 2000](https://www.lseg.com/en/data-analytics/financial-data/pricing-and-market-data/equities-pricing-data),
real-time L1/L2, daily terms, corporate actions, cross-reference IDs, and API/cloud/
SFTP delivery. Its [Tick History](https://www.lseg.com/en/data-analytics/market-data/data-feeds/tick-history)
extends beyond 30 years. This is one of the strongest normalized-data options, but
field entitlements, exchange fees, India inactive coverage, retention, and price are
quote-dependent.

**FactSet.** The [Prices and Returns API](https://www.factset.com/marketplace/catalog/product/factset-prices-and-returns-api)
includes OHLCV, active/inactive securities, splits, dividends, and APAC history from
1985. FactSet also provides strong symbology and corporate-action normalization. It
is a strong historical/reference candidate, with exact NSE/BSE entitlements and
non-display rights to be contracted.

**Bloomberg.** [Data License](https://professional.bloomberg.com/products/data/data-management/data-license/)
offers REST, SFTP, and cloud delivery with 20+ years of bulk data, while
[B-PIPE](https://professional.bloomberg.com/products/data/enterprise-catalog/real-time-data-feed/)
supports normalized real-time and non-display applications. Bloomberg also offers
security master and corporate actions. It is technically complete and commercially
quote-dependent.

**S&P Capital IQ and Morningstar.** [S&P Managed Corporate Actions](https://www.spglobal.com/market-intelligence/en/solutions/mca)
is a strong CA/reference specialist, particularly where lifecycle normalization is
more important than live Indian prices. [Morningstar Data Feeds](https://www.morningstar.com/business/products/direct/data-feeds)
support licensed scheduled delivery and are stronger for reference, fundamentals,
and funds than for Alpha's primary India tick feed. Both require package-level
coverage and price confirmation.

### Public and community sources

**Yahoo Finance.** Yahoo's [developer terms](https://legal.yahoo.com/us/en/yahoo/terms/product-atos/apiforydn/index.html)
provide revocable, as-is access and do not establish a supported commercial bulk
warehouse. Provenance, corrections, inactive identity, and exchange entitlement are
not adequate.

**Alpha Vantage.** The [API documentation](https://www.alphavantage.co/documentation/)
claims 20+ years of daily history and adjusted split/dividend data. Its [terms](https://www.alphavantage.co/terms_of_service/)
make the default license personal and non-commercial and explicitly route commercial
investment analysis/research users to a commercial agreement. Retail pricing is not
the cost of Alpha's required rights.

**Twelve Data.** Its [exchange list](https://twelvedata.com/exchanges) shows NSE and
BSE as EOD rather than live. [Business pricing](https://twelvedata.com/pricing-business)
starts at a published US$4,990 per year, while exchange licenses and add-ons may
still apply. Its [terms](https://twelvedata.com/terms) distinguish storage,
non-display, redistribution, plan, and exchange-specific rights. It may be a useful
secondary EOD validator only after written India source lineage and retention rights.

**Stooq and GitHub.** No authoritative Indian exchange entitlement, point-in-time
identity, correction policy, or commercial retention right was established for
Stooq. GitHub datasets inherit unknown upstream rights and commonly embed
survivorship, adjustment, and provenance defects. Neither should enter Alpha's
authoritative zone.

## Corporate actions and identity

Alpha needs more than split-adjusted candles. The required event ledger must cover:

- cash and special dividends;
- bonus issues, splits, consolidations, and rights;
- mergers, demergers, schemes, and acquisitions;
- old and new ISINs and symbols with effective dates;
- series changes, listing, suspension, relisting, and delisting;
- event announcement, ex, record, effective, and payment dates;
- raw and adjusted factors with price and volume treatment;
- source publication time, revisions, cancellations, and supersession links.

The cheapest plausible alternative to NSE's ₹5 lakh corporate-data package is a
CA-only commercial contract. Global Datafeeds, TrueData, S&P, LSEG, FactSet, and
Bloomberg should be asked to quote only the required event and identity fields.
Global Datafeeds' public API covers dividends, bonuses, splits, rights, mergers and
other events, but its documented 30-day history means it does not yet satisfy
backfill. Public NSE/BSE filings can be used as reconciliation evidence only after
automated retention rights are confirmed. NSDL operationally maintains ISIN and
corporate-action masters, but no public documentation reviewed here establishes a
research warehouse product for Alpha.

## Is NSE-only sufficient?

### What the evidence supports

- It covers 100% of Alpha's current stored rows because the present warehouse is
  NSE-only.
- It covers the venue that represented approximately **93.6%** of combined NSE and
  BSE FY 2024-25 cash average daily turnover: NSE ₹112,963 crore versus BSE ₹7,766
  crore. The BSE figure is reported in its [FY 2024-25 annual report](https://archives.nseindia.com/annual_reports/AR_27090_BSE_2024_2025_A_24072025103555.pdf).
- For a liquidity-filtered NSE strategy universe, NSE-only is sufficient for an MVP
  price warehouse and likely captures the dominant executable cash market.

### What it does not support

- National-market completeness. SEBI reported 5,396 BSE and 2,673 NSE listed
  companies in December 2024; the counts overlap and cannot be subtracted to infer
  BSE-only names. See the [SEBI bulletin](https://www.sebi.gov.in/sebi_data/attachdocs/jul-2025/1753874458062.pdf).
- BSE-only mainboard and SME securities, venue-specific price formation, or cases
  where BSE is the more liquid venue.
- Independent cross-exchange detection of bad ticks, suspensions, corporate-action
  mismatches, symbol changes, or stale venue data.
- A complete delisted and historical identity universe.

BSE materially changes Alpha when the candidate is BSE-only, an SME or inactive
security, BSE has superior liquidity, venue prices disagree, or an identity/corporate
action is missing from NSE evidence. It is likely to change fewer liquid large-cap
signals because NSE dominates cash turnover, but the exact outcome impact is
**unknown** until Alpha performs an ISIN-level point-in-time NSE/BSE join and replay.

## Scenario analysis

Scores are 1 (weak) to 5 (strong). “Quote required” is deliberately not replaced by
an invented estimate.

| Scenario | Published annual cost | Warehouse quality | Replay | Corporate actions | Legal confidence | Operational complexity | Decision |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| A. Existing legacy + broker live | ₹0–₹6,000 incremental | 2 | 2 | 1 | 1 | 2 | Cheapest, but not institutionally defensible |
| B. Official NSE only | ₹8.15L + tax + backfill quote | 5 for NSE | 4 | 5 for NSE | 4 after contract | 3 | Strong single-venue core |
| C. Official NSE + official BSE | ≥₹8.15L + BSE quote + tax/backfills | 5 | 5 | 5 | 4 after contracts | 4 | Best India authority; likely premature for MVP |
| D. Official EOD + broker live | ₹8.15L + ₹0–₹6,000 + tax/backfill | 5 for NSE | 4 | 5 for NSE | 4 for warehouse; live rights separate | 3 | **Best value complete baseline** |
| E. Licensed vendor + broker live | Vendor quote + ₹0–₹6,000 | 3–4 | 3–4 | 3–4 | 3–4 after contract | 2 | Potentially cheaper; must prove authority/backfill |
| F. Premium institutional stack | Entirely quote required | 5 | 5 | 5 | 5 after contract | 5 | Best capability, unjustified before scale |

Notes:

- Scenario B and D use the published NSE EOD + master + corporate-data total. A
  leaner price-and-identity floor is ₹3.15 lakh before tax, with CA priced separately.
- Historical backfill and historical identity costs are not published in the
  reviewed schedule and remain additional.
- Broker figures exclude brokerage, account charges, exchange entitlements, and any
  separately negotiated commercial data rights.
- A source is not legally “high confidence” until Alpha's actual use and retention
  clauses are signed.

## Cheapest institutional configuration

The lowest published-cost architecture that can become institutionally defensible is:

1. **NSE EOD cash market:** ₹1 lakh/year/site before tax.
2. **NSE master data:** ₹2.15 lakh/year/site before tax.
3. **Corporate actions:** run a CA-only RFP; use NSE's ₹5 lakh/year/site package if
   no lower-cost source passes the same field, history, correction, and rights tests.
4. **Historical backfill:** one-time or licensed recurring quote, including inactive
   and delisted securities and original publication/revision metadata.
5. **Live operations:** Upstox, FYERS, or Angel One for monitoring only, with no
   permanent warehouse ingestion unless written commercial rights are obtained.
6. **Reconciliation:** public exchange pages and a second broker may flag anomalies,
   but never silently overwrite the authoritative raw layer.

The known published floor is ₹3.15 lakh/year plus tax and unknown backfill/CA costs.
The known published price for the complete NSE EOD/master/CA package is ₹8.15
lakh/year plus tax and backfill. Whether a licensed Indian vendor can beat that
complete price while meeting every right and field requirement is an RFP question,
not a fact visible in public pricing.

## Upgrade path

### Stage 1 — MVP

**Providers:** NSE EOD + master; CA-only RFP or NSE CA; Upstox/FYERS/Angel live.  
**Approximate annual cost:** ₹3.15 lakh published floor plus CA/backfill quote, or
₹8.15 lakh with NSE CA, before tax.  
**Expected data confidence:** High for current NSE raw EOD after contract; medium
for history until backfill and identity tests pass.  
**Remaining limitations:** BSE-only coverage, full historical identity, vendor exit
continuity, live retention rights.

### Stage 2 — Growing capital

**Providers:** Stage 1 plus BSE EOD/identity/CA where the point-in-time overlap study
shows incremental value; add a licensed normalized reference vendor if exchange
identity is incomplete.  
**Approximate annual cost:** NSE published package plus BSE and specialist quotes.  
**Expected data confidence:** High for India EOD and replay after cross-exchange and
corporate-action reconciliation.  
**Remaining limitations:** Premium global symbology, deep tick history, advanced SLA
and multi-region distribution.

### Stage 3 — Institutional scale

**Providers:** Official NSE+BSE entitlements plus LSEG, FactSet, or Bloomberg-class
normalization/reference and an institutional real-time feed where justified.  
**Approximate annual cost:** Quote required; do not budget from retail API prices.  
**Expected data confidence:** Very high after entitlement, sample, and SLA approval.  
**Remaining limitations:** Contract complexity, exchange pass-through fees, user/site
controls, audit obligations, and vendor concentration.

## Procurement acceptance test

No vendor should be selected from a slide deck alone. Require a deterministic sample
covering active, renamed, merged, demerged, suspended, delisted, relisted, SME,
EQ/BE-series, and symbol-reuse cases. The vendor must provide:

1. earliest available date by venue, instrument status, and interval;
2. active and inactive population counts by year;
3. raw unadjusted OHLCV and deliverable quantity;
4. weekly/monthly methodology and trading-calendar rules;
5. every corporate-action field and adjustment rule;
6. effective-dated symbol, series, ISIN, security ID, listing and delisting history;
7. original publication time, corrections, cancellations, and revision history;
8. rate limits, bulk extraction, checksum, rerun, and disaster-recovery process;
9. API/SFTP/cloud formats and full export on termination;
10. uptime, correction, and support SLAs;
11. written local retention, backup, internal non-display, derived-data, replay,
    model-training, and proprietary-research rights;
12. explicit restrictions on display, redistribution, client reporting, and Alpha
    Terminal usage;
13. all setup, exchange, site, user, API, backfill, and annual fees; and
14. a contract clause preventing silent removal or retrospective rewriting of frozen
    point-in-time evidence.

## Final recommendation

### Best overall choice

Use official NSE as Alpha's authoritative raw warehouse, procure corporate actions
as a separable contract, and use a broker only for live operations. Add BSE after a
measured point-in-time coverage and outcome study.

### Best value for money

Start with the ₹3.15 lakh published NSE EOD + master floor, run a competitive CA-only
RFP, and keep Upstox/FYERS/Angel live data outside the authoritative storage zone.

### Best MVP stack

NSE EOD + master + contract-complete CA source + Upstox live. Quarantine the existing
legacy history with immutable provenance labels; do not relabel it as official.

### Best long-term institutional stack

Official NSE and BSE venue data, backed by an LSEG/FactSet/Bloomberg-class identity
and corporate-action normalization layer where the economics and error reduction
justify it.

### Principal risks

- NSE-only omits BSE-only and venue-divergent evidence.
- A licensed vendor may normalize away original point-in-time facts unless raw and
  revised forms are both retained.
- Broker feeds can fail legal, inactive-identity, and correction requirements even
  when their APIs are technically excellent.
- Public datasets can introduce survivorship, adjustment, source, and redistribution
  defects that Alpha cannot later audit away.
- Premium stacks can create high fixed costs and vendor lock-in before Alpha has
  evidence that the incremental fields improve decisions.

### Unknowns requiring direct confirmation

- NSE and BSE earliest bulk backfill, inactive/delisted coverage, historical master,
  revision lineage, backup, derived-data, and model-research rights;
- BSE internal EOD/master/CA pricing and exchange pass-through fees;
- Global Datafeeds and TrueData full-history CA/identity backfill and commercial
  retention terms;
- exact Indian exchange entitlements and costs from LSEG, FactSet, S&P, Morningstar,
  and Bloomberg;
- Twelve Data's underlying India source, inactive coverage, and commercial storage
  rights;
- the actual count and outcome value of BSE-only or BSE-primary instruments in
  Alpha's intended universe; and
- every vendor's rights for Alpha Terminal display versus internal non-display
  analytics.

Until these unknowns are answered in writing and a sample passes, **no new provider
is approved as Alpha's authoritative warehouse source**.
