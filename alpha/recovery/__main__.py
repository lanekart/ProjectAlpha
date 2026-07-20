"""Standalone CLI for canonical replay integrity verification."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import typer

from .canonical_replay import CanonicalReplayBuilder
from .corporate_actions import CorporateActionTimeline
from .replay_snapshot import CanonicalReplaySnapshotRepository

app = typer.Typer(no_args_is_help=True)


@app.command(name="verify-snapshot")
def verify_snapshot(
    root: Path = typer.Option(
        ...,
        "--root",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        help="Canonical replay snapshot repository root.",
    ),
    as_of: str = typer.Option(
        ...,
        "--as-of",
        help="Snapshot date in YYYY-MM-DD format.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        help="Optional output directory for verification artifacts.",
    ),
) -> None:
    """Verify one immutable canonical replay snapshot and its manifest."""

    replay_date = _parse_date(as_of)
    snapshot = CanonicalReplaySnapshotRepository(root).read(replay_date)
    audit = CanonicalReplayBuilder(CorporateActionTimeline(())).audit_bars(
        snapshot.bars
    )
    payload = {
        "as_of": snapshot.as_of.isoformat(),
        "bar_count": len(snapshot.bars),
        "bars_ready": audit.bars_ready,
        "bars_quarantined": audit.bars_quarantined,
        "recovery_version": snapshot.recovery_version,
        "snapshot_sha256": snapshot.snapshot_sha256,
        "integrity_verified": audit.snapshot_sha256 == snapshot.snapshot_sha256,
        "governed_replay_ready": audit.passed,
    }
    if output is not None:
        _write_verification_artifacts(payload, output)
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


@app.command(name="list-snapshots")
def list_snapshots(
    root: Path = typer.Option(
        ...,
        "--root",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        help="Canonical replay snapshot repository root.",
    ),
) -> None:
    """List available canonical replay snapshot dates."""

    repository = CanonicalReplaySnapshotRepository(root)
    for snapshot_date in repository.available_dates():
        typer.echo(snapshot_date.isoformat())


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise typer.BadParameter("--as-of must use YYYY-MM-DD") from error


def _write_verification_artifacts(
    payload: dict[str, object],
    output: Path,
) -> tuple[Path, Path]:
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "snapshot_verification.json"
    report_path = output / "snapshot_verification.md"
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(
        "# Canonical Replay Snapshot Verification\n\n"
        f"- As Of: `{payload['as_of']}`\n"
        f"- Bars: `{payload['bar_count']}`\n"
        f"- Bars Ready: `{payload['bars_ready']}`\n"
        f"- Bars Quarantined: `{payload['bars_quarantined']}`\n"
        f"- Snapshot SHA-256: `{payload['snapshot_sha256']}`\n"
        f"- Integrity Verified: `{payload['integrity_verified']}`\n"
        f"- Governed Replay Ready: `{payload['governed_replay_ready']}`\n",
        encoding="utf-8",
    )
    return json_path, report_path


if __name__ == "__main__":
    app()
