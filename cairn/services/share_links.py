import secrets

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cairn.models import ShareLink, Tune, TuneSetting


async def create_share_link(
    db: AsyncSession,
    user_id: int,
    tune_id: int,
    setting_id: int | None = None,
) -> ShareLink:
    """Create a share link for a tune, or for one specific setting of it —
    exactly one of tune_id/setting_id is set on the row (see the model's
    check constraint), matching whichever the caller asked to share."""
    link = ShareLink(
        token=secrets.token_urlsafe(24),
        tune_id=tune_id if setting_id is None else None,
        setting_id=setting_id,
        created_by=user_id,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return link


async def get_share_link_by_token(db: AsyncSession, token: str) -> ShareLink | None:
    result = await db.execute(
        select(ShareLink)
        .where(ShareLink.token == token)
        .options(
            selectinload(ShareLink.tune).selectinload(Tune.settings),
            selectinload(ShareLink.setting).selectinload(TuneSetting.tune),
        )
    )
    return result.scalar_one_or_none()


async def list_share_links_for_tune(db: AsyncSession, tune_id: int, setting_ids: list[int]) -> list[ShareLink]:
    """Every share link pointing at this tune itself, or at any of its settings."""
    result = await db.execute(
        select(ShareLink).where(or_(ShareLink.tune_id == tune_id, ShareLink.setting_id.in_(setting_ids)))
    )
    return list(result.scalars().all())


async def revoke_share_link(db: AsyncSession, share_link_id: int, user_id: int) -> bool:
    link = await db.get(ShareLink, share_link_id)
    if link is None or link.created_by != user_id:
        return False
    await db.delete(link)
    await db.commit()
    return True
