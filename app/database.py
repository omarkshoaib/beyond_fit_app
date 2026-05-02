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

def create_db_and_tables():
    """Initializes tables based on SQLModel inheritance in models.py"""
    SQLModel.metadata.create_all(engine)
