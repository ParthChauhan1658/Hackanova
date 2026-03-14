"""
Async PostgreSQL connection using SQLAlchemy 2.0 + asyncpg.
"""

from __future__ import annotations

import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.constants import DATABASE_URL_DEFAULT, DATABASE_URL_ENV


class Base(DeclarativeBase):
    pass


DATABASE_URL: str = os.getenv(DATABASE_URL_ENV, DATABASE_URL_DEFAULT)

engine = create_async_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields an async DB session."""
    async with AsyncSessionLocal() as session:
        yield session


async def create_tables() -> None:
    """Called once at startup to create tables if they do not exist."""
    from app.db import models as _models  # noqa: F401 — ensure models are registered
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
