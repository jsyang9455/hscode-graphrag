"""Empirical & verification report generation agent."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestration.schemas import AgentResult, BaseAgent, WorkInstruction


class EmpiricalReportAgent(BaseAgent):
    role = "empirical_report"

    def execute(self, instruction: WorkInstruction, context: dict[str, Any]) -> AgentResult:
        from backend.app.db.models import EmpiricalReport, ExperimentRun, get_session_factory, init_db
        from backend.app.services.metrics.eval import compute_metrics

        Path("data/runtime").mkdir(parents=True, exist_ok=True)
        init_db()
        Session = get_session_factory()
        db = Session()
        try:
            metrics = compute_metrics(db)
            experiments = db.query(ExperimentRun).order_by(ExperimentRun.id.desc()).limit(10).all()
            findings = [
                f"Sample size n={metrics.get('n', 0)} classifications stored.",
                f"Top-1 accuracy (vs GT)={metrics.get('top1')}, ESA={metrics.get('esa')}, RVR={metrics.get('rvr')}.",
                f"CIR (correction incorporation)={metrics.get('cir')}, escalation_rate={metrics.get('escalation_rate')}.",
                f"Override rate={metrics.get('override_rate')}; mode_collapse flags={metrics.get('mode_collapse_flags')}.",
                "Closed-loop CustomsBrokerAgent feedback persisted into K_history and K_guard.",
            ]
            if metrics.get("top1", 0) >= 0.5:
                findings.append("Demo run meets minimum empirical viability threshold (Top-1 >= 0.5).")
            else:
                findings.append("Top-1 below 0.5 — expand KG coverage / seed diversity before paper claims.")

            summary = (
                "HSCode-GraphRAG empirical verification report. "
                "Pipeline executed dual-channel retrieval, multi-agent orchestration, "
                "tiered CustomsBrokerAgent review, and closed-loop K_history accumulation."
            )
            report = EmpiricalReport(
                title="HSCode-GraphRAG Empirical Verification Report",
                summary=summary,
                metrics=metrics,
                findings=findings,
            )
            db.add(report)
            db.commit()
            db.refresh(report)

            md_lines = [
                "# HSCode-GraphRAG Empirical Verification Report",
                "",
                summary,
                "",
                "## Metrics",
                "```json",
                json.dumps(metrics, indent=2, ensure_ascii=False),
                "```",
                "",
                "## Findings",
            ]
            for f in findings:
                md_lines.append(f"- {f}")
            md_lines.extend(["", "## Recent Experiments"])
            for e in experiments:
                md_lines.append(f"- {e.name} ({e.experiment_type}): {json.dumps(e.metrics, ensure_ascii=False)}")

            report_path = Path("reports/empirical_verification_report.md")
            report_path.write_text("\n".join(md_lines), encoding="utf-8")
            json_path = Path("reports/empirical_verification_report.json")
            payload = {
                "id": report.id,
                "title": report.title,
                "summary": summary,
                "metrics": metrics,
                "findings": findings,
            }
            json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

            return AgentResult(
                agent_role=self.role,
                order_id=instruction.order_id,
                success=True,
                artifacts={"report_id": report.id, "md": str(report_path), "json": str(json_path), **payload},
                notes="Empirical report generated from stored DB metrics",
            )
        except Exception as e:  # noqa: BLE001
            return AgentResult(
                agent_role=self.role,
                order_id=instruction.order_id,
                success=False,
                errors=[str(e)],
            )
        finally:
            db.close()
