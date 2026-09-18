from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.app.api.routes import router
from backend.app.api.chat_docs import router as chat_docs_router
from backend.app.core.config import get_settings
from backend.app.db.models import HsCodeRecord, init_db, get_session_factory
from backend.app.services.auth.bootstrap import ensure_demo_account
from backend.app.services.knowledge.graph import get_kg
from backend.app.services.knowledge.loader import ingest_kcs_hsk, ingest_wco_fallback, KCS_CSV


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="HSCode-GraphRAG API",
        description="Office-tenant Customs Broker HITL + KCS HSK GraphRAG (legacy hscode_prj data)",
        version="0.3.1",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list + ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api/v1")
    app.include_router(chat_docs_router, prefix="/api/v1")

    @app.on_event("startup")
    def _startup() -> None:
        Path("data/runtime").mkdir(parents=True, exist_ok=True)
        Path("data/runtime/uploads").mkdir(parents=True, exist_ok=True)
        Path("data/kcs").mkdir(parents=True, exist_ok=True)
        init_db(drop_all=False)
        Session = get_session_factory()
        db = Session()
        try:
            demo = ensure_demo_account(db)
            print(
                f"[startup] demo account email={demo['email']} "
                f"office={demo['office_code']} created_user={demo['created_user']}"
            )
            n = db.query(HsCodeRecord).count()
            if n < 100:
                priority = Path("data/kcs/kcs_hsk_priority.csv")
                if priority.exists():
                    meta = ingest_kcs_hsk(db, csv_path=priority)
                    print(f"[startup] priority KCS ingest: {meta}")
                elif KCS_CSV.exists():
                    meta = ingest_kcs_hsk(db, limit=8000)
                    print(f"[startup] partial KCS ingest: {meta}")
                else:
                    meta = ingest_wco_fallback(db)
                    print(f"[startup] WCO fallback: {meta}")
            loaded = get_kg().load_from_db(db)
            print(f"[startup] GraphRAG nodes={loaded}")
        except Exception as e:  # noqa: BLE001
            print(f"[startup] HS ingest warning: {e}")
        finally:
            db.close()

    frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return app


app = create_app()
