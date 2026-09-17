"""Frontend development agent — ensures dashboard assets exist."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestration.schemas import AgentResult, BaseAgent, WorkInstruction


class FrontendDevAgent(BaseAgent):
    role = "frontend_dev"

    def execute(self, instruction: WorkInstruction, context: dict[str, Any]) -> AgentResult:
        required = [
            Path("frontend/index.html"),
            Path("frontend/src/main.js"),
            Path("frontend/src/styles/app.css"),
            Path("frontend/package.json"),
            Path("frontend/Dockerfile"),
        ]
        missing = [str(p) for p in required if not p.exists()]
        artifact = {"checked": [str(p) for p in required], "missing": missing}
        Path("orchestration/artifacts/frontend_dev.json").write_text(
            json.dumps(artifact, indent=2), encoding="utf-8"
        )
        return AgentResult(
            agent_role=self.role,
            order_id=instruction.order_id,
            success=len(missing) == 0,
            artifacts=artifact,
            errors=[f"Missing: {m}" for m in missing],
            notes="Frontend scaffold verification",
        )
