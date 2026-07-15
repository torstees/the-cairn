import logging

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
from cairn.dependencies import get_db
from cairn.models import Role, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

oauth = OAuth()
oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


def _safe_next_path(next: str | None) -> str:
    # `next` round-trips through the client (query param -> session -> redirect
    # target) — restrict it to same-site relative paths so it can't be turned
    # into an open redirect (e.g. next=https://evil.example or next=//evil.example).
    if not next or not next.startswith("/") or next.startswith("//"):
        return "/"
    return next


@router.get("/login")
async def login(request: Request, next: str | None = None) -> RedirectResponse:
    request.session["next"] = _safe_next_path(next)
    redirect_uri = request.url_for("auth_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/callback", name="auth_callback")
async def callback(request: Request, db: AsyncSession = Depends(get_db)) -> RedirectResponse:
    token = await oauth.google.authorize_access_token(request)
    userinfo = token["userinfo"]
    google_sub = userinfo["sub"]

    user = await db.scalar(select(User).where(User.google_sub == google_sub))
    if user is None:
        user = await _provision_user(db, userinfo)

    request.session["user_id"] = user.id
    next_path = _safe_next_path(request.session.pop("next", None))
    return RedirectResponse(next_path)


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/auth/login", status_code=303)


async def _provision_user(db: AsyncSession, userinfo: dict) -> User:
    email = userinfo["email"]
    base_username = email.split("@")[0]
    username = base_username
    suffix = 1
    while await db.scalar(select(User).where(User.username == username)):
        suffix += 1
        username = f"{base_username}{suffix}"

    user = User(username=username, email=email, google_sub=userinfo["sub"], role=Role.student)
    db.add(user)
    await db.commit()
    logger.info("Auto-provisioned new user %s from Google login", username)
    return user
