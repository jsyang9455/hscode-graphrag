import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_kcs_priority_file_exists():
    assert (ROOT / "data/kcs/kcs_hsk_priority.csv").exists()


def test_signup_classify_broker_learning(tmp_path, monkeypatch):
    db_path = tmp_path / "t.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import backend.app.core.config as config
    import backend.app.db.models as models

    config.get_settings.cache_clear()
    models.reset_engine_cache()

    from fastapi.testclient import TestClient
    from backend.app.main import app
    from backend.app.db.models import init_db, get_session_factory
    from backend.app.services.knowledge.loader import ingest_kcs_hsk

    init_db(drop_all=True)
    Session = get_session_factory()
    db = Session()
    ingest_kcs_hsk(db, csv_path=ROOT / "data/kcs/kcs_hsk_priority.csv", limit=500)
    db.close()

    client = TestClient(app)
    su = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "broker@test.com",
            "password": "pass12345",
            "full_name": "테스트관세사",
            "office_code": "TEST-01",
            "office_name": "테스트사무소",
        },
    )
    assert su.status_code == 200, su.text
    token = su.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    cl = client.post(
        "/api/v1/classify",
        headers=headers,
        json={"description": "수분 크림 화장품 skincare", "material": "cream", "function": "skin care"},
    )
    assert cl.status_code == 200, cl.text
    cid = cl.json()["classification_id"]
    assert cl.json()["status"] == "pending_broker"

    pending = client.get("/api/v1/opinions/pending", headers=headers)
    assert pending.status_code == 200
    assert any(p["classification_id"] == cid for p in pending.json())

    fb = client.post(
        "/api/v1/opinions/broker-review",
        headers=headers,
        json={
            "classification_id": cid,
            "broker_hs": cl.json()["recommended_hs"],
            "conditions": ["hs_accurate", "tariff_benefit"],
            "detail_opinion": "추천 코드 적절, 관세율도 유리",
        },
    )
    assert fb.status_code == 200, fb.text
    assert fb.json()["applied_to_learning"] is True

    weights = client.get("/api/v1/learning/weights", headers=headers)
    assert weights.status_code == 200
    assert isinstance(weights.json(), list)
