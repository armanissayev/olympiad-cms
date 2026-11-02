import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def database_url() -> str:
    return os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://olympiad:olympiad@127.0.0.1:5432/olympiad"
    )


def make_engine(url: str | None = None):
    return create_engine(url or database_url(), pool_pre_ping=True)


def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)
