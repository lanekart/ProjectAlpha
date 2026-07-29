"""Immutable local experiment registry for conversational research sessions."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alpha.research.lab_models import (
    CompilationResult,
    ExperimentStatus,
    ResearchExperimentSpec,
)
from alpha.research.lab_serialization import specification_from_dict


@dataclass(frozen=True, slots=True)
class ExperimentRegistryEntry:
    experiment_id: str
    session_id: str
    parent_experiment_id: str | None
    status: ExperimentStatus
    specification_sha256: str | None
    user_command: str
    created_at: str


class ResearchLabStore:
    def __init__(self, root: Path = Path(".alpha/research")) -> None:
        self.root = root
        self.sessions_root = root / "sessions"
        self.runs_root = root / "runs"
        self.registry_path = root / "registry.jsonl"

    def allocate_experiment_id(self) -> str:
        largest = max(
            (
                int(path.name.removeprefix("ARL-"))
                for path in self.runs_root.glob("ARL-*")
                if path.name.removeprefix("ARL-").isdigit()
            ),
            default=0,
        )
        return f"ARL-{largest + 1:06d}"

    def allocate_session_id(self) -> str:
        largest = max(
            (
                int(path.stem.removeprefix("ARS-"))
                for path in self.sessions_root.glob("ARS-*.json")
                if path.stem.removeprefix("ARS-").isdigit()
            ),
            default=0,
        )
        return f"ARS-{largest + 1:06d}"

    def save_compilation(
        self,
        *,
        result: CompilationResult,
        user_command: str,
        session_id: str,
        experiment_id: str,
    ) -> Path:
        run_root = self.runs_root / experiment_id
        run_root.mkdir(parents=True, exist_ok=False)
        _write_json(
            run_root / "compiled_request.json",
            {
                "normalized_request": result.normalized_request,
                "intent": result.intent,
                "status": result.status.value,
                "issues": [asdict(item) for item in result.issues],
            },
        )
        _write_json(
            run_root / "spec_diff.json",
            {"changes": [asdict(item) for item in result.changes]},
        )
        if result.specification is not None:
            _write_json(run_root / "spec.json", result.specification.as_dict())
        entry = ExperimentRegistryEntry(
            experiment_id=experiment_id,
            session_id=session_id,
            parent_experiment_id=(
                None
                if result.specification is None
                else result.specification.parent_experiment_id
            ),
            status=result.status,
            specification_sha256=(
                None
                if result.specification is None
                else result.specification.specification_sha256
            ),
            user_command=user_command,
            created_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        )
        self.root.mkdir(parents=True, exist_ok=True)
        with self.registry_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    _registry_payload(entry),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
        self.sessions_root.mkdir(parents=True, exist_ok=True)
        session_path = self.sessions_root / f"{session_id}.json"
        session: dict[str, Any] = (
            json.loads(session_path.read_text())
            if session_path.is_file()
            else {"session_id": session_id, "experiments": []}
        )
        experiments = list(session.get("experiments", []))
        experiments.append(experiment_id)
        session["experiments"] = experiments
        session["latest_experiment"] = experiment_id
        _write_json(session_path, session)
        return run_root

    def load_specification(self, experiment_id: str) -> ResearchExperimentSpec:
        path = self.runs_root / experiment_id / "spec.json"
        if not path.is_file():
            raise FileNotFoundError(
                f"experiment specification not found: {experiment_id}"
            )
        payload = json.loads(path.read_text())
        return specification_from_dict(payload)

    def entries(self) -> tuple[dict[str, Any], ...]:
        if not self.registry_path.is_file():
            return ()
        return tuple(
            json.loads(line)
            for line in self.registry_path.read_text().splitlines()
            if line.strip()
        )


def _registry_payload(entry: ExperimentRegistryEntry) -> dict[str, Any]:
    payload = asdict(entry)
    payload["status"] = entry.status.value
    return payload


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


__all__ = ["ExperimentRegistryEntry", "ResearchLabStore"]
