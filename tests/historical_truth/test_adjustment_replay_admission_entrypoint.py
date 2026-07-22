from __future__ import annotations

import sys
from collections.abc import Callable

import typer

from alpha.__main__ import main
from alpha.historical_truth.adjustment_replay_admission_cli import (
    adjustment_replay_admission_certify,
)


def test_module_cli_routes_htr010b1_command(monkeypatch: object) -> None:
    calls: list[Callable[..., object]] = []

    def fake_run(command: Callable[..., object]) -> None:
        calls.append(command)

    monkeypatch.setattr(typer, "run", fake_run)  # type: ignore[attr-defined]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        sys,
        "argv",
        [
            "alpha",
            "historical-truth",
            "adjustment-replay-admission-certify",
            "--verify-only",
        ],
    )

    main()

    assert calls == [adjustment_replay_admission_certify]
    assert sys.argv == ["alpha", "--verify-only"]
