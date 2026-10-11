"""
Defines and connects the database.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from models import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./users.db")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

if __name__ == "__main__":
    Base.metadata.create_all(engine)
