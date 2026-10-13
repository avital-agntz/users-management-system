"""
Defines and connects the database.
Your code → SQLAlchemy (ORM) → Psycopg (PostgreSQL Driver) → PostgreSQL server
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings

settings = get_settings()
engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine)
