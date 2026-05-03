import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlmodel import Session, create_engine, select, SQLModel

logger = logging.getLogger(__name__)


def _init_sentry() -> None:
    """Initialise Sentry if SENTRY_DSN is set. No-op locally."""
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        sentry_sdk.init(
            dsn=dsn,
            integrations=[FastApiIntegration()],
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_RATE", "0.1")),
            environment=os.getenv("SENTRY_ENV", "production"),
        )
    except Exception as e:
        logger.warning(f"Sentry init failed: {e}")


def _init_structlog() -> None:
    """JSON structured logging when STRUCTLOG_JSON=true. Otherwise stdlib."""
    if os.getenv("STRUCTLOG_JSON", "").lower() != "true":
        logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                            format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        return
    try:
        import structlog
        structlog.configure(
            processors=[
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.JSONRenderer(),
            ],
        )
        logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")
    except Exception as e:
        logger.warning(f"structlog init failed: {e}")


_init_sentry()
_init_structlog()

from app.settings import get_settings
from app.container import Container
from app.routes import router
from app.api.auth import router as auth_router
from app.api.plans import router as plans_router
from app.api.profile import router as profile_router
from app.api.checkin import router as checkin_router
from app.api.progress import router as progress_router
from app.api.nutrition import router as nutrition_router
from app.api.coach import router as coach_router
from app.api.admin import router as admin_router
from app.api.sets import router as sets_router
from app.api.feedback import router as feedback_router
from app.api.health import router as health_router


def _make_engine(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, echo=False, connect_args=connect_args)


def _run_migrations(database_url: str) -> bool:
    """Run alembic upgrade head. Returns True on success, False on failure.
    Skipped on SQLite (dev) because some legacy migrations don't support
    SQLite's lack of full ALTER TABLE — dev relies on SQLModel.create_all."""
    if database_url.startswith("sqlite"):
        return False
    try:
        from alembic import command
        from alembic.config import Config
        cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
        cfg.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(cfg, "head")
        return True
    except Exception as e:
        logger.warning(f"Alembic upgrade failed: {e}. Falling back to create_all().")
        return False


def _detect_schema_drift_and_rebuild(engine) -> None:
    """SQLite-only: if the live `clientprofile` table is missing columns the
    current model defines, DROP + CREATE all tables. Wipes data — only safe
    for dev. Logs loudly when triggered."""
    if not str(engine.url).startswith("sqlite"):
        return
    from sqlalchemy import inspect
    from app.models import ClientProfile
    inspector = inspect(engine)
    if "clientprofile" not in inspector.get_table_names():
        return  # fresh DB; create_all will handle it
    live_cols = {c["name"] for c in inspector.get_columns("clientprofile")}
    expected_cols = set(ClientProfile.__table__.columns.keys())
    missing = expected_cols - live_cols
    if missing:
        logger.warning(
            f"⚠️  Schema drift detected on SQLite. Missing columns: {sorted(missing)}. "
            f"DROPPING + RECREATING all tables (dev DB is ephemeral)."
        )
        SQLModel.metadata.drop_all(engine)
        SQLModel.metadata.create_all(engine)


def _ensure_super_admin(engine) -> None:
    """Self-heal the super-admin row. Forces is_admin=True + is_coach=True so
    role drift after manual DB edits or partial migrations cannot lock everyone
    out. If the row doesn't exist yet, log a warning — user must register first."""
    from app.models import ClientProfile
    settings = get_settings()
    email = settings.super_admin_email
    if not email:
        return
    with Session(engine) as session:
        user = session.exec(select(ClientProfile).where(ClientProfile.email == email)).first()
        if user is None:
            logger.warning(
                f"Super-admin email '{email}' has not registered yet. "
                f"They will be auto-promoted on first login."
            )
            return
        changed = False
        if not user.is_admin:
            user.is_admin = True
            changed = True
        if not user.is_coach:
            user.is_coach = True
            changed = True
        if changed:
            session.add(user)
            session.commit()
            logger.info(f"✅ Self-healed super-admin flags for {email}.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    if settings.auth_secret_key in ("", "change-me-in-production"):
        logger.warning(
            "⚠️  AUTH_SECRET_KEY is using the default placeholder. "
            "Run `python scripts/generate_secret.py --append-to .env` and restart "
            "before exposing this server to anyone but yourself."
        )
    if settings.cors_allowed_origins.strip() == "*":
        logger.warning(
            "⚠️  CORS allows all origins (*). Set CORS_ALLOWED_ORIGINS to your "
            "explicit frontend URL(s) before deploying to production."
        )

    engine = _make_engine(settings.database_url)

    # Postgres: alembic upgrade head. SQLite (dev): create_all + drift rebuild.
    if settings.database_url.startswith("sqlite"):
        _detect_schema_drift_and_rebuild(engine)
        SQLModel.metadata.create_all(engine)
    else:
        if not _run_migrations(settings.database_url):
            SQLModel.metadata.create_all(engine)

    # Ensure the super-admin always has the right flags
    _ensure_super_admin(engine)

    app.state.container = Container(
        settings=settings,
        session_factory=lambda: Session(engine),
    )
    yield


def _install_rate_limiter(app: FastAPI) -> None:
    """Per-IP rate limiting on auth endpoints. slowapi is optional — if not
    installed, we skip without crashing. Disabled when DISABLE_RATELIMIT=true
    (test fixtures + dev rapid-iterating)."""
    if os.getenv("DISABLE_RATELIMIT", "").lower() == "true":
        return
    try:
        from slowapi import Limiter, _rate_limit_exceeded_handler
        from slowapi.util import get_remote_address
        from slowapi.errors import RateLimitExceeded
        limiter = Limiter(key_func=get_remote_address, default_limits=[])
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

        # Wrap relevant routes after include_router via a middleware that
        # checks per-IP counts on /auth/* paths.
        @app.middleware("http")
        async def _ratelimit_auth_paths(request: Request, call_next):
            path = request.url.path
            if path in ("/api/v1/auth/login", "/api/v1/auth/register",
                        "/api/v1/auth/forgot", "/api/v1/auth/reset"):
                key = get_remote_address(request) + ":" + path
                # 10 hits / minute / IP / endpoint
                cache = app.state.__dict__.setdefault("_rl_cache", {})
                import time
                now = time.time()
                bucket = cache.setdefault(key, [])
                bucket[:] = [t for t in bucket if now - t < 60]
                if len(bucket) >= 10:
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "Too many requests. Try again in a minute."},
                    )
                bucket.append(now)
            return await call_next(request)
    except ImportError:
        logger.info("slowapi not installed — rate limiting disabled")


def get_app() -> FastAPI:
    app = FastAPI(title="Deterministic Coaching Engine", lifespan=lifespan)

    cors = get_settings().cors_allowed_origins
    origins = ["*"] if cors.strip() == "*" else [o.strip() for o in cors.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["*"],
        allow_headers=["*"],
        # allow_credentials must stay False while allow_origins is wildcard.
        # If you switch to an explicit origin list and want to send cookies
        # cross-origin, flip this to True.
        allow_credentials=False,
    )

    @app.get("/")
    def read_root():
        return {"status": "healthy", "service": "coaching-engine"}

    app.include_router(router)
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(plans_router, prefix="/api/v1")
    app.include_router(profile_router, prefix="/api/v1")
    app.include_router(checkin_router, prefix="/api/v1")
    app.include_router(progress_router, prefix="/api/v1")
    app.include_router(nutrition_router, prefix="/api/v1")
    app.include_router(coach_router, prefix="/api/v1")
    app.include_router(admin_router, prefix="/api/v1")
    app.include_router(sets_router, prefix="/api/v1")
    app.include_router(feedback_router, prefix="/api/v1")
    app.include_router(health_router)  # /healthz at root for ops monitors

    _install_rate_limiter(app)
    return app


app = get_app()
