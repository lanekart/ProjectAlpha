# Download Strategy

**Status:** Future implementation design only  
**No downloader exists in this milestone.**  
**Production influence:** None (`PRODUCTION_INFLUENCE=false`)

## Governing Principle

Acquisition starts only after source rights, coverage, and schema have been confirmed.
Public visibility is not authorization for automation or permanent retention.

## Pre-Acquisition Gates

1. Execute or record the applicable source agreement/permission.
2. Confirm internal storage, non-display research, derived analytics, replay, backup,
   correction reprocessing, and retention rights in writing.
3. Record prohibited uses, redistribution constraints, sites/users, expiry, and exit
   requirements.
4. Obtain a data dictionary, sample, historical range, correction policy, and delivery
   SLA.
5. Approve the source in a versioned source-authorization registry.
6. Run a small representative pilot across active, delisted, renamed, split, merger,
   illiquid, and multi-listed securities.

Failure at any gate means no acquisition.

## Initial Backfill Plan

### Phase 1: session inventory

Build the expected exchange-session schedule from official calendars and report
availability. Record expected source objects by venue, segment, dataset, and date.
Do not infer that every security should have traded every session.

### Phase 2: bounded pilot

Acquire only an authorized sample covering:

- one normal recent month;
- one historical year with known format lineage;
- format-transition boundaries;
- known corporate actions and identity changes;
- delisted/suspended securities;
- NSE/BSE dual listings and venue-only listings.

Validate rights, schemas, checksums, corrections, identities, and event coverage before
committing to the full backfill.

### Phase 3: immutable raw backfill

Acquire oldest-to-newest by source family into a content-addressed raw vault. Write an
acquisition journal before and after each object. Failed dates remain explicit retry
items; they are never skipped silently.

Suggested dependency order:

1. trading calendars and format specifications;
2. security/master and listing identity evidence;
3. raw bhavcopy/price and delivery data;
4. corporate actions and issuer events;
5. index constituent history;
6. sector history;
7. depository identity/action confirmations.

### Phase 4: verification and reconciliation

Verify coverage by session, security, series, and source. Reconcile against official
totals and Warehouse v1. Quarantine rather than auto-fix unexplained differences.

### Phase 5: candidate release

Materialize a Warehouse v2 candidate only after all mandatory component gates pass.
Human publication approval is required. Consumer cutover is a later milestone.

## Incremental Update Plan

For each source, define a versioned schedule:

- expected publication and finalization time;
- first fetch window and bounded retry policy;
- checksum/size/schema validation;
- late correction watch window;
- explicit source-unavailable state;
- session-close watermark;
- immutable daily acquisition manifest;
- periodic long-tail reconciliation against official revisions.

An incremental run is idempotent: the same bytes produce the same object ID and no
duplicate canonical row. Different bytes for the same logical report open a revision
case.

## Checksum Policy

- SHA-256 of original bytes is mandatory.
- Preserve provider checksum/signature when supplied.
- Hash decompressed payload and normalized row set separately.
- Verify hashes on every read from the raw vault.
- Store size, media type, archive members, and schema fingerprint.
- Never key an object only by filename or date.

## Duplicate Detection

Classify duplicates at four levels:

1. exact byte duplicate: same content hash;
2. packaging duplicate: different archive bytes, identical payload hash;
3. semantic duplicate: different source rows normalize to same authoritative fact;
4. conflicting duplicate: same natural key, different normalized value.

Exact duplicates are idempotent references. Packaging duplicates are retained with
their own transport provenance. Semantic duplicates are linked. Conflicting duplicates
open reconciliation cases.

## Corruption and Recovery

Detect:

- checksum or byte-length failure;
- unreadable/truncated archive;
- unsafe archive path or unexpected members;
- malformed headers or schema fingerprint change;
- row-count collapse/spike;
- impossible OHLC or negative volume;
- duplicate natural keys;
- partial response presented as complete;
- future or wrong-session payload.

Recovery:

1. quarantine the object and dependent normalized rows;
2. record immutable failure evidence and source response metadata;
3. retry within the authorized bounded policy;
4. compare a replacement as a new object;
5. restore from checksum-verified backup if the local object was damaged;
6. rebuild derived zones from raw objects and manifests;
7. publish a new release if canonical content changes.

Never edit damaged bytes in place.

## Resume and Restart Safety

Every work unit has a deterministic key: provider + dataset + venue + segment + date
or published object ID. State transitions are journaled atomically. On restart, Alpha
revalidates completed objects by hash and resumes unresolved units. No completion flag
is trusted without its manifest and object.

## Rate Limits and Operational Courtesy

- Use only contracted/documented endpoints and credentials.
- Respect rate, concurrency, and delivery windows.
- Do not bypass CAPTCHA, anti-bot, authentication, or access controls.
- Prefer licensed bulk/SFTP delivery over scraping public interfaces.
- Do not add browser automation as a data-acquisition mechanism.
- Stop and classify provider errors; do not rotate identities or evade controls.

## Verification Reports

Each acquisition wave must produce:

- expected vs received objects/sessions;
- checksum and schema results;
- duplicate/revision counts;
- row and security coverage by year;
- identity/action/index/sector coverage;
- reconciliation mismatch rates and reason codes;
- rights/authorization snapshot;
- outstanding unknowns and quarantines;
- release eligibility decision.

## Backup and Exit

Use checksum-verified, encrypted backups consistent with source agreements. Test full
restore into an empty environment. Before vendor exit, preserve only what the agreement
permits, record export/deletion obligations, and produce a version-impact report.

## Explicit Non-Actions

This milestone does not download data, call an exchange endpoint, create credentials,
change Warehouse v1, publish Warehouse v2, run replay, or change production behavior.
