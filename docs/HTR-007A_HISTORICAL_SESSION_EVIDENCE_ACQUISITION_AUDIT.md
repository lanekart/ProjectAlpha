# HTR-007A Historical Official Session Evidence Acquisition Audit

HTR-007A adds a fail-closed repair and diagnostic layer around the existing HTR-007 annual NSE Capital Market session-evidence engine. The original engine remains the first acquisition path and retains its immutable-source and checkpoint behavior.

## Why this milestone exists

The first real HTR-007 run admitted official evidence for 2025 but failed for 2016–2024, leaving 127 unresolved weekdays. HTR-007A does not infer that those dates were holidays. Instead, it records why each source attempt failed and probes additional governed NSE discovery surfaces for admissible historical Capital Market documents.

## Admission boundary

An alternate candidate is admitted only when:

1. The final URL is on an approved NSE-controlled domain.
2. The response succeeds and is non-empty.
3. The parser is selected from inspected bytes and response metadata rather than the filename alone.
4. The document resolves to supported PDF, HTML, or plain-text evidence.
5. The requested calendar year is verified by the parsed records.
6. Capital Market, Equities, or governed CMTR lineage is verified.
7. Holiday parsing passes the existing HTR-007 sanity and ambiguity checks.
8. Raw discovery bytes, raw official-source bytes, and normalized derivatives are stored immutably with SHA-256 checksums.

Discovery alone never upgrades certification. Unsupported or ambiguous evidence remains rejected and visible in the audit.

## Discovery sources

After the existing annual-page path fails, the repair layer probes official NSE holiday and circular directory surfaces and inspects official attachment links in Capital Market holiday context. Derivative-segment documents and non-NSE hosts are rejected.

The implementation intentionally does not use a third-party holiday calendar and does not hard-code missing dates.

## Structured diagnostics

The acquisition audit distinguishes, where observable:

- official document not found,
- access denied,
- rate limited,
- PDF resolving to HTML,
- invalid content,
- empty response,
- PDF or HTML parse failure,
- no or partial session records,
- source-year mismatch,
- source-segment mismatch,
- checksum mismatch,
- network error,
- unknown legacy-path failure.

Each attempt retains year, source family, requested and final URLs, retrieval timestamp, HTTP status, content type, byte size, redirects, inferred extension, SHA-256, parser, parse/admission status, counts, and failure detail.

## Commands

Acquire and audit annual evidence:

```bash
poetry run python -m alpha historical-session-evidence acquire \
  --start-year 2016 \
  --end-year 2025 \
  --output artifacts/htr007_historical_session_evidence
```

Inspect an existing audit:

```bash
poetry run python -m alpha historical-session-evidence audit \
  --evidence-dir artifacts/htr007_historical_session_evidence
```

Acquire, audit, and reconcile the complete window:

```bash
poetry run python -m alpha historical-session-evidence run \
  --start-year 2016 \
  --end-year 2025 \
  --start 2016-01-01 \
  --end 2026-07-20 \
  --root alpha_data \
  --output artifacts/htr007_historical_session_evidence
```

## Artifacts

The repair layer adds:

- `htr007a_acquisition_audit.json`
- `htr007a_acquisition_audit.csv`
- `htr007a_acquisition_audit.md`
- `htr007a_rejected_evidence.json`
- `htr007a_rejected_evidence.csv`
- `htr007a_unresolved_sessions.json`
- `htr007a_unresolved_sessions.csv`

The existing HTR-007 evidence and session-calendar artifacts remain unchanged in name and format.

## Certification labels

The CLI reports exactly one of:

- `complete_official_evidence`
- `incomplete_official_evidence`
- `conflicting_official_evidence`

Any failed acquisition year, unresolved weekday, missing or unconfirmed special session, or conflict keeps the result fail-closed.

## Progress rendering

Interactive terminals retain in-place progress. Captured logs receive newline-delimited records, preventing overwritten fragments such as `2025ing 2016` and `completedow`.

## Validation boundary

Deterministic tests use local fixtures and do not require network access. A real local run against NSE and the populated Historical Truth Warehouse remains necessary to determine whether 2016–2024 can now be admitted or which official-source gaps remain irreducible.
