import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import Content, ContentType, ContentVisibility

logger = logging.getLogger(__name__)


async def upsert_content(
    db: AsyncSession,
    slug: str,
    title: str,
    content_type: ContentType,
    body: str,
    visibility: ContentVisibility = ContentVisibility.public,
    metadata: dict | None = None,
    created_by: int | None = None,
) -> Content:
    """Insert or update a Content record by slug."""
    result = await db.execute(select(Content).where(Content.slug == slug))
    content = result.scalar_one_or_none()
    if content is None:
        content = Content(slug=slug)
        db.add(content)

    content.title = title
    content.content_type = content_type
    content.body = body
    content.visibility = visibility
    content.metadata_ = metadata
    content.created_by = created_by

    await db.commit()
    await db.refresh(content)
    logger.info("content upserted", extra={"slug": slug, "content_type": content_type.value})
    return content


async def get_content(db: AsyncSession, slug: str) -> Content | None:
    result = await db.execute(select(Content).where(Content.slug == slug))
    return result.scalar_one_or_none()


async def list_content(db: AsyncSession, content_type: ContentType | None = None) -> list[Content]:
    stmt = select(Content).order_by(Content.title)
    if content_type is not None:
        stmt = stmt.where(Content.content_type == content_type)
    result = await db.execute(stmt)
    return list(result.scalars().all())
