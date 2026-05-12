from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .model import Base

DATABASE_URL = "sqlite:///checker_db.db"

engine = create_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db():
    Base.metadata.create_all(bind=engine)
