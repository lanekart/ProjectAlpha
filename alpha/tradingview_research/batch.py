"""Batch run planning for per-symbol TradingView experiments."""

from __future__ import annotations

import hashlib

from alpha.tradingview_research.models import (
    BatchRun,
    LabConfiguration,
    ResearchPartition,
    UniverseMember,
)


class BatchRunPlanner:
    """Materialize one auditable chart run per symbol and partition."""

    def plan(
        self,
        configuration: LabConfiguration,
        members: tuple[UniverseMember, ...],
        partitions: tuple[ResearchPartition, ...],
    ) -> tuple[BatchRun, ...]:
        if not members:
            raise ValueError("batch plan requires at least one universe member")
        if not partitions:
            raise ValueError("batch plan requires at least one partition")
        symbols = tuple(item.symbol.strip().upper() for item in members)
        if len(symbols) != len(set(symbols)):
            raise ValueError("batch universe symbols must be unique")
        runs: list[BatchRun] = []
        for partition in sorted(partitions, key=lambda item: item.value):
            for member in sorted(members, key=lambda item: item.symbol):
                raw = "|".join(
                    (
                        configuration.configuration_id,
                        partition.value,
                        member.symbol.strip().upper(),
                        member.sector.strip().upper(),
                    )
                )
                runs.append(
                    BatchRun(
                        run_id="trl-run-"
                        + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16],
                        symbol=member.symbol.strip().upper(),
                        sector=member.sector.strip().upper(),
                        partition=partition,
                        configuration_id=configuration.configuration_id,
                    )
                )
        return tuple(runs)
