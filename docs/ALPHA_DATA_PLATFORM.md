# Alpha Data Platform v1.0

## Status

`ALPHA_DATA_PLATFORM_v1.0` is the frozen architecture contract for Alpha's
future historical truth platform. It has no production influence, contains no
downloaded market data, does not migrate Warehouse v1, and does not change
replay or any downstream consumer.

## Architecture

```text
Official Sources
    -> Immutable Raw Layer
    -> Lossless Normalized Layer
    -> Historical Truth Layer
    -> Versioned Canonical Warehouse
    -> Disposable Replay Cache
    -> Separately approved consumers
```

The existing `alpha.market_truth.warehouse` package remains the storage and
ingestion foundation. ADP adds the permanent governance contracts around it:

- official dataset and schema registries;
- append-only raw artifact identities and checksum validation;
- field-level truth classification and transformation provenance;
- confidence assessment with explicit caps;
- source reconciliation that never overwrites conflicts;
- restart-safe, transport-independent acquisition checkpoints;
- independently queryable canonical datasets;
- effective-time plus knowledge-time travel;
- Warehouse v1/v2/v3 lineage and complete replay data bindings.

## Frozen Dataset Scope

ADP registers 20 official dataset definitions covering NSE and BSE daily
bhavcopies, NSE delivery data, corporate actions, security masters, ISIN and
symbol history, the NSE trading calendar, eight broad-market index histories,
all official sector-index history, and historical index membership.

All initial datasets are `UNACQUIRED`, have unknown coverage, and remain LOW
confidence until lawful acquisition, checksum verification, normalization,
reconciliation, and publication occur.

## Commands

```text
poetry run python -m alpha data platform
poetry run python -m alpha data registry
poetry run python -m alpha data datasets
poetry run python -m alpha data query
poetry run python -m alpha data provenance
poetry run python -m alpha data architecture
```

`data platform` exports the frozen 14-file architecture bundle to
`.alpha/data_platform/ALPHA_DATA_PLATFORM_v1.0`. Query commands do not acquire
data. Until HTA populates a dataset, they return `DATASET_NOT_ACQUIRED`.

## Next Milestone

Historical Truth Acquisition v1.0 should confirm source rights first, then add
one authorised connector at a time. Every acquired byte must enter the immutable
raw layer and pass checksum, schema, identity, corporate-action, reconciliation,
and point-in-time audits before Warehouse v2 can be frozen or published.

`PRODUCTION_INFLUENCE=false`
