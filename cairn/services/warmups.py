from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cairn.models import Instrument, WarmupInstrument, WarmupItem, WarmupTempo, WarmupType


def _with_instruments():
    return selectinload(WarmupItem.instruments)


async def list_warmups(db: AsyncSession) -> list[WarmupItem]:
    result = await db.execute(
        select(WarmupItem).options(_with_instruments()).order_by(WarmupItem.difficulty, WarmupItem.title)
    )
    return list(result.scalars().all())


async def get_warmup(db: AsyncSession, warmup_id: int) -> WarmupItem | None:
    result = await db.execute(select(WarmupItem).where(WarmupItem.id == warmup_id).options(_with_instruments()))
    return result.scalar_one_or_none()


async def create_warmup(
    db: AsyncSession,
    title: str,
    warmup_type: WarmupType,
    content: str,
    difficulty: int,
    instruments: list[Instrument],
    default_tempo: int | None = None,
) -> WarmupItem:
    warmup = WarmupItem(
        title=title,
        warmup_type=warmup_type,
        content=content,
        difficulty=difficulty,
        default_tempo=default_tempo,
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
    default_tempo: int | None = None,
) -> WarmupItem | None:
    warmup = await get_warmup(db, warmup_id)
    if warmup is None:
        return None
    warmup.title = title
    warmup.warmup_type = warmup_type
    warmup.content = content
    warmup.difficulty = difficulty
    warmup.default_tempo = default_tempo
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


async def get_warmup_tempo(db: AsyncSession, user_id: int, warmup_id: int) -> int | None:
    result = await db.execute(
        select(WarmupTempo.tempo).where(
            WarmupTempo.user_id == user_id,
            WarmupTempo.warmup_id == warmup_id,
        )
    )
    return result.scalar_one_or_none()


async def upsert_warmup_tempo(db: AsyncSession, user_id: int, warmup_id: int, tempo: int) -> None:
    stmt = (
        sqlite_insert(WarmupTempo)
        .values(user_id=user_id, warmup_id=warmup_id, tempo=tempo)
        .on_conflict_do_update(
            index_elements=["user_id", "warmup_id"],
            set_={"tempo": tempo},
        )
    )
    await db.execute(stmt)
    await db.commit()
