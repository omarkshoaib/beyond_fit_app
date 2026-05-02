from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlmodel import Session, create_engine, SQLModel

from app.settings import get_settings
from app.container import Container
from app.routes import router


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

    @app.get("/")
    def read_root():
        return {"status": "healthy", "service": "coaching-engine"}

    app.include_router(router)
    return app


app = get_app()
