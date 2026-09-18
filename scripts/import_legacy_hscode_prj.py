"""Import legacy jsyang9455/hscode_prj HSK master into DB."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.db.models import init_db, get_session_factory, reset_engine_cache
from backend.app.services.knowledge.loader import ingest_kcs_hsk, KCS_CSV
from backend.app.services.knowledge.graph import get_kg


def main() -> None:
    reset_engine_cache()
    init_db()
    Session = get_session_factory()
    db = Session()
    try:
        path = KCS_CSV if KCS_CSV.exists() else ROOT / "data/kcs/kcs_hsk_priority.csv"
        meta = ingest_kcs_hsk(db, csv_path=path)
        n = get_kg().load_from_db(db)
        print({"ingest": meta, "kg_nodes": n})
    finally:
        db.close()


if __name__ == "__main__":
    main()
