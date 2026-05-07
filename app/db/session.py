from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()

write_engine: AsyncEngine = create_async_engine(
    settings.database_write_url,
    pool_pre_ping=True,
)
read_engine: AsyncEngine = create_async_engine(
    settings.database_read_effective_url,
    pool_pre_ping=True,
)

WriteSessionMaker = async_sessionmaker(
    write_engine,
    expire_on_commit=False,
    autoflush=False,
)
ReadSessionMaker = async_sessionmaker(
    read_engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_write_session() -> AsyncIterator[AsyncSession]:
    async with WriteSessionMaker() as session:
        yield session


async def get_read_session() -> AsyncIterator[AsyncSession]:
    async with ReadSessionMaker() as session:
        yield session

