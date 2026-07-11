import logging
from datetime import date

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cairn.models import KeyRoot, PracticeList, PracticeListType, ProgressStatus, Tune, TuneListEntry

logger = logging.getLogger(__name__)


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
    display_alias_id: int | None = None,
) -> TuneListEntry | None:
    if await db.get(PracticeList, list_id) is None:
        return None
    entry = TuneListEntry(list_id=list_id, tune_id=tune_id, setting_id=setting_id, display_alias_id=display_alias_id)
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


async def delete_list(db: AsyncSession, list_id: int) -> bool:
    practice_list = await db.get(PracticeList, list_id)
    if practice_list is None:
        return False
    await db.delete(practice_list)
    await db.commit()
    return True


async def update_list(
    db: AsyncSession,
    list_id: int,
    name: str,
    list_type: PracticeListType,
    progress_goal: ProgressStatus,
    target_date: date | None,
) -> PracticeList | None:
    practice_list = await db.get(PracticeList, list_id)
    if practice_list is None:
        return None
    practice_list.name = name.strip()
    practice_list.list_type = list_type
    practice_list.progress_goal = progress_goal
    practice_list.target_date = target_date
    db.add(practice_list)
    await db.commit()
    await db.refresh(practice_list)
    return practice_list


async def get_list(db: AsyncSession, list_id: int) -> PracticeList | None:
    stmt = (
        select(PracticeList)
        .where(PracticeList.id == list_id)
        .options(
            selectinload(PracticeList.entries).selectinload(TuneListEntry.tune).selectinload(Tune.settings),
            selectinload(PracticeList.entries).selectinload(TuneListEntry.tune).selectinload(Tune.aliases),
            selectinload(PracticeList.entries).selectinload(TuneListEntry.setting),
            selectinload(PracticeList.entries).selectinload(TuneListEntry.display_alias),
            selectinload(PracticeList.box),
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_lists(db: AsyncSession, user_id: int) -> list[PracticeList]:
    stmt = (
        select(PracticeList)
        .where(PracticeList.user_id == user_id)
        .options(
            selectinload(PracticeList.entries).selectinload(TuneListEntry.tune),
            selectinload(PracticeList.box),
        )
        .order_by(PracticeList.name)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_list_entry(db: AsyncSession, list_id: int, tune_id: int) -> TuneListEntry | None:
    stmt = (
        select(TuneListEntry)
        .where(TuneListEntry.list_id == list_id, TuneListEntry.tune_id == tune_id)
        .options(
            selectinload(TuneListEntry.tune).selectinload(Tune.settings),
            selectinload(TuneListEntry.tune).selectinload(Tune.aliases),
            selectinload(TuneListEntry.setting),
            selectinload(TuneListEntry.display_alias),
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_list_entry_setting(
    db: AsyncSession,
    list_id: int,
    tune_id: int,
    setting_id: int | None,
) -> TuneListEntry | None:
    result = await db.execute(
        select(TuneListEntry).where(TuneListEntry.list_id == list_id, TuneListEntry.tune_id == tune_id)
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        return None
    entry.setting_id = setting_id
    db.add(entry)
    await db.commit()
    return await get_list_entry(db, list_id, tune_id)


async def update_list_entry_display_alias(
    db: AsyncSession,
    list_id: int,
    tune_id: int,
    display_alias_id: int | None,
) -> TuneListEntry | None:
    result = await db.execute(
        select(TuneListEntry).where(TuneListEntry.list_id == list_id, TuneListEntry.tune_id == tune_id)
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        return None
    entry.display_alias_id = display_alias_id
    db.add(entry)
    await db.commit()
    return await get_list_entry(db, list_id, tune_id)


async def update_list_entry_transpose(
    db: AsyncSession,
    list_id: int,
    tune_id: int,
    key_root: KeyRoot | None,
    octave: int,
) -> TuneListEntry | None:
    result = await db.execute(
        select(TuneListEntry).where(TuneListEntry.list_id == list_id, TuneListEntry.tune_id == tune_id)
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        return None
    entry.transpose_key_root = key_root
    entry.transpose_octave = octave
    db.add(entry)
    await db.commit()
    return await get_list_entry(db, list_id, tune_id)


async def find_list_entries_by_setting(
    db: AsyncSession,
    tune_id: int,
    box_id: int,
    setting_id: int | None,
) -> list[TuneListEntry]:
    stmt = (
        select(TuneListEntry)
        .join(PracticeList, TuneListEntry.list_id == PracticeList.id)
        .where(
            TuneListEntry.tune_id == tune_id,
            TuneListEntry.setting_id == setting_id,
            PracticeList.box_id == box_id,
        )
        .options(selectinload(TuneListEntry.practice_list))
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def bulk_update_list_entry_setting(
    db: AsyncSession,
    tune_id: int,
    list_ids: list[int],
    setting_id: int | None,
) -> None:
    if not list_ids:
        return
    logger.debug("bulk update setting: tune=%s lists=%s setting_id=%r", tune_id, list_ids, setting_id)
    stmt = (
        update(TuneListEntry)
        .where(
            TuneListEntry.tune_id == tune_id,
            TuneListEntry.list_id.in_(list_ids),
        )
        .values(setting_id=setting_id)
        .execution_options(synchronize_session=False)
    )
    result = await db.execute(stmt)
    logger.debug("bulk update setting: %s row(s) affected", result.rowcount)
    await db.commit()


async def remove_tune_from_list(db: AsyncSession, list_id: int, tune_id: int) -> bool:
    stmt = select(TuneListEntry).where(TuneListEntry.list_id == list_id, TuneListEntry.tune_id == tune_id)
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()
    if entry is None:
        return False
    await db.delete(entry)
    await db.commit()
    return True
