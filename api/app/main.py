"""PyZapp public API: instance lifecycle + messaging over WhatsApp."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings, get_settings
from app.errors import ApiError, BaileysError, error_envelope
from app.logging_utils import logger, setup_logging
from app.routes import ai, health, instances
from app.services.baileys import BaileysClient
from app.store import InstanceStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    setup_logging(settings.log_level)
    if settings.api_key == "dev-change-me" and settings.environment == "production":
        logger.error("event=misconfigured API_KEY must be set in production")
        raise RuntimeError("API_KEY must be set in production")

    app.state.baileys = BaileysClient(
        settings.baileys_base_url, settings.internal_api_key, settings.baileys_timeout_s
    )
    app.state.store = InstanceStore(settings.database_path or None)

    import os

    from app.ai.responder import AIResponder
    from app.ai.store import AIStore

    app.state.ai_store = AIStore(settings.database_path or None)

    async def _send_via_baileys(instance_id: str, to: str, text: str) -> str:
        data = await app.state.baileys.send_message(instance_id, to, text)
        return data.get("message_id", "")

    app.state.responder = AIResponder(app.state.ai_store, dict(os.environ), _send_via_baileys)

    # Best-effort re-sync: adopt instances the Baileys service still knows
    # about (e.g. API restarted while sessions persisted on disk).
    try:
        known = await app.state.baileys.list_instances()
        await app.state.store.sync_ids([s["instance_id"] for s in known if "instance_id" in s])
        logger.info("event=startup synced_instances=%d", len(known))
    except Exception as exc:  # noqa: BLE001 - boot must not fail on downstream outage
        logger.warning("event=startup_sync_skipped error=%s", type(exc).__name__)

    yield
    await app.state.baileys.aclose()
    app.state.store.close()
    app.state.ai_store.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="PyZapp API", version="0.1.0")
    app.state.settings = settings or get_settings()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=app.state.settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, tags=["health"])
    app.include_router(instances.router, tags=["instances"])
    app.include_router(ai.router, tags=["ai"])

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(error_envelope(exc.code, exc.message), exc.status_code)

    @app.exception_handler(BaileysError)
    async def _baileys_error(_: Request, exc: BaileysError):
        # Stable codes from baileys-service pass through (404/409/...).
        public = {"instance_not_found", "not_connected", "qr_not_available", "invalid_input", "connection_not_ready"}
        code = exc.code if exc.code in public else "baileys_error"
        status = exc.status_code if exc.code in public else 502
        return JSONResponse(error_envelope(code, exc.message), status)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        code = "unauthorized" if exc.status_code == 401 else "http_error"
        return JSONResponse(error_envelope(code, exc.detail), exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        return JSONResponse(error_envelope("validation_error", str(first.get("msg", "invalid request"))), 422)

    app.router.lifespan_context = lifespan
    return app


app = create_app()
