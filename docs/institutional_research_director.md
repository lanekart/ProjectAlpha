# Institutional Research Director (IRD)

## Purpose

The Institutional Research Director is Project Alpha's diagnostic research
governance layer. It reads existing replay evidence, preserves metric lineage,
ranks proven engineering bottlenecks, records controlled experiments, and
generates an evidence-backed roadmap.

IRD is diagnostic only. Its models reject `production_influence=True`, and the
subsystem has no dependency from recommendation, approval, allocation, trading,
learning, replay execution, or live market-data paths.

## Architecture

The orchestration flow is:

```text
existing diagnostic reports
        |
        v
DiagnosticRegistry -> BottleneckEngine -> RoadmapEngine
        |                    |
        |                    v
        +------------> BriefingEngine
        |
ResearchExperimentRegistry -> EngineeringRoiEngine
```

The package lives in `alpha/research/`:

- `models.py`: immutable IRD value objects and policy invariant.
- `diagnostic_registry.py`: plugin interface and adapters for existing reports.
- `research_registry.py`: deterministic JSON ledger and JSON/CSV export.
- `bottleneck_engine.py`: evidence-only bottleneck classification and ranking.
- `engineering_roi.py`: measured experiment deltas and separate estimates.
- `roadmap_engine.py`: deterministic P0/P1/P2/Deferred generation.
- `briefing_engine.py`: executive research briefing synthesis.
- `institutional_research_director.py`: read-only orchestration facade.
- `rendering.py`: deterministic CLI rendering.

## Diagnostic Registration

Built-in adapters automatically register these existing diagnostics without
modifying their source modules:

- institutional approval diagnostics;
- entry timing validation;
- directional signal quality;
- market regime audit;
- breakout replay readiness;
- NSE historical identity coverage;
- corporate-action coverage;
- point-in-time analytical coverage.

A future diagnostic implements `ResearchDiagnosticPlugin` with four metadata
attributes and one method:

```python
class MyDiagnostic:
    diagnostic_id = "my-diagnostic"
    title = "My diagnostic"
    subsystem = ResearchSubsystem.RESEARCH_GOVERNANCE
    source_module = "alpha.example"

    def collect(self) -> DiagnosticEvidence:
        ...
```

It may be exposed as `RESEARCH_DIAGNOSTIC_PLUGIN`, returned from a module-level
`research_diagnostic_plugins()` function, or published through the
`project_alpha.research_diagnostics` Python entry-point group. The IRD core does
not need to change for any of these paths.

Collection failures become typed `UNKNOWN` evidence. They never produce an
inferred metric.

## Metric Lineage

Every `ResearchMetric` retains:

- source;
- definition;
- population;
- version.

Two metrics are comparable only when metric ID, unit, source, definition,
population, and version match exactly. Strict institutional approval and raw
approval are consequently retained as separate concepts and are never used in
the same baseline/treatment delta.

## Experiment Registry

`ResearchExperimentRegistry.record()` persists immutable
`RegisteredResearchExperiment` values. A record contains the experiment ID,
title, subsystem, date, purpose, evidence sources, baseline metrics, treatment
metrics, measured metric IDs, statistical confidence, decision, status, and
production influence.

Recording the same identical experiment is idempotent. Reusing an experiment ID
for different evidence is rejected. Writes are deterministic, sorted, and
atomically replaced. The default path is:

```text
.alpha/research/experiment_registry.json
```

Use `ALPHA_RESEARCH_REGISTRY_PATH` to select another registry.

The registry can be exported through the API or CLI:

```text
poetry run python -m alpha research registry --format json
poetry run python -m alpha research registry --format csv
poetry run python -m alpha research registry --format json --output report.json
```

## Priority Rules

Roadmap priority is derived from diagnostic facts. It is not an estimate of
profit, expected gain, or implementation value.

- `P0`: proven gap, high evidence quality, high confidence, and maturity is
  `BLOCKED` or `NASCENT`.
- `P1`: proven gap, at least medium evidence quality and confidence, and maturity
  is `BLOCKED`, `NASCENT`, or `PARTIAL`.
- `P2`: any other proven gap.
- `Deferred`: unknown evidence or no material gap.

Ordering inside a band is deterministic: confidence, evidence quality, maturity,
then diagnostic ID. Every roadmap item carries its supporting diagnostic IDs.

Engineering complexity is also mechanical: no dependency is low; two or more
internal dependencies are medium; an authorized, licensed, external, or
corporate-action dependency is high.

## Engineering ROI

Measured ROI contains only numeric baseline/treatment deltas from completed
experiments with identical metric lineage. Estimated ROI is a separate model and
is `UNKNOWN` until evidence supports an estimate. The two collections are never
added, averaged, ranked together, or presented as interchangeable.

The highest ROI completed project is unavailable unless completed experiments
record a comparable `engineering.roi` metric. IRD does not use an arbitrary
proxy when that metric is absent.

## Commands

```text
poetry run python -m alpha research bottlenecks
poetry run python -m alpha research roadmap
poetry run python -m alpha research roi
poetry run python -m alpha research registry
poetry run python -m alpha research briefing
```

## Constraints

- `PRODUCTION_INFLUENCE=false` for every IRD artifact.
- Phase 1 reads existing replay evidence only.
- No recommendation, approval, replay, learning, allocation, trading, live-data,
  or production-policy behavior is changed.
- No expected gain, win rate, precision, confidence, or ROI is fabricated.
- Missing or failed evidence is reported as `UNKNOWN`.
- Definition-incompatible metrics are never compared.
- The roadmap is a research queue, not authorization to change production.
