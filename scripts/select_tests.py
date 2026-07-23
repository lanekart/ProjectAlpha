"""Select conservative pytest targets from changed Project Alpha files."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_SHARED_FILES = {
    "pyproject.toml",
    "poetry.lock",
    "alpha/__main__.py",
    "alpha/config.py",
}
_TEST_SELECTION_FILES = {
    "Makefile",
    "scripts/select_tests.py",
}
_SHARED_PREFIXES = (
    "alpha/application/",
    "alpha/data/",
    "alpha/historical_truth/adjustment_replay_admission_models.py",
)
_SUBSYSTEMS = {
    "historical_truth": "tests/historical_truth",
    "historical_replay": "tests/historical_replay",
    "market_intelligence": "tests/market_intelligence",
    "decision_intelligence": "tests/decision_intelligence",
    "portfolio": "tests/portfolio",
    "backtest": "tests/backtest",
    "research": "tests/research",
    "trading_signals": "tests/trading_signals",
}
_FALLBACK_BASES = (
    "origin/HEAD",
    "origin/main",
    "origin/master",
    "origin/feature/recovery-foundation-v1",
    "HEAD^",
)


def _git_lines(*args: str, check: bool = True) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", *args],
        check=check,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ()
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def _ref_exists(ref: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", ref],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def resolve_base(explicit_base: str | None) -> str | None:
    candidates = (
        explicit_base,
        os.environ.get("TEST_BASE"),
        *_FALLBACK_BASES,
    )
    for candidate in candidates:
        if candidate and _ref_exists(candidate):
            return candidate
    return None


def changed_files(base: str | None) -> tuple[str, ...]:
    tracked = (
        _git_lines("diff", "--name-only", f"{base}...HEAD", check=False)
        if base
        else ()
    )
    staged = _git_lines("diff", "--name-only", "--cached", check=False)
    unstaged = _git_lines("diff", "--name-only", check=False)
    return tuple(sorted(set((*tracked, *staged, *unstaged))))


def select_targets(paths: tuple[str, ...]) -> tuple[str, ...]:
    if not paths:
        return ("tests",)
    if any(path in _SHARED_FILES for path in paths):
        return ("tests",)
    if any(path.startswith(prefix) for path in paths for prefix in _SHARED_PREFIXES):
        return ("tests",)

    targets: set[str] = set()
    for path in paths:
        file_path = Path(path)
        if path in _TEST_SELECTION_FILES:
            targets.add("tests/test_test_selection.py")
            continue
        if path.startswith("tests/") and file_path.suffix == ".py":
            targets.add(path)
            continue
        if path.startswith("alpha/") and file_path.suffix == ".py":
            relative = file_path.relative_to("alpha")
            subsystem = relative.parts[0] if relative.parts else ""
            target = _SUBSYSTEMS.get(subsystem)
            if target:
                targets.add(target)
                candidate = Path("tests") / relative.parent / f"test_{relative.name}"
                if candidate.is_file():
                    targets.add(candidate.as_posix())
                continue
            return ("tests",)
        if path.startswith(("docs/", ".github/")) or file_path.suffix in {
            ".md",
            ".txt",
        }:
            continue
        return ("tests",)

    return tuple(sorted(targets)) or ("tests",)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base")
    parser.add_argument("--run", action="store_true")
    arguments = parser.parse_args()

    base = resolve_base(arguments.base)
    if base is None:
        print("No valid comparison base found; selecting the full test suite.")
    else:
        print(f"Comparison base: {base}")

    targets = select_targets(changed_files(base))
    print("Selected pytest targets:")
    for target in targets:
        print(f"  {target}")

    if not arguments.run:
        return 0
    return subprocess.call([sys.executable, "-m", "pytest", "-q", *targets])


if __name__ == "__main__":
    raise SystemExit(main())
