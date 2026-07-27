from __future__ import annotations

from pathlib import Path


MODULE = Path("alpha/decision_superiority/pre2016_calendar_recovery.py")
CLI = Path("alpha/application/decision_superiority_pre2016_calendar_sources_cli.py")
DOCS = Path("docs/DSI-010_PRE2011_OFFICIAL_CALENDAR_RECOVERY.md")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        if new in text:
            return text
        raise RuntimeError(f"PATCH_TARGET_MISSING:{label}")
    return text.replace(old, new, 1)


def patch_module() -> None:
    text = MODULE.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '"""Official-document recovery for DSI-010 pre-2011 session calendars."""',
        '"""Official-document recovery for DSI-010 2005-2015 session calendars."""',
        "module docstring",
    )
    text = replace_once(
        text,
        "PRE2011_CALENDAR_YEARS = tuple(range(2005, 2011))\n",
        "PRE2011_CALENDAR_YEARS = tuple(range(2005, 2011))\n"
        "PRE2016_CALENDAR_YEARS = tuple(range(2005, 2016))\n",
        "calendar year constants",
    )
    text = replace_once(
        text,
        "    if year not in PRE2011_CALENDAR_YEARS:\n",
        "    if year not in PRE2016_CALENDAR_YEARS:\n",
        "candidate year boundary",
    )
    text = replace_once(
        text,
        "            candidate.expected_circular_date is None\n"
        "            or candidate.expected_circular_date in normalized\n",
        "            candidate.expected_circular_date is None\n"
        "            or _normalize(candidate.expected_circular_date) in normalized\n",
        "circular date normalization",
    )
    MODULE.write_text(text, encoding="utf-8")


def patch_cli() -> None:
    text = CLI.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'DEFAULT_DSI010_PRE2011_RECOVERY_OUTPUT = Path(\n'
        '    "artifacts/dsi010_pre2011_official_sources"\n'
        ")\n",
        'DEFAULT_DSI010_PRE2011_RECOVERY_OUTPUT = Path(\n'
        '    "artifacts/dsi010_pre2011_official_sources"\n'
        ")\n"
        'DEFAULT_DSI010_PRE2016_RECOVERY_OUTPUT = Path(\n'
        '    "artifacts/dsi010_pre2016_official_sources"\n'
        ")\n",
        "generic recovery output",
    )
    text = replace_once(
        text,
        '    app.command("decision-superiority-pre2011-calendar-source-recovery")(\n'
        "        decision_superiority_pre2011_calendar_source_recovery\n"
        "    )\n",
        '    app.command("decision-superiority-pre2011-calendar-source-recovery")(\n'
        "        decision_superiority_pre2011_calendar_source_recovery\n"
        "    )\n"
        '    app.command("decision-superiority-pre2016-calendar-source-recovery")(\n'
        "        decision_superiority_pre2016_calendar_source_recovery\n"
        "    )\n",
        "generic recovery registration",
    )
    text = replace_once(
        text,
        '        typer.echo(f"PRE2011_CALENDAR_SOURCE_RECOVERY_FAILED: {exc}", err=True)\n',
        '        typer.echo(f"PRE2016_CALENDAR_SOURCE_RECOVERY_FAILED: {exc}", err=True)\n',
        "generic recovery error",
    )
    text = replace_once(
        text,
        '    typer.echo("===== DSI-010 PRE-2011 OFFICIAL CALENDAR RECOVERY =====")\n',
        '    typer.echo("===== DSI-010 2005-2015 OFFICIAL CALENDAR RECOVERY =====")\n',
        "generic recovery heading",
    )
    marker = "\n\ndef decision_superiority_pre2016_calendar_source_build(\n"
    function = '''\n\ndef decision_superiority_pre2016_calendar_source_recovery(\n    candidate_registry: Annotated[\n        Path,\n        typer.Option("--candidate-registry"),\n    ],\n    output: Annotated[\n        Path,\n        typer.Option("--output"),\n    ] = DEFAULT_DSI010_PRE2016_RECOVERY_OUTPUT,\n    timeout_seconds: Annotated[\n        float,\n        typer.Option("--timeout-seconds", min=1.0),\n    ] = 30.0,\n) -> None:\n    """Recover official NSE calendar circulars across the DSI-010 period."""\n\n    decision_superiority_pre2011_calendar_source_recovery(\n        candidate_registry=candidate_registry,\n        output=output,\n        timeout_seconds=timeout_seconds,\n    )\n'''
    if function.strip() not in text:
        if marker not in text:
            raise RuntimeError("PATCH_TARGET_MISSING:generic recovery function")
        text = text.replace(marker, function + marker, 1)
    CLI.write_text(text, encoding="utf-8")


def patch_docs() -> None:
    text = DOCS.read_text(encoding="utf-8")
    addition = '''\n## 2011-2015 extension\n\nThe recovery engine also accepts governed candidates through calendar year 2015.\nThe permanent generic command is:\n\n```text\ndecision-superiority-pre2016-calendar-source-recovery\n```\n\nThe legacy `pre2011` command remains registered as a compatibility alias. Calendar\nyear 2016 and later remain outside the signed DSI-010 external period.\n'''
    if "## 2011-2015 extension" not in text:
        text = text.rstrip() + "\n" + addition
    DOCS.write_text(text, encoding="utf-8")


def main() -> None:
    patch_module()
    patch_cli()
    patch_docs()


if __name__ == "__main__":
    main()
