"""Supervisor (총괄에이전트): design, plan, instruct, verify, remediate."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestration.agents.analysis import AnalysisAgent
from orchestration.agents.api_agent import APIAgent
from orchestration.agents.backend_dev import BackendDevAgent
from orchestration.agents.data_collect import DataCollectAgent
from orchestration.agents.empirical_report import EmpiricalReportAgent
from orchestration.agents.frontend_dev import FrontendDevAgent
from orchestration.agents.paper_writer import PaperWriterAgent
from orchestration.agents.verification import VerificationAgent
from orchestration.schemas import AgentResult, WorkInstruction


class SupervisorAgent:
    """Customs-research program supervisor — not the HS CustomsBrokerAgent.

    Designs work orders, dispatches specialist agents, verifies outputs,
    and re-issues corrected instructions when verification fails.
    """

    role = "supervisor"

    def __init__(self) -> None:
        self.agents = {
            "data_collect": DataCollectAgent(),
            "analysis": AnalysisAgent(),
            "backend_dev": BackendDevAgent(),
            "frontend_dev": FrontendDevAgent(),
            "api": APIAgent(),
            "verification": VerificationAgent(),
            "empirical_report": EmpiricalReportAgent(),
            "paper_writer": PaperWriterAgent(),
        }
        self.plan_path = Path("docs/design/master_plan.json")
        self.work_order_dir = Path("docs/work_orders")
        self.work_order_dir.mkdir(parents=True, exist_ok=True)
        Path("orchestration/artifacts").mkdir(parents=True, exist_ok=True)

    def design_plan(self) -> dict[str, Any]:
        plan = {
            "project": "HSCode-GraphRAG Empirical System",
            "objective": (
                "Build a closed-loop HS classification stack with CustomsBrokerAgent "
                "supervision, persist all evidence, and generate empirical + paper drafts."
            ),
            "layers": [
                "Knowledge layer (HS KG + communities)",
                "Orchestration layer (Hypothesis + Critic + Knowledge loop)",
                "Retrieval/Generation layer (Local+Global GraphRAG, GIR grounding)",
                "Supervisory layer (CustomsBrokerAgent, Opinion Report, K_history)",
            ],
            "gaps_addressed": [
                "Added meta-agent program office for reproducible empirical delivery",
                "Docker/AWS packaging for deployable verification",
                "Persistent stores for classifications, deltas, reports, paper sections",
                "Ablation path (no_feedback) for RQ5 closed-loop evaluation",
            ],
            "phases": [
                {"id": "P1", "name": "Data & KG", "agents": ["data_collect"]},
                {"id": "P2", "name": "Platform build verify", "agents": ["backend_dev", "frontend_dev", "api"]},
                {"id": "P3", "name": "Empirical analysis", "agents": ["analysis"]},
                {"id": "P4", "name": "Verification gate", "agents": ["verification"]},
                {"id": "P5", "name": "Reports & paper", "agents": ["empirical_report", "paper_writer"]},
            ],
        }
        self.plan_path.parent.mkdir(parents=True, exist_ok=True)
        self.plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
        return plan

    def build_work_orders(self) -> list[WorkInstruction]:
        specs = [
            (
                "data_collect",
                "Seed KCS-style cases and export HS KG",
                "Load demo product cases; export knowledge graph JSON for auditability.",
                ["success_flag", "kg_exported", "artifacts_present"],
            ),
            (
                "backend_dev",
                "Verify backend classification stack",
                "Confirm importable modules, requirements, and Dockerfile for API services.",
                ["success_flag", "artifacts_present"],
            ),
            (
                "frontend_dev",
                "Verify frontend dashboard scaffold",
                "Confirm dashboard HTML/JS/CSS and container build files exist.",
                ["success_flag", "artifacts_present"],
            ),
            (
                "api",
                "Smoke-test REST API",
                "Hit health, seed, classify, metrics endpoints; ensure persistence works.",
                ["success_flag", "api_health", "artifacts_present"],
            ),
            (
                "analysis",
                "Run closed-loop empirical classification",
                "Classify all seeded cases with closed-loop feedback; record ablation pass metrics.",
                ["success_flag", "metrics_nonempty", "artifacts_present"],
            ),
            (
                "verification",
                "Verify all prior agent deliverables",
                "Check acceptance criteria; list failed roles for remediation.",
                ["success_flag", "artifacts_present"],
            ),
            (
                "empirical_report",
                "Generate empirical verification report",
                "Write markdown/JSON report from DB metrics and experiment runs.",
                ["success_flag", "artifacts_present"],
            ),
            (
                "paper_writer",
                "Draft paper sections from stored evidence",
                "Produce APA-oriented paper draft sections persisted to DB and reports/.",
                ["success_flag", "artifacts_present"],
            ),
        ]
        orders: list[WorkInstruction] = []
        for role, title, instructions, criteria in specs:
            oid = f"WO-{role}-{uuid.uuid4().hex[:6]}"
            wi = WorkInstruction(
                order_id=oid,
                agent_role=role,
                title=title,
                instructions=instructions,
                acceptance_criteria=criteria,
            )
            orders.append(wi)
            Path(self.work_order_dir / f"{oid}.json").write_text(
                json.dumps(
                    {
                        "order_id": wi.order_id,
                        "agent_role": wi.agent_role,
                        "title": wi.title,
                        "instructions": wi.instructions,
                        "acceptance_criteria": wi.acceptance_criteria,
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        return orders

    def dispatch(self, order: WorkInstruction, context: dict[str, Any]) -> AgentResult:
        agent = self.agents[order.agent_role]
        print(f"[Supervisor] → {order.agent_role}: {order.title} ({order.order_id})")
        result = agent.execute(order, context)
        status = "OK" if result.success else "FAIL"
        print(f"[Supervisor] ← {order.agent_role}: {status} {result.notes}")
        if result.errors:
            for e in result.errors:
                print(f"    ! {e}")
        return result

    def remediate_and_retry(
        self,
        order: WorkInstruction,
        result: AgentResult,
        context: dict[str, Any],
        max_retries: int = 1,
    ) -> AgentResult:
        current = result
        for attempt in range(max_retries):
            if current.success:
                return current
            print(f"[Supervisor] Remediation retry {attempt + 1} for {order.agent_role}")
            # Strengthen instruction
            order.instructions += (
                f"\n[REMEDIATION] Previous errors: {current.errors}. Fix and re-run cleanly."
            )
            current = self.dispatch(order, context)
        return current

    def run(self) -> dict[str, Any]:
        plan = self.design_plan()
        orders = self.build_work_orders()
        criteria_by_role = {o.agent_role: o.acceptance_criteria for o in orders}
        prior_results: dict[str, AgentResult] = {}
        context: dict[str, Any] = {
            "plan": plan,
            "prior_results": prior_results,
            "criteria_by_role": criteria_by_role,
        }

        # Persist work orders to DB when possible
        try:
            from backend.app.db.models import WorkOrder, get_session_factory, init_db

            Path("data/runtime").mkdir(parents=True, exist_ok=True)
            init_db()
            Session = get_session_factory()
            db = Session()
            for o in orders:
                exists = db.query(WorkOrder).filter(WorkOrder.order_id == o.order_id).first()
                if not exists:
                    db.add(
                        WorkOrder(
                            order_id=o.order_id,
                            agent_role=o.agent_role,
                            title=o.title,
                            instructions=o.instructions,
                            acceptance_criteria=o.acceptance_criteria,
                            status="issued",
                        )
                    )
            db.commit()
            db.close()
        except Exception as e:  # noqa: BLE001
            print(f"[Supervisor] DB work-order persist skipped: {e}")

        for order in orders:
            if order.agent_role == "verification":
                context["prior_results"] = prior_results
            result = self.dispatch(order, context)
            result = self.remediate_and_retry(order, result, context)
            prior_results[order.agent_role] = result

            try:
                from backend.app.db.models import WorkOrder, get_session_factory

                Session = get_session_factory()
                db = Session()
                wo = db.query(WorkOrder).filter(WorkOrder.order_id == order.order_id).first()
                if wo:
                    wo.status = "verified" if result.success else "failed"
                    wo.result = {
                        "success": result.success,
                        "artifacts": result.artifacts,
                        "errors": result.errors,
                        "notes": result.notes,
                    }
                    wo.verification_notes = "passed" if result.success else "; ".join(result.errors)
                    db.commit()
                db.close()
            except Exception as e:  # noqa: BLE001
                print(f"[Supervisor] WO update skipped: {e}")

        # Final gate: if verification failed, stop before paper? Still attempt report with note
        summary = {
            "plan": plan["project"],
            "results": {
                role: {"success": r.success, "notes": r.notes, "errors": r.errors}
                for role, r in prior_results.items()
            },
            "all_passed": all(r.success for r in prior_results.values()),
        }
        Path("orchestration/artifacts/supervisor_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        Path("reports/supervisor_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return summary


def main() -> None:
    supervisor = SupervisorAgent()
    summary = supervisor.run()
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if not summary["all_passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
