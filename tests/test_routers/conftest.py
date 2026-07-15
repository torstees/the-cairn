import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.requests import Request

from cairn.database import Base
from cairn.dependencies import get_current_user, get_db
from cairn.main import app
from cairn.models import Role, User

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(_TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def user(db: AsyncSession) -> User:
    u = User(username="tester", email="t@example.com", google_sub="google-sub-tester", role=Role.student)
    db.add(u)
    await db.flush()
    return u


@pytest_asyncio.fixture
async def client(db, user):
    user_id = user.id  # captured now, while fresh — some service calls (e.g.
    # set_members()'s db.expire_all()) expire every object in the session's
    # identity map, and re-fetching by id here mirrors what the real
    # get_current_user already does per-request in production anyway.

    async def _override_db():
        yield db

    async def _override_user(request: Request) -> User:
        # Mirrors the real get_current_user's request.state.user side effect
        # (templating.py's context processor reads it for base.html's nav).
        current_user = await db.get(User, user_id)
        request.state.user = current_user
        return current_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
