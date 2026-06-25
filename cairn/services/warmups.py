from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cairn.models import Instrument, WarmupInstrument, WarmupItem, WarmupType


def _with_instruments():
    return selectinload(WarmupItem.instruments)


async def list_warmups(db: AsyncSession) -> list[WarmupItem]:
    result = await db.execute(
        select(WarmupItem)
        .options(_with_instruments())
        .order_by(WarmupItem.difficulty, WarmupItem.title)
    )
    return list(result.scalars().all())


async def get_warmup(db: AsyncSession, warmup_id: int) -> WarmupItem | None:
    result = await db.execute(
        select(WarmupItem)
        .where(WarmupItem.id == warmup_id)
        .options(_with_instruments())
    )
    return result.scalar_one_or_none()


async def create_warmup(
    db: AsyncSession,
    title: str,
    warmup_type: WarmupType,
    content: str,
    difficulty: int,
    instruments: list[Instrument],
) -> WarmupItem:
    warmup = WarmupItem(
        title=title,
        warmup_type=warmup_type,
        content=content,
        difficulty=difficulty,
        instruments=[WarmupInstrument(instrument=i) for i in instruments],
    )
    db.add(warmup)
    await db.commit()
    await db.refresh(warmup, ["instruments"])
    return warmup


async def update_warmup(
    db: AsyncSession,
    warmup_id: int,
    title: str,
    warmup_type: WarmupType,
    content: str,
    difficulty: int,
    instruments: list[Instrument],
) -> WarmupItem | None:
    warmup = await get_warmup(db, warmup_id)
    if warmup is None:
        return None
    warmup.title = title
    warmup.warmup_type = warmup_type
    warmup.content = content
    warmup.difficulty = difficulty
    warmup.instruments = [WarmupInstrument(warmup_id=warmup_id, instrument=i) for i in instruments]
    await db.commit()
    await db.refresh(warmup, ["instruments"])
    return warmup


async def delete_warmup(db: AsyncSession, warmup_id: int) -> bool:
    warmup = await get_warmup(db, warmup_id)
    if warmup is None:
        return False
    await db.delete(warmup)
    await db.commit()
    return True
