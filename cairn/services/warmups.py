from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import Instrument, WarmupItem, WarmupType


async def list_warmups(db: AsyncSession) -> list[WarmupItem]:
    result = await db.execute(select(WarmupItem).order_by(WarmupItem.difficulty, WarmupItem.title))
    return list(result.scalars().all())


async def get_warmup(db: AsyncSession, warmup_id: int) -> WarmupItem | None:
    return await db.get(WarmupItem, warmup_id)


async def create_warmup(
    db: AsyncSession,
    title: str,
    warmup_type: WarmupType,
    content: str,
    difficulty: int,
    instrument: Instrument | None,
) -> WarmupItem:
    warmup = WarmupItem(
        title=title,
        warmup_type=warmup_type,
        content=content,
        difficulty=difficulty,
        instrument=instrument,
    )
    db.add(warmup)
    await db.commit()
    await db.refresh(warmup)
    return warmup


async def update_warmup(
    db: AsyncSession,
    warmup_id: int,
    title: str,
    warmup_type: WarmupType,
    content: str,
    difficulty: int,
    instrument: Instrument | None,
) -> WarmupItem | None:
    warmup = await db.get(WarmupItem, warmup_id)
    if warmup is None:
        return None
    warmup.title = title
    warmup.warmup_type = warmup_type
    warmup.content = content
    warmup.difficulty = difficulty
    warmup.instrument = instrument
    await db.commit()
    await db.refresh(warmup)
    return warmup


async def delete_warmup(db: AsyncSession, warmup_id: int) -> bool:
    warmup = await db.get(WarmupItem, warmup_id)
    if warmup is None:
        return False
    await db.delete(warmup)
    await db.commit()
    return True
