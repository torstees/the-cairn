import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from cairn.dependencies import NotAuthenticatedError, get_current_user
from cairn.models import Role, User


def _request(session: dict, path: str = "/", query_string: bytes = b"") -> Request:
    scope = {
        "type": "http",
        "session": session,
        "headers": [],
        "query_string": query_string,
        "path": path,
        "method": "GET",
    }
    return Request(scope)


async def _seed_user(db: AsyncSession) -> User:
    u = User(username="alice", email="alice@example.com", google_sub="google-sub-alice", role=Role.student)
    db.add(u)
    await db.flush()
    return u


async def test_get_current_user_returns_user_from_session(db: AsyncSession) -> None:
    user = await _seed_user(db)
    request = _request({"user_id": user.id})
    result = await get_current_user(request, db)
    assert result.id == user.id


async def test_get_current_user_raises_when_session_empty(db: AsyncSession) -> None:
    request = _request({}, path="/tunes", query_string=b"page=2")
    with pytest.raises(NotAuthenticatedError) as exc_info:
        await get_current_user(request, db)
    assert exc_info.value.next_path == "/tunes?page=2"


async def test_get_current_user_raises_when_session_user_id_stale(db: AsyncSession) -> None:
    # e.g. the user row was deleted after the session cookie was issued.
    request = _request({"user_id": 999999})
    with pytest.raises(NotAuthenticatedError):
        await get_current_user(request, db)
