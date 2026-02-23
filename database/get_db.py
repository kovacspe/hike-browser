from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base

DATABASE_URL = "sqlite+aiosqlite:///./itineraries.db"
# pre postgres:
# DATABASE_URL = "postgresql+asyncpg://user:password@localhost/itineraries"

engine = create_async_engine(
    DATABASE_URL,
    echo=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
)




async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session

