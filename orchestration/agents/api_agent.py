"""API agent — exercises HTTP endpoints via TestClient."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestration.schemas import AgentResult, BaseAgent, WorkInstruction


class APIAgent(BaseAgent):
    role = "api"

    def execute(self, instruction: WorkInstruction, context: dict[str, Any]) -> AgentResult:
        from fastapi.testclient import TestClient

        from backend.app.main import app

        Path("data/runtime").mkdir(parents=True, exist_ok=True)
        try:
            client = TestClient(app)
            checks = {}
            errors = []

            r = client.get("/api/v1/health")
            checks["health"] = r.status_code == 200
            if r.status_code != 200:
                errors.append("health failed")

            r = client.post("/api/v1/admin/seed")
            checks["seed"] = r.status_code == 200
            if r.status_code != 200:
                errors.append(f"seed failed: {r.text}")

            r = client.post(
                "/api/v1/classify",
                json={
                    "description": "Hydrating facial cream lotion for skin care",
                    "ground_truth_hs": "3304.99.1000",
                    "external_id": "API-TEST-001",
                },
            )
            checks["classify"] = r.status_code == 200 and "final_hs" in r.json()
            if r.status_code != 200:
                errors.append(f"classify failed: {r.text}")

            r = client.get("/api/v1/metrics")
            checks["metrics"] = r.status_code == 200

            r = client.get("/api/v1/classifications?limit=5")
            checks["list"] = r.status_code == 200

            artifact = {"checks": checks, "sample_classify": checks.get("classify") and r.status_code}
            c = client.post(
                "/api/v1/classify",
                json={"description": "cotton T-shirt apparel", "external_id": "API-TEST-002"},
            )
            artifact["sample"] = c.json() if c.status_code == 200 else {}

            Path("orchestration/artifacts/api.json").write_text(
                json.dumps(artifact, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
            )
            ok = all(checks.values())
            return AgentResult(
                agent_role=self.role,
                order_id=instruction.order_id,
                success=ok,
                artifacts=artifact,
                errors=errors,
                notes="API smoke tests via TestClient",
            )
        except Exception as e:  # noqa: BLE001
            return AgentResult(
                agent_role=self.role,
                order_id=instruction.order_id,
                success=False,
                errors=[str(e)],
                notes="API agent exception",
            )
