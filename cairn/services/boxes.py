from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cairn.models import (
    Instrument,
    KeyRoot,
    Tune,
    TuneAlias,
    TuneBox,
    TuneBoxEntry,
    TuneBoxInstrument,
    TuneListEntry,
    TuneSetting,
)


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
    display_alias_id: int | None = None,
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

    entry = TuneBoxEntry(box_id=box_id, tune_id=tune_id, setting_id=setting_id, display_alias_id=display_alias_id)
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


async def set_display_alias(
    db: AsyncSession,
    box_id: int,
    tune_id: int,
    display_alias_id: int | None,
) -> TuneBoxEntry:
    result = await db.execute(
        select(TuneBoxEntry).where(
            TuneBoxEntry.box_id == box_id,
            TuneBoxEntry.tune_id == tune_id,
        )
    )
    entry = result.scalar_one()
    entry.display_alias_id = display_alias_id
    await db.commit()
    await db.refresh(entry)
    return entry


async def get_display_names_for_tunes(db: AsyncSession, box_id: int, tune_ids: set[int]) -> dict[int, str]:
    """Single query: tune_id -> display alias name, for entries in box_id that have one chosen (#119)."""
    if not tune_ids:
        return {}
    rows = await db.execute(
        select(TuneBoxEntry.tune_id, TuneAlias.name)
        .join(TuneAlias, TuneBoxEntry.display_alias_id == TuneAlias.id)
        .where(TuneBoxEntry.box_id == box_id, TuneBoxEntry.tune_id.in_(tune_ids))
    )
    return dict(rows.all())


async def set_transpose(
    db: AsyncSession,
    box_id: int,
    tune_id: int,
    key_root: KeyRoot | None,
    octave: int,
) -> TuneBoxEntry:
    result = await db.execute(
        select(TuneBoxEntry).where(
            TuneBoxEntry.box_id == box_id,
            TuneBoxEntry.tune_id == tune_id,
        )
    )
    entry = result.scalar_one()
    entry.transpose_key_root = key_root
    entry.transpose_octave = octave
    await db.commit()
    await db.refresh(entry)
    return entry


async def get_transposes_for_tunes(
    db: AsyncSession,
    box_id: int,
    tune_ids: set[int],
    list_id: int | None = None,
) -> dict[int, tuple[KeyRoot | None, int]]:
    """tune_id -> (transpose_key_root, transpose_octave) for entries with a transpose set (#158).

    Box entries are the base; when list_id is given, that list's own entries
    override the box's per tune, matching resolve_display_context()'s
    existing list-overrides-box precedence for setting/display_name.
    """
    if not tune_ids:
        return {}
    result: dict[int, tuple[KeyRoot | None, int]] = {}
    box_rows = await db.execute(
        select(TuneBoxEntry.tune_id, TuneBoxEntry.transpose_key_root, TuneBoxEntry.transpose_octave).where(
            TuneBoxEntry.box_id == box_id, TuneBoxEntry.tune_id.in_(tune_ids)
        )
    )
    for tune_id, key_root, octave in box_rows.all():
        if key_root is not None or octave:
            result[tune_id] = (key_root, octave)

    if list_id is not None:
        list_rows = await db.execute(
            select(TuneListEntry.tune_id, TuneListEntry.transpose_key_root, TuneListEntry.transpose_octave).where(
                TuneListEntry.list_id == list_id, TuneListEntry.tune_id.in_(tune_ids)
            )
        )
        for tune_id, key_root, octave in list_rows.all():
            if key_root is not None or octave:
                result[tune_id] = (key_root, octave)

    return result


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
            selectinload(TuneBox.entries).selectinload(TuneBoxEntry.display_alias),
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
            selectinload(TuneBox.entries).selectinload(TuneBoxEntry.tune).selectinload(Tune.aliases),
            selectinload(TuneBox.entries).selectinload(TuneBoxEntry.setting),
            selectinload(TuneBox.entries).selectinload(TuneBoxEntry.display_alias),
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
            selectinload(TuneBoxEntry.tune).selectinload(Tune.aliases),
            selectinload(TuneBoxEntry.setting),
            selectinload(TuneBoxEntry.display_alias),
        )
    )
    return result.scalar_one_or_none()
