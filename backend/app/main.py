from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.app.api.routes import router
from backend.app.core.config import get_settings
from backend.app.db.models import init_db


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="HSCode-GraphRAG API",
        description="Customs Broker Supervisory Agent-Driven Knowledge-Driven GraphRAG",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list + ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api/v1")

    @app.on_event("startup")
    def _startup() -> None:
        Path("data/runtime").mkdir(parents=True, exist_ok=True)
        init_db()

    # Serve built frontend if present
    frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

    return app


app = create_app()
