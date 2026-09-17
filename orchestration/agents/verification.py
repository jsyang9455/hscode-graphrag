"""Verification agent — validates agent outputs against acceptance criteria."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestration.schemas import AgentResult, BaseAgent, VerificationReport, WorkInstruction


class VerificationAgent(BaseAgent):
    role = "verification"

    def execute(self, instruction: WorkInstruction, context: dict[str, Any]) -> AgentResult:
        prior: dict[str, AgentResult] = context.get("prior_results", {})
        reports: list[dict[str, Any]] = []
        failed = []

        for role, result in prior.items():
            if role == self.role:
                continue
            criteria = context.get("criteria_by_role", {}).get(role, ["artifacts_present"])
            checks = []
            for c in criteria:
                if c == "artifacts_present":
                    passed = bool(result.artifacts)
                elif c == "success_flag":
                    passed = bool(result.success)
                elif c == "metrics_nonempty":
                    m = result.artifacts.get("closed_loop_metrics") or result.artifacts.get("checks")
                    passed = bool(m)
                elif c == "kg_exported":
                    passed = Path(result.artifacts.get("kg_path", "")).exists() if result.artifacts.get("kg_path") else False
                elif c == "api_health":
                    passed = bool((result.artifacts.get("checks") or {}).get("health"))
                else:
                    passed = result.success
                checks.append({"criterion": c, "passed": passed})
            ok = result.success and all(ch["passed"] for ch in checks)
            if not ok:
                failed.append(role)
            reports.append(
                {
                    "agent_role": role,
                    "order_id": result.order_id,
                    "passed": ok,
                    "checks": checks,
                    "remediation": None if ok else f"Supervisor must re-issue work order for {role}",
                }
            )

        artifact = {"reports": reports, "failed_roles": failed, "all_passed": len(failed) == 0}
        Path("orchestration/artifacts/verification.json").write_text(
            json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return AgentResult(
            agent_role=self.role,
            order_id=instruction.order_id,
            success=len(failed) == 0,
            artifacts=artifact,
            errors=[f"Failed: {r}" for r in failed],
            notes="Cross-agent verification complete",
        )

    def verify_result(self, result: AgentResult, criteria: list[str]) -> VerificationReport:
        return self.verify_self(result, criteria)
