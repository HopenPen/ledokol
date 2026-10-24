"""Точка входа API: uvicorn app.main:app --reload"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import attachments, auth, companies, operations, planning
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.domain.categories import CATEGORIES

log = logging.getLogger("cashflow.http")


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    if get_settings().env != "prod":
        # В dev/test схема создаётся сама; в prod — только миграциями (alembic upgrade head).
        import app.db.models  # noqa: F401 — регистрируем модели в metadata
        from app.db.session import Base, engine

        Base.metadata.create_all(engine)
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="Cashflow — прогноз денег для МСП", version="0.1.0", lifespan=lifespan,
                  docs_url="/docs" if s.env != "prod" else None, redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "Idempotency-Key"])

    @app.middleware("http")
    async def security_and_access_log(request: Request, call_next):
        request_id = uuid.uuid4().hex[:12]
        started = time.perf_counter()
        response = await call_next(request)
        response.headers.update({
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "X-Frame-Options": "DENY",
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            "X-Request-ID": request_id,
        })
        # В лог — только метод, шаблон пути, статус и время. Ни тела запроса, ни query, ни заголовков.
        route = request.scope.get("route")
        log.info("request", extra={"method": request.method, "path": getattr(route, "path", "unmatched"),
                                   "status": response.status_code, "request_id": request_id,
                                   "duration_ms": round((time.perf_counter() - started) * 1000)})
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        # Наружу — общий текст без стектрейса; детали — во внутреннем логе (без данных клиента).
        log.exception("unhandled_error", extra={"reason": type(exc).__name__})
        return JSONResponse({"detail": "Внутренняя ошибка. Мы уже разбираемся."}, status_code=500)

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/meta/categories", tags=["meta"])
    def categories() -> list[dict]:
        return [{"code": c.code, "label": c.label, "mandatory": c.mandatory, "role": c.role.value}
                for c in CATEGORIES.values()]

    for r in (auth.router, companies.router, operations.router, planning.router, attachments.router):
        app.include_router(r, prefix="/api")
    return app


app = create_app()
