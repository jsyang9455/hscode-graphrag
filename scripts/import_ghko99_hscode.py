"""Import ghko99/Hscode enriched CSV into HsCodeRecord + reload GraphRAG."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.db.models import HsCodeRecord, init_db, get_session_factory, reset_engine_cache
from backend.app.services.knowledge.graph import get_kg
from backend.app.services.knowledge.loader import (
    GHKO99_CSV,
    KCS_CSV,
    ingest_ghko99,
    ingest_kcs_hsk,
)


def main() -> None:
    if not GHKO99_CSV.exists():
        raise SystemExit(
            f"Missing {GHKO99_CSV}. Run: python scripts/convert_ghko99_hscode.py --src /path/to/Hscode"
        )
    reset_engine_cache()
    init_db()
    Session = get_session_factory()
    db = Session()
    try:
        steps = []
        if KCS_CSV.exists():
            steps.append({"kcs_master": ingest_kcs_hsk(db, csv_path=KCS_CSV)})
        steps.append({"ghko99": ingest_ghko99(db, csv_path=GHKO99_CSV)})
        kg_nodes = get_kg().load_from_db(db)
        out = {
            "steps": steps,
            "kg_nodes": kg_nodes,
            "hs_records": db.query(HsCodeRecord).count(),
            "ghko99_sourced": db.query(HsCodeRecord)
            .filter(HsCodeRecord.source == "ghko99_hscode")
            .count(),
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
