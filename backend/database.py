from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal = None


def _make_async_url(url: str) -> str:
    if "sqlite+aiosqlite" in url:
        return url
    if url.startswith("sqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    if "postgresql+asyncpg" in url or "postgres+asyncpg" in url:
        return url
    return (
        url.replace("postgresql://", "postgresql+asyncpg://")
           .replace("postgres://", "postgresql+asyncpg://")
    )


def _engine_kwargs(url: str) -> dict:
    if "sqlite" in url:
        return {"echo": False}
    return {"echo": False, "pool_size": 5, "max_overflow": 10, "pool_pre_ping": True}


def init_engine(database_url: str):
    global _engine, _SessionLocal
    async_url = _make_async_url(database_url)
    _engine = create_async_engine(async_url, **_engine_kwargs(database_url))
    _SessionLocal = async_sessionmaker(_engine, expire_on_commit=False)


async def get_db():
    async with _SessionLocal() as session:
        yield session


async def create_tables():
    async with _engine.begin() as conn:
        from . import models  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)
