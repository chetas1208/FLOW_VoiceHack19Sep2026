"""FastAPI application factory for flow-api."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .core import ApiError, Cloud
from .db import make_engine
from .identity import LocalIdentityVerifier, OIDCIdentityVerifier
from .middleware import RequestGuardMiddleware
from .observability import Metrics, configure_logging
from .ratelimit import MemoryRateLimiter, RedisRateLimiter
from .realtime import InProcessBus, RealtimeBus, RedisBus
from .repo import Repo
from .security import AccessTokenService
from .settings import ConfigError, Settings

log = logging.getLogger("flow.cloud")


def build_cloud(settings: Settings, bus: RealtimeBus | None = None, identity=None, limiter=None) -> Cloud:
    engine = make_engine(settings.database_url)
    if settings.database_url.startswith("sqlite") and ":memory:" not in settings.database_url and settings.database_url != "sqlite://":
        from pathlib import Path
        path = settings.database_url.replace("sqlite:///", "", 1)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    if identity is None:
        identity = LocalIdentityVerifier(settings) if settings.auth_mode == "local" else OIDCIdentityVerifier(settings)
    redis_bus = redis_limiter = None
    if settings.redis_url and (bus is None or limiter is None):
        import redis
        redis_bus = RedisBus(settings.redis_url)
        redis_limiter = RedisRateLimiter(redis.Redis.from_url(settings.redis_url, socket_timeout=1, socket_connect_timeout=1))
    return Cloud(settings=settings, repo=Repo(engine), tokens=AccessTokenService(settings), identity=identity,
                 bus=bus or redis_bus or InProcessBus(), limiter=limiter or redis_limiter or MemoryRateLimiter(),
                 metrics=Metrics())


def create_app(settings: Settings | None = None, *, cloud: Cloud | None = None, auto_migrate: bool | None = None) -> FastAPI:
    """`auto_migrate` defaults to True only for non-production sqlite (dev/tests); production uses flow-migrate."""
    settings = (settings or Settings.from_env()).validate()
    configure_logging(settings.log_level)
    cloud = cloud or build_cloud(settings)
    if auto_migrate is None:
        auto_migrate = not settings.is_production and settings.database_url.startswith("sqlite")
    if auto_migrate:
        from .migrate import upgrade
        upgrade(settings.database_url)
    if settings.ephemeral_secret:
        log.warning("using an ephemeral JWT secret; tokens will not survive a restart")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        await cloud.bus.aclose()
        cloud.repo.engine.dispose()

    app = FastAPI(lifespan=lifespan, title="FLOW cloud", version="1", docs_url=None if settings.is_production else "/docs", redoc_url=None,
                  openapi_url=None if settings.is_production else "/openapi.json")
    app.state.cloud = cloud
    app.add_middleware(RequestGuardMiddleware, settings=settings, metrics=cloud.metrics)

    from . import routes_auth, routes_remote, routes_sessions, routes_ws
    for module in (routes_auth, routes_sessions, routes_remote, routes_ws):
        app.include_router(module.router)

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return JSONResponse({"error": exc.code, "message": exc.message}, status_code=exc.status, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        errors = [{"loc": [str(p) for p in e["loc"]], "msg": e["msg"]} for e in exc.errors()]
        return JSONResponse({"error": "validation_error", "message": "invalid request", "details": errors[:10]}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse({"error": "internal_error", "message": "internal error"}, status_code=500)

    return app
