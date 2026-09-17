"""Paper / thesis draft agent — writes APA-oriented sections from stored evidence."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestration.schemas import AgentResult, BaseAgent, WorkInstruction


SECTIONS = [
    ("introduction", "Introduction"),
    ("related_work", "Related Work"),
    ("framework", "HSCode-GraphRAG Framework"),
    ("experimental_design", "Experimental Design"),
    ("results", "Results"),
    ("discussion", "Discussion"),
    ("conclusion", "Conclusion"),
]


class PaperWriterAgent(BaseAgent):
    role = "paper_writer"

    def execute(self, instruction: WorkInstruction, context: dict[str, Any]) -> AgentResult:
        from backend.app.db.models import (
            EmpiricalReport,
            KnowledgeHistory,
            PaperArtifact,
            get_session_factory,
            init_db,
        )
        from backend.app.services.metrics.eval import compute_metrics

        Path("data/runtime").mkdir(parents=True, exist_ok=True)
        init_db()
        Session = get_session_factory()
        db = Session()
        try:
            metrics = compute_metrics(db)
            emp = db.query(EmpiricalReport).order_by(EmpiricalReport.id.desc()).first()
            kh_n = db.query(KnowledgeHistory).count()

            contents = {
                "introduction": (
                    "HS code misclassification in high-volume cross-border e-commerce creates tariff risk, "
                    "regulatory exposure, and logistics delay. Korea's surge in inbound and outbound direct "
                    "purchases intensifies verification scarcity under list-clearance regimes. This paper "
                    "proposes HSCode-GraphRAG, a four-layer framework with a CustomsBrokerAgent supervisory "
                    "layer that enforces closed-loop expert feedback into K_history."
                ),
                "related_work": (
                    "Prior work progressed from text classifiers to explainable RAG and knowledge-graph agents "
                    "(e.g., HSGraphAgent), yet typically explores a single classification path, lacks "
                    "cross-session knowledge transfer, omits metric-gaming defenses, and treats brokers as "
                    "open-loop escalation endpoints. Closed-loop expert supervision literature (EON, DNFO, "
                    "Digital Apprentice) motivates embedding broker corrections as first-class learning signals."
                ),
                "framework": (
                    "HSCode-GraphRAG comprises (1) HS regulatory knowledge graph with hierarchical communities, "
                    "(2) knowledge-driven multi-agent orchestration (HypothesisAgent, RegulationCritic), "
                    "(3) dual-channel Local+Global GraphRAG retrieval with adaptive routing, and "
                    "(4) CustomsBrokerAgent tiered review producing Opinion Reports and structured correction "
                    "deltas that update K_history and K_guard reality anchors."
                ),
                "experimental_design": (
                    "We evaluate on a KCS-10D-style demonstration set with closed-loop vs no-feedback ablation. "
                    "Metrics include Top-1, regulation violation rate (RVR), expert-system agreement (ESA), "
                    "correction incorporation rate (CIR), escalation rate, and mode-collapse flags."
                ),
                "results": (
                    f"Stored empirical metrics (n={metrics.get('n')}): Top-1={metrics.get('top1')}, "
                    f"ESA={metrics.get('esa')}, RVR={metrics.get('rvr')}, CIR={metrics.get('cir')}, "
                    f"escalation_rate={metrics.get('escalation_rate')}, override_rate={metrics.get('override_rate')}. "
                    f"K_history accumulated {kh_n} structured correction records. "
                    + (
                        emp.summary
                        if emp
                        else "Empirical report pending; metrics sourced directly from classification store."
                    )
                ),
                "discussion": (
                    "Closed-loop broker corrections provide a reality anchor that mitigates open-loop "
                    "Correction Collapse risk. Dual-channel retrieval surfaces chapter contention notes that "
                    "single-path agents miss. Limitations include demo KG coverage, simulated broker policy "
                    "relative to licensed human brokers, and need for larger KCS-10D Hard calibration studies."
                ),
                "conclusion": (
                    "HSCode-GraphRAG demonstrates a deployable closed-loop architecture for regulation-compliant "
                    "HS classification under e-commerce volume pressure. Future work expands the regulatory "
                    "graph, integrates live LLM backbones, and conducts multi-broker ORQ/RTR user studies."
                ),
            }

            refs = [
                "Guo, X. (2025). Expert Oversight Network (EON).",
                "Lee, E., et al. (2023). Explainable Product Classification for Customs. ACM TIST.",
                "Seki, T. (2026). Distributed Negative Feedback Optimization for Multi-Agent AI.",
                "Weber, T., & Taneja, R. (2026). The Digital Apprentice.",
                "Ko, J. (2026). Preventing Correction Collapse.",
            ]

            # Clear previous draft sections for idempotent runs
            for old in db.query(PaperArtifact).all():
                db.delete(old)
            db.commit()

            saved = []
            for key, title in SECTIONS:
                art = PaperArtifact(
                    title=title,
                    section=key,
                    content=contents[key],
                    sources=refs,
                )
                db.add(art)
                saved.append({"section": key, "title": title, "chars": len(contents[key])})
            db.commit()

            paper_md = ["# HSCode-GraphRAG — Paper Draft (from stored empirical data)", ""]
            for key, title in SECTIONS:
                paper_md.append(f"## {title}")
                paper_md.append("")
                paper_md.append(contents[key])
                paper_md.append("")
            paper_md.append("## References")
            paper_md.append("")
            for r in refs:
                paper_md.append(f"- {r}")

            out = Path("reports/paper_draft.md")
            out.write_text("\n".join(paper_md), encoding="utf-8")
            meta = {"sections": saved, "metrics_used": metrics, "path": str(out)}
            Path("orchestration/artifacts/paper_writer.json").write_text(
                json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            Path("reports/paper_draft_meta.json").write_text(
                json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            return AgentResult(
                agent_role=self.role,
                order_id=instruction.order_id,
                success=True,
                artifacts=meta,
                notes="Paper draft generated from DB-backed metrics and empirical report",
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
