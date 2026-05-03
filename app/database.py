import os
from dotenv import load_dotenv
from sqlmodel import SQLModel, create_engine

load_dotenv()

# Automatically map to PostgreSQL if passed via .env, 
# otherwise default natively to SQLite in the root folder structure.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./beyond_fit.db")

# For SQLite, we must set check_same_thread=False
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)

# Ensure tables exist at import time (covers TestClient flows that don't
# trigger FastAPI lifespan and ad-hoc scripts that import app.database directly).
# Idempotent for production: lifespan re-runs create_all anyway.
import app.models  # noqa: F401  (ensure SQLModel metadata is populated)
SQLModel.metadata.create_all(engine)


def create_db_and_tables():
    """Initializes tables based on SQLModel inheritance in models.py"""
    SQLModel.metadata.create_all(engine)
