"""Backend development agent — verifies backend package integrity."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestration.schemas import AgentResult, BaseAgent, WorkInstruction


REQUIRED_MODULES = [
    "backend.app.main",
    "backend.app.api.routes",
    "backend.app.services.classification.pipeline",
    "backend.app.services.knowledge.graph",
    "backend.app.db.models",
]


class BackendDevAgent(BaseAgent):
    role = "backend_dev"

    def execute(self, instruction: WorkInstruction, context: dict[str, Any]) -> AgentResult:
        errors = []
        loaded = []
        for mod in REQUIRED_MODULES:
            try:
                importlib.import_module(mod)
                loaded.append(mod)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{mod}: {e}")
        req = Path("backend/requirements.txt")
        dockerfile = Path("backend/Dockerfile")
        ok = not errors and req.exists() and dockerfile.exists()
        artifact = {
            "loaded_modules": loaded,
            "requirements_present": req.exists(),
            "dockerfile_present": dockerfile.exists(),
            "errors": errors,
        }
        Path("orchestration/artifacts/backend_dev.json").write_text(
            json.dumps(artifact, indent=2), encoding="utf-8"
        )
        return AgentResult(
            agent_role=self.role,
            order_id=instruction.order_id,
            success=ok,
            artifacts=artifact,
            errors=errors,
            notes="Backend module and packaging verification",
        )
