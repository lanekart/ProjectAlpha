from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path

from alpha.benchmark_replay.models import BenchmarkPolicy, VersionFreeze
from alpha.canonical_universe_audit.models import CANONICAL_ENGINE_VERSION

_FEATURE_VERSION = "point-in-time-feature-stack-v1"
_CANDIDATE_VERSION = CANONICAL_ENGINE_VERSION
_SETUP_VERSION = "SDE_v1.0"
_ATTRIBUTION_VERSION = "POINT_IN_TIME_FEATURE_ATTRIBUTION_v1.0"
_APPROVAL_POLICY_VERSION = "institutional-approval-policy-v1"
_TRADE_PLAN_ENGINE_VERSION = "trade-plan-engine-v1"
_DECISION_VERSION = "institutional-decision-engine-v1"


def freeze_versions(*, project_root: Path, warehouse: Path) -> VersionFreeze:
    return VersionFreeze(
        warehouse_version="LEGACY_DATASET/PROVISIONAL",
        warehouse_hash=_file_hash(warehouse),
        feature_version=_FEATURE_VERSION,
        feature_hash=_tree_hash(
            project_root,
            ("alpha/analysis", "alpha/recommendation_intelligence"),
        ),
        candidate_generation_version=_CANDIDATE_VERSION,
        candidate_generation_hash=_tree_hash(
            project_root,
            (
                "alpha/analysis/signals",
                "alpha/application/intelligence_inputs.py",
                "alpha/canonical_universe_audit/canonical_runner.py",
            ),
        ),
        setup_discovery_version=_SETUP_VERSION,
        setup_discovery_hash=_tree_hash(
            project_root,
            ("alpha/setup_discovery", "alpha/recommendation_intelligence/engines.py"),
        ),
        feature_attribution_version=_ATTRIBUTION_VERSION,
        feature_attribution_hash=_tree_hash(
            project_root,
            ("alpha/feature_attribution_research",),
        ),
        approval_policy_version=_APPROVAL_POLICY_VERSION,
        approval_policy_hash=_tree_hash(
            project_root,
            ("alpha/decision_intelligence/engine.py",),
        ),
        trade_plan_policy_version=_TRADE_PLAN_ENGINE_VERSION,
        trade_plan_policy_hash=_tree_hash(
            project_root,
            (
                "alpha/decision_intelligence/tradeplan.py",
                "alpha/recommendation_intelligence/engines.py",
            ),
        ),
        decision_engine_version=_DECISION_VERSION,
        decision_engine_hash=_tree_hash(
            project_root,
            ("alpha/decision_intelligence",),
        ),
        source_commit=_git(project_root, "rev-parse", "HEAD") or "UNKNOWN",
        source_tree_hash=_source_tree_hash(project_root),
        source_tree_state=(
            "CLEAN"
            if not (_git(project_root, "status", "--porcelain") or "").strip()
            else "DIRTY"
        ),
        python_version=platform.python_version(),
        dependency_lock_hash=_file_hash(project_root / "poetry.lock"),
    )


def replay_input_hash(
    *,
    versions: VersionFreeze,
    policy: BenchmarkPolicy,
    start: str,
    end: str,
    evidence_hashes: dict[str, str] | None = None,
) -> str:
    payload = {
        "versions": asdict(versions),
        "policy": {key: str(value) for key, value in asdict(policy).items()},
        "start": start,
        "end": end,
        "evidence_hashes": dict(sorted((evidence_hashes or {}).items())),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def file_hash(path: Path) -> str:
    return _file_hash(path)


def _source_tree_hash(project_root: Path) -> str:
    return _tree_hash(
        project_root,
        ("alpha", "pyproject.toml", "poetry.lock"),
    )


def _tree_hash(project_root: Path, entries: Iterable[str]) -> str:
    paths: list[Path] = []
    for entry in entries:
        path = project_root / entry
        if path.is_dir():
            paths.extend(
                item
                for item in path.rglob("*")
                if item.is_file() and item.suffix in {".py", ".json", ".toml"}
            )
        elif path.is_file():
            paths.append(path)
    digest = hashlib.sha256()
    for path in sorted(set(paths)):
        digest.update(str(path.relative_to(project_root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _file_hash(path: Path) -> str:
    if not path.exists():
        return "UNAVAILABLE"
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(project_root: Path, *arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ("git", *arguments),
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


__all__ = ["file_hash", "freeze_versions", "replay_input_hash"]
