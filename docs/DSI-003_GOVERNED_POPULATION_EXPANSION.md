# DSI-003 Governed Population Expansion

## Purpose

DSI-003 certifies the largest defensible independent complete-stack candidate
population available from the accepted Project Alpha evidence chain. It does
not relax a gate, change a threshold, create a trade, or claim that a gate has
economic value.

`PRODUCTION_INFLUENCE=false`.

## Independent Unit

The primary empirical unit is `economic_candidate_id`. Its identity binds:

- security identity;
- recommendation date;
- canonical recommendation identity;
- complete-stack policy version;
- point-in-time captured-input identity.

RAW and ADJUSTED records remain separate analytical arms. Paired arms map to
one economic candidate and never increase the independent sample size.

## Signed Source Chain

The command validates and binds:

- HTR-010B5 complete-stack gate evidence;
- HTR-010B7 setup-matched outcomes;
- HTR-010B10 adaptive-shadow evidence, including a governed empty population;
- DSI-001 candidate and outcome evidence;
- DSI-002A capture acceptance;
- DSI-002D1 and renewed B2/C2/D2 complete-stack evidence;
- the final DSI-002 certificate and all internal slice certificates.

Certificates, support artifacts, report digests, evaluator lineage, source
ancestry, and caller-selected artifact paths are checked fail closed. Portable
outputs retain source names, filenames, and hashes, never machine-local
absolute paths.

## Population Reconstruction

HTR-010B5 is the authoritative broad recorded complete-stack source. Its
candidate and gate ledgers were produced by the canonical evaluators with
unchanged policy. Rejected candidates remain valid population members when the
complete institutional stack produced a terminal state. Downstream stress and
trade-plan stages after a base rejection are recorded as semantically not
applicable, not silently dropped.

The separate signed DSI-002 BEL candidate is added once. B7 and DSI-001 rows
attach to matching candidates but do not create new candidates.

## Outcomes

Only signed HTR-010B7 outcome rows are admitted. DSI-003 classifies each
economic candidate as:

- completed comparable outcome;
- not entered;
- pending at the end of data;
- missing outcome;
- or an explicit non-comparable/error state.

No outcome is generated for a rejected candidate, and no production ledger is
backfilled.

## DSI-002 Transferability

DSI-002 exact condition-pass replay requires the frozen recommendation object
used to construct the institutional candidate. That complete object exists for
the signed BEL capture. B5 and DSI-001 retain complete recorded stage and gate
evidence, but not rehydratable recommendation objects for every historical
candidate.

Therefore DSI-003:

- runs no fabricated evaluator replay;
- reports BEL as exact signed DSI-002 transferability evidence;
- reports the broad historical population as recorded-stage attribution only;
- returns `READY_WITH_PARTIAL_DSI002_TRANSFERABILITY`.

This distinction is permanent unless a future governed capture provides the
missing point-in-time recommendation objects.

## Readiness

The slices are:

- A: source inventory;
- B: complete-stack reconstruction;
- C: population funnel and loss attribution;
- D: independence and deduplication;
- E: coverage and external validity;
- F: outcome readiness;
- G: DSI-002 transferability;
- H: effective research sufficiency;
- I: final certification.

A broad candidate count does not establish market-wide external validity.
Missing sector and regime classifications remain `UNKNOWN`, and concentration
is measured using economic candidates rather than arm, gate, or remediation
rows.

## CLI

Run:

```bash
poetry run python -m alpha benchmark \
  decision-superiority-population-expansion \
  --b5-certificate <PATH> \
  --b7-certificate <PATH> \
  --b10-certificate <PATH> \
  --dsi001-certificate <PATH> \
  --dsi002a-certificate <PATH> \
  --dsi002d1-certificate <PATH> \
  --dsi002b2-certificate <PATH> \
  --dsi002c2-certificate <PATH> \
  --dsi002d2-certificate <PATH> \
  --dsi002-certificate <PATH> \
  --output <PATH>
```

Verify:

```bash
poetry run python -m alpha benchmark \
  decision-superiority-population-expansion-verify \
  --certificate <OUTPUT>/dsi003_population_expansion_certificate.json \
  --require-ready
```

## Artifacts

The run writes one certificate, nineteen CSV ledgers, and one Markdown
executive report. All twenty support artifacts are hash-bound by the
certificate. Serialization and ordering are deterministic; a byte-identical
rerun produces byte-identical artifacts when the source commit and inputs are
unchanged.

## Governance

All policy, production, execution, recommendation, portfolio, learning,
synthetic-data, and causal-claim flags remain false. Structural probes exercise
both positive and negative code paths but are permanently excluded from
empirical counts.
