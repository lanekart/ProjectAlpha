# Truth Classification

**Contract version:** `HISTORICAL_TRUTH_CLASSIFICATION_1.0`  
**Production influence:** None (`PRODUCTION_INFLUENCE=false`)

## Decision

Truth class describes **how Alpha knows a field**, not whether the value is bullish,
useful, complete, or conflict-free. Confidence and resolution status are separate.

The closed truth-class vocabulary is:

| Truth class | Meaning | Historical-use rule |
| --- | --- | --- |
| `OFFICIAL` | The value for the relevant field, venue, and effective date is directly supported by the responsible exchange, index administrator, depository, regulator, or issuer filing disseminated by an official venue | Eligible, subject to point-in-time, rights, quality, and conflict checks |
| `OBSERVED` | Alpha directly observed the value in a local or secondary dataset, but official authority, identity, or complete provenance is not established | Diagnostic/research use only; cannot override official evidence |
| `INFERRED` | A deterministic, versioned method derived the value from evidence available by the knowledge cutoff | Allowed only in a named derived view; never presented as source truth |
| `CURRENT_ONLY` | The value is official or observed for the present/current snapshot but lacks an effective-dated historical interval | Valid only at the documented current snapshot; historical backfill forbidden |
| `UNKNOWN` | No evidence supports a value for the requested field and effective date | Must remain null/unknown and fail closed where required |

No extra class may be introduced without a major contract-version change.

## Separate Resolution Status

Truth class does not resolve disagreement. Every field also carries one status:

| Resolution status | Meaning |
| --- | --- |
| `UNCONTESTED` | One admissible value and no conflicting evidence |
| `CONFIRMED` | Independent admissible evidence agrees after normalization |
| `REVISED` | A later authoritative correction supersedes an earlier value; both remain retained |
| `CONFLICTED` | Admissible sources disagree and no rule resolves the difference |
| `QUARANTINED` | Structural, legal, or quality validation prevents canonical use |
| `NOT_APPLICABLE` | The field has no meaning at the requested grain |

An `OFFICIAL + CONFLICTED` value is possible. Official sources can disagree, publish
corrections, or refer to different venues/effective times.

## Mandatory Field Metadata

Each field must retain:

- value and unit;
- truth class;
- resolution status;
- source authority and source record IDs;
- valid/effective interval;
- publication time, retrieval time, and earliest knowledge time;
- confidence components and grade;
- reconciliation version;
- inference method/version when applicable;
- reason codes for unknown, conflict, revision, or quarantine.

`NULL` without this metadata is prohibited because it cannot distinguish unknown,
not applicable, parse failure, or source omission.

## Classification Rules

### OFFICIAL

Use only when all are true:

1. the source is the authority for the field;
2. the raw object or official record is retained with stable provenance;
3. the field applies to the requested venue/entity and date;
4. parsing did not invent or impute the value;
5. use and retention are permitted by the source authorization snapshot.

Examples:

- NSE close for an NSE symbol/series/session from an official NSE bhavcopy;
- BSE deliverable quantity from an official BSE report;
- Nifty 500 membership from an effective-dated NSE Indices constituent file;
- ISIN state from an NSDL/CDSL master snapshot for that effective date;
- listing or delisting date from an exchange event record.

### OBSERVED

Use when the fact was directly present but authority is incomplete. The existing
Warehouse v1 OHLCV is `OBSERVED`, because its local rows are real observations but do
not carry complete official raw provenance, permanent identity, or corporate-action
lineage.

Observed evidence can identify a data gap or support reconciliation. It cannot certify
an official historical universe.

### INFERRED

Inference requires:

- deterministic method ID and version;
- complete input provenance;
- knowledge-time boundary;
- uncertainty/reason codes;
- reproducible output hash;
- no replacement of a conflicting official fact.

Examples include a derived venue-consolidated close, an inferred suspension interval
between two dated notices, or a sector mapping derived from a versioned taxonomy rule.
Inference must be removable without changing raw or official facts.

### CURRENT_ONLY

Current masters, current index constituents, and current sector assignments are
`CURRENT_ONLY` when historical effective dates are absent. A current value can confirm
today's state. It cannot answer yesterday's state.

### UNKNOWN

Unknown is a first-class result. Common reason codes include:

- `SOURCE_NOT_IDENTIFIED`;
- `COVERAGE_OUTSIDE_SOURCE_RANGE`;
- `HISTORICAL_EFFECTIVE_DATE_MISSING`;
- `IDENTITY_UNRESOLVED`;
- `CORPORATE_ACTION_TERMS_INCOMPLETE`;
- `INDEX_MEMBERSHIP_NOT_LICENSED`;
- `SECTOR_HISTORY_NOT_AVAILABLE`;
- `SOURCE_RIGHTS_UNCONFIRMED`;
- `CONFLICT_UNRESOLVED`;
- `RAW_OBJECT_MISSING_OR_CORRUPT`.

## Field Examples for Alpha

| Entity / field | Current classification | Why |
| --- | --- | --- |
| Warehouse v1 daily close | `OBSERVED` | Local OHLCV exists, but original official source lineage is incomplete |
| Warehouse v1 volume | `OBSERVED` | Directly stored but not independently certified |
| NSE official bhavcopy close after future authorized ingestion | `OFFICIAL` | Exchange is authority for its venue observation |
| BSE close for same ISIN/session | `OFFICIAL` | Separate BSE venue truth; not a mismatch merely because value differs |
| Current Nifty 500 member file | `CURRENT_ONLY` for earlier dates | No historical effective interval |
| Historical Nifty 500 membership today | `UNKNOWN` | No authoritative constituent history is currently ingested |
| Current four-tier industry classification | `CURRENT_ONLY` | Public source describes current taxonomy/assignment, not history |
| Historical sector in Warehouse v1 | `UNKNOWN` for PIT use | No authoritative effective-date semantics established |
| First local bar date | `OBSERVED` | Proves first observation, not official listing date |
| Listing date from official exchange record | `OFFICIAL` | Exchange listing authority with effective date |
| Split factor from confirmed official terms | `INFERRED` | Factor is computed; event terms remain official |
| Split event and ex-date from exchange | `OFFICIAL` | Direct official event facts |
| Symbol link based only on similar company name | `INFERRED` and `QUARANTINED` | Candidate identity, not canonical resolution |

## Authority by Field

| Field family | Primary authority | Secondary confirmation |
| --- | --- | --- |
| Venue OHLCV / trades / deliverables | The relevant exchange | Licensed copy of that exchange data; legacy observed rows |
| Exchange symbol, series, security code | The relevant exchange | Clearing files, depository cross-reference |
| ISIN admission/status | NSDL/CDSL and exchange master for venue mapping | Issuer/RTA and official notices |
| Listing/suspension/delisting | The relevant exchange | SEBI orders, depository status, issuer disclosure |
| Nifty membership/weights | NSE Indices | Dated official press releases |
| BSE index membership/weights | BSE Index Services | Dated official index notices |
| Corporate action market dates | Exchange and depository action records | Issuer filing, clearing circular |
| Corporate action economic terms | Official issuer filing plus exchange/depository confirmation | Court/NCLT/SEBI documents for schemes |
| Sector/industry assignment | Named taxonomy administrator for the effective date | Versioned licensed reference vendor |
| Trading calendar | Exchange circular/calendar plus observed market report | Clearing calendar |

## Precedence Is Not a Global Source Ranking

There is no rule saying “NSE beats BSE” or “depository beats exchange” for all fields.
Authority is field- and venue-specific:

- NSE controls its own market observation; BSE controls its own.
- The exchange controls its trading symbol; the depository controls ISIN admission.
- NSE Indices controls Nifty membership.
- Official corrections beat earlier versions from the same authority only after the
  correction's knowledge time.
- Legacy or vendor data can confirm but never silently overwrite the responsible
  authority.

## Promotion Rules

1. `UNKNOWN` cannot be promoted by majority vote among non-authoritative sources.
2. `CURRENT_ONLY` cannot be copied backward.
3. `INFERRED` cannot be relabeled `OFFICIAL`, even with high confidence.
4. A conflict must remain visible until a versioned rule or authoritative revision
   resolves it.
5. Every adjusted value remains `INFERRED`; its source event terms can be `OFFICIAL`.
6. Research may mix truth classes only in a view named `MIXED_DIAGNOSTIC` and must
   report class shares.
7. Production eligibility is outside this milestone and remains unchanged.
