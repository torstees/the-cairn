from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cairn.models import PracticeList, PracticeListType, ProgressStatus, Tune, TuneListEntry


async def create_list(
    db: AsyncSession,
    user_id: int,
    box_id: int,
    name: str,
    list_type: PracticeListType,
    progress_goal: ProgressStatus = ProgressStatus.committed,
    target_date: date | None = None,
) -> PracticeList:
    practice_list = PracticeList(
        user_id=user_id,
        box_id=box_id,
        name=name.strip(),
        list_type=list_type,
        progress_goal=progress_goal,
        target_date=target_date,
    )
    db.add(practice_list)
    await db.commit()
    await db.refresh(practice_list)
    return practice_list


async def get_active_list(db: AsyncSession, user_id: int) -> PracticeList | None:
    stmt = (
        select(PracticeList)
        .where(PracticeList.user_id == user_id, PracticeList.is_active.is_(True))
        .options(selectinload(PracticeList.entries))
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def activate_list(db: AsyncSession, user_id: int, list_id: int) -> PracticeList | None:
    target = await db.get(PracticeList, list_id)
    if target is None or target.user_id != user_id:
        return None

    current = await get_active_list(db, user_id)
    if current is not None and current.id != list_id:
        current.is_active = False
        db.add(current)

    target.is_active = True
    db.add(target)
    await db.commit()
    await db.refresh(target)
    return target


async def deactivate_list(db: AsyncSession, user_id: int) -> None:
    current = await get_active_list(db, user_id)
    if current is not None:
        current.is_active = False
        db.add(current)
        await db.commit()


async def add_tune_to_list(
    db: AsyncSession,
    list_id: int,
    tune_id: int,
    setting_id: int | None = None,
) -> TuneListEntry | None:
    if await db.get(PracticeList, list_id) is None:
        return None
    entry = TuneListEntry(list_id=list_id, tune_id=tune_id, setting_id=setting_id)
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


async def get_list(db: AsyncSession, list_id: int) -> PracticeList | None:
    stmt = (
        select(PracticeList)
        .where(PracticeList.id == list_id)
        .options(selectinload(PracticeList.entries).selectinload(TuneListEntry.tune))
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_lists(db: AsyncSession, user_id: int) -> list[PracticeList]:
    stmt = (
        select(PracticeList)
        .where(PracticeList.user_id == user_id)
        .options(selectinload(PracticeList.entries).selectinload(TuneListEntry.tune))
        .order_by(PracticeList.name)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_list_entry(db: AsyncSession, list_id: int, tune_id: int) -> TuneListEntry | None:
    stmt = (
        select(TuneListEntry)
        .where(TuneListEntry.list_id == list_id, TuneListEntry.tune_id == tune_id)
        .options(selectinload(TuneListEntry.tune))
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def remove_tune_from_list(db: AsyncSession, list_id: int, tune_id: int) -> bool:
    stmt = select(TuneListEntry).where(
        TuneListEntry.list_id == list_id, TuneListEntry.tune_id == tune_id
    )
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()
    if entry is None:
        return False
    await db.delete(entry)
    await db.commit()
    return True
