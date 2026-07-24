from __future__ import annotations

import base64
import zlib
from pathlib import Path

ROOT = Path.cwd()
PAYLOADS = {
    ROOT / "alpha/benchmark_replay/governed_trade_formation.py": (
        ROOT / "scripts/.htr010b4_core.b64"
    ),
    ROOT / "alpha/application/governed_trade_formation_cli.py": (
        ROOT / "scripts/.htr010b4_cli.b64"
    ),
    ROOT / "tests/benchmark_replay/test_governed_trade_formation.py": (
        ROOT / "scripts/.htr010b4_test.b64"
    ),
}


def decode_payloads() -> None:
    for destination, payload_path in PAYLOADS.items():
        encoded = payload_path.read_text(encoding="utf-8").strip()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(zlib.decompress(base64.b64decode(encoded)))
        print(f"wrote {destination}")


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        print(f"already applied: {label}")
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one insertion point, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"patched: {label}")


def patch_benchmark_cli() -> None:
    path = ROOT / "alpha/application/benchmark_cli.py"
    replace_once(
        path,
        """from alpha.application.governed_adjusted_stability_cli import (
    register_governed_adjusted_stability_command,
)
""",
        """from alpha.application.governed_adjusted_stability_cli import (
    register_governed_adjusted_stability_command,
)
from alpha.application.governed_trade_formation_cli import (
    register_governed_trade_formation_command,
)
""",
        "B4 CLI import",
    )
    replace_once(
        path,
        """register_governed_adjusted_benchmark_command(benchmark_app)
register_governed_adjusted_stability_command(benchmark_app)
""",
        """register_governed_adjusted_benchmark_command(benchmark_app)
register_governed_adjusted_stability_command(benchmark_app)
register_governed_trade_formation_command(benchmark_app)
""",
        "B4 CLI registration",
    )


def patch_package_exports() -> None:
    path = ROOT / "alpha/benchmark_replay/__init__.py"
    replace_once(
        path,
        """from alpha.benchmark_replay.models import (
""",
        """from alpha.benchmark_replay.governed_trade_formation import (
    B4_BLOCKED_DEFECT,
    B4_BLOCKED_DIVERGENCE,
    B4_BLOCKED_INSUFFICIENT,
    B4_BLOCKED_ZERO,
    B4_READY,
    HTR010B4_CONTRACT_VERSION,
    GovernedTradeFormationEngine,
    GovernedTradeFormationResult,
    export_governed_trade_formation,
    validate_governed_trade_formation_certificate,
)
from alpha.benchmark_replay.models import (
""",
        "B4 package imports",
    )
    replace_once(
        path,
        """    "B3_READY",
""",
        """    "B3_READY",
    "B4_BLOCKED_DEFECT",
    "B4_BLOCKED_DIVERGENCE",
    "B4_BLOCKED_INSUFFICIENT",
    "B4_BLOCKED_ZERO",
    "B4_READY",
""",
        "B4 package constants",
    )
    replace_once(
        path,
        """    "HTR010B3_CONTRACT_VERSION",
""",
        """    "HTR010B3_CONTRACT_VERSION",
    "HTR010B4_CONTRACT_VERSION",
""",
        "B4 package contract",
    )
    replace_once(
        path,
        """    "GovernedBenchmarkStorePair",
""",
        """    "GovernedBenchmarkStorePair",
    "GovernedTradeFormationEngine",
    "GovernedTradeFormationResult",
""",
        "B4 package types",
    )
    replace_once(
        path,
        """    "export_governed_adjusted_stability",
""",
        """    "export_governed_adjusted_stability",
    "export_governed_trade_formation",
""",
        "B4 package exporter",
    )
    replace_once(
        path,
        """    "validate_governed_adjusted_research_activation",
""",
        """    "validate_governed_adjusted_research_activation",
    "validate_governed_trade_formation_certificate",
""",
        "B4 package validator",
    )


decode_payloads()
patch_benchmark_cli()
patch_package_exports()
