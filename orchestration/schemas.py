"""Shared schemas and base agent for meta-orchestration."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class WorkInstruction:
    order_id: str
    agent_role: str
    title: str
    instructions: str
    acceptance_criteria: list[str]
    priority: int = 1
    dependencies: list[str] = field(default_factory=list)


@dataclass
class AgentResult:
    agent_role: str
    order_id: str
    success: bool
    artifacts: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    notes: str = ""
    completed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class VerificationReport:
    order_id: str
    agent_role: str
    passed: bool
    checks: list[dict[str, Any]]
    remediation: Optional[str] = None


class BaseAgent(ABC):
    role: str = "base"

    @abstractmethod
    def execute(self, instruction: WorkInstruction, context: dict[str, Any]) -> AgentResult:
        raise NotImplementedError

    def verify_self(self, result: AgentResult, criteria: list[str]) -> VerificationReport:
        checks = []
        for c in criteria:
            ok = bool(result.success and result.artifacts)
            checks.append({"criterion": c, "passed": ok})
        passed = result.success and all(ch["passed"] for ch in checks)
        return VerificationReport(
            order_id=result.order_id,
            agent_role=self.role,
            passed=passed,
            checks=checks,
            remediation=None if passed else "Re-run with corrections from supervisor",
        )
