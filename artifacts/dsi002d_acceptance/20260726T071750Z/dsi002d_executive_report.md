# DSI-002D Governed Stage Attribution

Readiness: **BLOCKED_BY_INCOMPLETE_STAGE_INVENTORY**
Source commit: `533797c1ac270be85ec4fa59ceb58824c574d563`
Candidates: 1
Stage inventory entries: 11
Canonical stage events: 11

## Finding

The signed baseline invokes recommendation and portfolio engines, but does not invoke the separate InstitutionalDecisionEngine base, stress, or optimization stages. Those stages are recorded as MISSING_EVALUATOR_WIRING and no result is inferred.

## Candidate Attribution

Candidate: `RAW|2026-07-26|BEL|6b6510eca6894beee800c225fe780a37521498115880cbf2cc0db50b3d8adeda`
Recorded decision: WATCHLIST
First observed blocker: recommendation.trade_setup
All observed blockers: recommendation.trade_setup|recommendation.score_and_rules|recommendation.trade_plan|portfolio.allocation
Decision parity: True
Attribution complete: False

## Governance

This bundle is observational only. It makes no causal, economic, counterfactual, approval, execution, or production claim.

PRODUCTION_INFLUENCE=false
