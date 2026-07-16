import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_current_user_optional, get_db
from cairn.models import ContentVisibility, User
from cairn.services.content import get_content, render_markdown
from cairn.services.enrollments import get_active_enrollment_partner_ids
from cairn.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pages", tags=["content"])


async def _visible_to(db: AsyncSession, content, user: User | None) -> bool:
    """Same visibility rule as Tune (#197): public to everyone including a
    guest (#225); enrolled/private require a real login and, for enrolled,
    an active enrollment with the page's creator."""
    if content.visibility == ContentVisibility.public:
        return True
    if user is None:
        return False
    if content.created_by == user.id:
        return True
    if content.visibility == ContentVisibility.enrolled:
        partner_ids = await get_active_enrollment_partner_ids(db, user.id)
        return content.created_by in partner_ids
    return False


@router.get("/{slug}")
async def content_page(
    request: Request,
    slug: str,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> Response:
    content = await get_content(db, slug)
    if content is None or not await _visible_to(db, content, user):
        raise HTTPException(status_code=404, detail="Page not found")

    rendered_body = render_markdown(content.body)
    return templates.TemplateResponse(
        request,
        "content/page.html",
        {"content": content, "rendered_body": rendered_body},
    )
