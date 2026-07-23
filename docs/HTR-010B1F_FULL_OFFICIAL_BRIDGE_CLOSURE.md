# HTR-010B1F Full Official Bridge Closure

## Purpose

HTR-010B1F closes governed cross-ISIN and cross-series identity bridge cases using official evidence only. It remains diagnostic and cannot influence production decisions, benchmark replay, factor formulas, or admission policy.

## Evidence roles

Each dossier is evaluated independently across three roles:

1. `PRE_IDENTITY`: an official historical filing containing the prior ISIN.
2. `CORPORATE_ACTION`: an official NSE corporate-actions API row matching the exact symbol, governed effective date, and a supported action purpose.
3. `POST_IDENTITY`: the official NSE equity security master containing the current ISIN and series.

Identity continuity is certified only when all three roles are proved. Price-series continuity and tradability continuity remain separate and are never inferred from identity continuity.

## Corporate-action matching

The downloader resolves governed corporate-action source references to the official NSE endpoint:

`/api/corporates-corporateActions`

Requests use:

- `index=equities`
- the exact governed symbol
- a bounded date window around the governed effective date
- an NSE cookie-bearing session and browser-compatible request headers

The semantic matcher is schema-tolerant but evidence-strict. It recursively identifies action rows and requires:

- exact symbol match;
- exact effective date match against ex-date, record date, book-closure start, or explicit effective-date fields;
- supported split, subdivision, consolidation, bonus, face-value, or series-change purpose.

Multiple matching rows fail closed as `ACTION_ROWS_CONFLICTING_OR_DUPLICATE`.

## Governed action states

- `ACTION_ROW_VERIFIED`
- `ACTION_API_RETURNED_NO_ROWS`
- `ACTION_PAYLOAD_NOT_VALID_JSON`
- `ACTION_SYMBOL_NOT_FOUND`
- `ACTION_EFFECTIVE_DATE_NOT_FOUND`
- `ACTION_PURPOSE_NOT_SUPPORTED`
- `ACTION_ROWS_CONFLICTING_OR_DUPLICATE`
- `ACTION_DOCUMENT_NOT_DOWNLOADED`

Each semantic package records row counts, matching counts, detected schema keys, matched official rows, payload SHA-256, role download states, and unresolved reasons.

## MCX handling

MCX remains explicitly unresolved unless an admissible official pre-event source proves `INE745G01035`. Corporate-action and post-identity evidence cannot substitute for missing pre-identity proof.

## Outputs

The semantic-review stage includes:

- `htr010b1f_evidence_package_review.json`
- `htr010b1f_semantically_reviewed_discoveries.json`
- `htr010b1f_semantic_package_results.json`
- `htr010b1f_action_evidence_diagnostics.json`

The report includes pre-identity, corporate-action, and post-identity proof counts plus a distribution of corporate-action states.

## Acceptance

The milestone is technically acceptable when:

- all focused and full tests pass;
- Ruff and Ruff format pass;
- MyPy passes;
- implementation defects are zero;
- official downloads have no unexplained failures;
- all 24 cases are explicitly classified;
- every unresolved case contains a concrete evidence reason;
- benchmark replay count remains zero;
- `PRODUCTION_INFLUENCE=false`.

A genuine official-evidence gap is acceptable. A silent parser, schema, download, or mapping failure is not.
