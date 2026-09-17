import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_kg_local_search():
    from backend.app.services.knowledge.graph import get_kg

    kg = get_kg()
    hits = kg.local_search("facial cream lotion skin care")
    assert hits
    assert hits[0]["code"].startswith("3304")


def test_classify_closed_loop(tmp_path, monkeypatch):
    db_path = tmp_path / "t.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    # reset engine cache
    import backend.app.db.models as models
    import backend.app.core.config as config

    config.get_settings.cache_clear()
    models._engine = None
    models._SessionLocal = None

    from backend.app.db.models import ProductCase, init_db, get_session_factory
    from backend.app.services.classification.pipeline import ClassificationPipeline
    from backend.app.services.knowledge.seed import seed_cases

    init_db()
    Session = get_session_factory()
    db = Session()
    seed_cases(db)
    case = db.query(ProductCase).first()
    out = ClassificationPipeline().classify(db, case, closed_loop=True)
    assert out.final_hs
    assert out.opinion["confidence_grade"] in {"High", "Medium", "Low"}
    db.close()
