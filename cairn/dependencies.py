from collections.abc import AsyncGenerator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.database import AsyncSessionLocal
from cairn.models import User


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


class NotAuthenticatedError(Exception):
    """Raised by get_current_user; main.py's exception handler turns this into
    a redirect to /auth/login?next=... rather than a bare 401."""

    def __init__(self, next_path: str = "/") -> None:
        self.next_path = next_path


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if user_id is not None:
        user = await db.get(User, user_id)
        if user is not None:
            return user
    next_path = request.url.path
    if request.url.query:
        next_path += f"?{request.url.query}"
    raise NotAuthenticatedError(next_path=next_path)
