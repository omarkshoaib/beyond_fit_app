from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, create_engine, SQLModel

from app.settings import get_settings
from app.container import Container
from app.routes import router
from app.api.auth import router as auth_router
from app.api.plans import router as plans_router
from app.api.profile import router as profile_router
from app.api.checkin import router as checkin_router
from app.api.progress import router as progress_router
from app.api.nutrition import router as nutrition_router


def _make_engine(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, echo=False, connect_args=connect_args)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = _make_engine(settings.database_url)
    SQLModel.metadata.create_all(engine)

    app.state.container = Container(
        settings=settings,
        session_factory=lambda: Session(engine),
    )
    yield


def get_app() -> FastAPI:
    app = FastAPI(title="Deterministic Coaching Engine", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
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
    return app


app = get_app()
