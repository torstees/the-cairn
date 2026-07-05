import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_db
from cairn.models import ContentVisibility
from cairn.services.content import get_content, render_markdown
from cairn.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pages", tags=["content"])

# Phase 1 has no auth, so only visibility levels that don't require it are servable.
_VISIBLE_WITHOUT_AUTH = {ContentVisibility.public, ContentVisibility.enrolled}


@router.get("/{slug}")
async def content_page(
    request: Request,
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    content = await get_content(db, slug)
    if content is None or content.visibility not in _VISIBLE_WITHOUT_AUTH:
        raise HTTPException(status_code=404, detail="Page not found")

    rendered_body = render_markdown(content.body)
    return templates.TemplateResponse(
        request,
        "content/page.html",
        {"content": content, "rendered_body": rendered_body},
    )
