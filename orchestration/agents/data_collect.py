"""Data collection agent — builds sample/KCS-style datasets and KG exports."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestration.schemas import AgentResult, BaseAgent, WorkInstruction


class DataCollectAgent(BaseAgent):
    role = "data_collect"

    def execute(self, instruction: WorkInstruction, context: dict[str, Any]) -> AgentResult:
        from backend.app.db.models import get_session_factory, init_db
        from backend.app.services.knowledge.graph import get_kg
        from backend.app.services.knowledge.seed import seed_cases

        Path("data/runtime").mkdir(parents=True, exist_ok=True)
        init_db()
        Session = get_session_factory()
        db = Session()
        try:
            n = seed_cases(db)
            kg = get_kg()
            out = Path("data/knowledge_graph/hs_kg_demo.json")
            kg.export_json(out)
            artifact = {
                "seeded_cases": n,
                "kg_path": str(out),
                "nodes": kg.g.number_of_nodes(),
                "edges": kg.g.number_of_edges(),
            }
            Path("orchestration/artifacts/data_collect.json").write_text(
                json.dumps(artifact, indent=2), encoding="utf-8"
            )
            return AgentResult(
                agent_role=self.role,
                order_id=instruction.order_id,
                success=True,
                artifacts=artifact,
                notes="Seeded product cases and exported HS knowledge graph subset",
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
