"""
Defines and connects the database.
Your code → SQLAlchemy (ORM) → Psycopg (PostgreSQL Driver) → PostgreSQL server
"""

from sqlalchemy import create_engine, make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings

settings = get_settings()
# Check pooled connections before reuse and bound PostgreSQL connection/query waits.
connect_args = {}
pool_options = {}
if make_url(settings.database_url).get_backend_name() == "postgresql":
    connect_args = {"connect_timeout": 3, "options": "-c statement_timeout=3000"}
    pool_options = {"pool_timeout": 3}
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args=connect_args,
    **pool_options,
)
SessionLocal = sessionmaker(bind=engine)
