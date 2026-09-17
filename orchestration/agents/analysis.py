"""Analysis agent — runs closed-loop vs open-loop experiments and metrics."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestration.schemas import AgentResult, BaseAgent, WorkInstruction


class AnalysisAgent(BaseAgent):
    role = "analysis"

    def execute(self, instruction: WorkInstruction, context: dict[str, Any]) -> AgentResult:
        from backend.app.db.models import ExperimentRun, ProductCase, get_session_factory, init_db
        from backend.app.services.classification.pipeline import ClassificationPipeline
        from backend.app.services.metrics.eval import compute_metrics

        Path("data/runtime").mkdir(parents=True, exist_ok=True)
        init_db()
        Session = get_session_factory()
        db = Session()
        pipe = ClassificationPipeline()
        try:
            cases = db.query(ProductCase).all()
            if not cases:
                return AgentResult(
                    agent_role=self.role,
                    order_id=instruction.order_id,
                    success=False,
                    errors=["No cases; run data_collect first"],
                )

            # Closed-loop run
            for case in cases:
                pipe.classify(db, case, closed_loop=True)
            closed_metrics = compute_metrics(db)

            # Open-loop ablation on same cases (second pass)
            for case in cases:
                pipe.classify(db, case, closed_loop=False)
            # Metrics are cumulative; store both snapshots from experiment configs
            open_run = ExperimentRun(
                name="ablation_no_feedback_pass",
                experiment_type="ablation",
                config={"closed_loop": False},
                metrics=compute_metrics(db),
            )
            closed_run = ExperimentRun(
                name="main_closed_loop",
                experiment_type="main_comparison",
                config={"closed_loop": True},
                metrics=closed_metrics,
            )
            db.add(closed_run)
            db.add(open_run)
            db.commit()

            artifact = {
                "closed_loop_metrics": closed_metrics,
                "cumulative_after_open_loop": open_run.metrics,
                "n_cases": len(cases),
            }
            Path("orchestration/artifacts/analysis.json").write_text(
                json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            return AgentResult(
                agent_role=self.role,
                order_id=instruction.order_id,
                success=True,
                artifacts=artifact,
                notes="Completed closed-loop classification and ablation pass",
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
