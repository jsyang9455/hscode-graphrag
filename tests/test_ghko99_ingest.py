"""Regression: ghko99 enriched HS master converts and searches case aliases."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GHKO99_CSV = ROOT / "data" / "kcs" / "ghko99_hscode_enriched.csv"


def test_ghko99_csv_present_and_shaped():
    assert GHKO99_CSV.exists(), "Run scripts/convert_ghko99_hscode.py first"
    text = GHKO99_CSV.read_text(encoding="utf-8").splitlines()
    assert len(text) > 10000
    header = text[0]
    assert "HS_KEY" in header
    assert "final_combined_text" in header
    # Ivory rod case alias from DATA.csv should survive into enriched file
    body = "\n".join(text[1:2000]).lower()
    assert "0101211000" in body or "0101.21" in body


def test_ghko99_alias_search(tmp_path, monkeypatch):
    if not GHKO99_CSV.exists():
        return
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/ghko99_test.db")
    import backend.app.core.config as config
    import backend.app.db.models as models

    config.get_settings.cache_clear()
    models.reset_engine_cache()

    from backend.app.db.models import HsCodeRecord, init_db, get_session_factory
    from backend.app.services.knowledge.graph import get_kg
    from backend.app.services.knowledge.loader import ingest_ghko99

    init_db(drop_all=True)
    db = get_session_factory()()
    try:
        meta = ingest_ghko99(db, csv_path=GHKO99_CSV, limit=3000)
        assert meta["added"] + meta["updated"] > 0
        assert db.query(HsCodeRecord).count() >= 1000
        kg = get_kg()
        kg.load_from_db(db)
        hits = kg.local_search("Kimlar beef roll", top_k=5)
        codes = [h["code"] for h in hits]
        assert any(c.startswith("0201") or c.startswith("0202") for c in codes)
        coffee = kg.local_search("인스턴트 커피", top_k=5)
        assert any(h["code"].startswith("2101") for h in coffee)
    finally:
        db.close()
