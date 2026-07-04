from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cairn.models import Instrument, Tune, TuneBox, TuneBoxEntry, TuneBoxInstrument, TuneSetting


async def create_box(
    db: AsyncSession,
    user_id: int,
    name: str,
    instruments: list[Instrument],
) -> TuneBox:
    if not instruments:
        raise ValueError("A TuneBox must have at least one instrument.")
    box = TuneBox(user_id=user_id, name=name)
    db.add(box)
    await db.flush()
    for instrument in instruments:
        db.add(TuneBoxInstrument(box_id=box.id, instrument=instrument))
    await db.commit()
    await db.refresh(box)
    return box


async def add_tune(
    db: AsyncSession,
    box_id: int,
    tune_id: int,
) -> TuneBoxEntry:
    instruments_result = await db.execute(select(TuneBoxInstrument).where(TuneBoxInstrument.box_id == box_id))
    box_instruments = {row.instrument for row in instruments_result.scalars().all()}

    settings_result = await db.execute(
        select(TuneSetting).where(
            TuneSetting.tune_id == tune_id,
            TuneSetting.instrument.in_(box_instruments),
        )
    )
    matching = settings_result.scalars().all()
    setting_id = matching[0].id if len(matching) == 1 else None

    entry = TuneBoxEntry(box_id=box_id, tune_id=tune_id, setting_id=setting_id)
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


async def set_preferred_setting(
    db: AsyncSession,
    box_id: int,
    tune_id: int,
    setting_id: int | None,
) -> TuneBoxEntry:
    result = await db.execute(
        select(TuneBoxEntry).where(
            TuneBoxEntry.box_id == box_id,
            TuneBoxEntry.tune_id == tune_id,
        )
    )
    entry = result.scalar_one()
    entry.setting_id = setting_id
    await db.commit()
    await db.refresh(entry)
    return entry


async def remove_tune(
    db: AsyncSession,
    box_id: int,
    tune_id: int,
) -> bool:
    result = await db.execute(
        select(TuneBoxEntry).where(
            TuneBoxEntry.box_id == box_id,
            TuneBoxEntry.tune_id == tune_id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        return False
    await db.delete(entry)
    await db.commit()
    return True


async def list_boxes(
    db: AsyncSession,
    user_id: int,
) -> list[TuneBox]:
    result = await db.execute(
        select(TuneBox)
        .where(TuneBox.user_id == user_id)
        .order_by(TuneBox.name)
        .options(
            selectinload(TuneBox.instruments),
            selectinload(TuneBox.entries).selectinload(TuneBoxEntry.setting),
        )
    )
    return list(result.scalars().all())


async def get_box(
    db: AsyncSession,
    box_id: int,
) -> TuneBox | None:
    return await db.get(TuneBox, box_id)


async def get_box_detail(
    db: AsyncSession,
    box_id: int,
) -> TuneBox | None:
    result = await db.execute(
        select(TuneBox)
        .where(TuneBox.id == box_id)
        .options(
            selectinload(TuneBox.instruments),
            selectinload(TuneBox.entries).selectinload(TuneBoxEntry.tune).selectinload(Tune.settings),
            selectinload(TuneBox.entries).selectinload(TuneBoxEntry.setting),
        )
    )
    return result.scalar_one_or_none()


async def get_box_entry(
    db: AsyncSession,
    box_id: int,
    tune_id: int,
) -> TuneBoxEntry | None:
    result = await db.execute(
        select(TuneBoxEntry)
        .where(TuneBoxEntry.box_id == box_id, TuneBoxEntry.tune_id == tune_id)
        .options(
            selectinload(TuneBoxEntry.tune).selectinload(Tune.settings),
            selectinload(TuneBoxEntry.setting),
        )
    )
    return result.scalar_one_or_none()
