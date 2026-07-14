from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cairn.models import Tune, TuneBox, TuneBoxSetDifficulty, TuneBoxSetEntry, TuneSet, TuneSetMember, TuneSetTempo


def _deep_load():
    return [
        selectinload(TuneSet.members).selectinload(TuneSetMember.tune).selectinload(Tune.settings),
        selectinload(TuneSet.members).selectinload(TuneSetMember.tune).selectinload(Tune.aliases),
        selectinload(TuneSet.members).selectinload(TuneSetMember.setting),
    ]


async def create_set(
    db: AsyncSession,
    title: str,
    description: str | None = None,
    source: str | None = None,
    abc_header: str | None = None,
    flow_difficulty: int | None = None,
    flow_difficulty_notes: str | None = None,
) -> TuneSet:
    tune_set = TuneSet(
        title=title.strip(),
        description=description,
        source=source,
        abc_header=abc_header,
        flow_difficulty=flow_difficulty,
        flow_difficulty_notes=flow_difficulty_notes,
    )
    db.add(tune_set)
    await db.commit()
    await db.refresh(tune_set)
    return tune_set


async def get_set(db: AsyncSession, set_id: int) -> TuneSet | None:
    result = await db.execute(select(TuneSet).where(TuneSet.id == set_id).options(*_deep_load()))
    return result.scalar_one_or_none()


async def list_sets(db: AsyncSession) -> list[TuneSet]:
    result = await db.execute(select(TuneSet).order_by(TuneSet.title).options(selectinload(TuneSet.members)))
    return list(result.scalars().all())


async def list_sets_for_tune(db: AsyncSession, tune_id: int) -> list[TuneSet]:
    result = await db.execute(
        select(TuneSet)
        .join(TuneSetMember, TuneSetMember.set_id == TuneSet.id)
        .where(TuneSetMember.tune_id == tune_id)
        .order_by(TuneSet.title)
    )
    return list(result.scalars().all())


async def update_set(
    db: AsyncSession,
    set_id: int,
    title: str,
    description: str | None = None,
    source: str | None = None,
    abc_header: str | None = None,
    flow_difficulty: int | None = None,
    flow_difficulty_notes: str | None = None,
) -> TuneSet | None:
    tune_set = await db.get(TuneSet, set_id)
    if tune_set is None:
        return None
    tune_set.title = title.strip()
    tune_set.description = description
    tune_set.source = source
    tune_set.abc_header = abc_header
    tune_set.flow_difficulty = flow_difficulty
    tune_set.flow_difficulty_notes = flow_difficulty_notes
    await db.commit()
    await db.refresh(tune_set)
    return tune_set


async def delete_set(db: AsyncSession, set_id: int) -> bool:
    tune_set = await db.get(TuneSet, set_id)
    if tune_set is None:
        return False
    await db.delete(tune_set)
    await db.commit()
    return True


async def set_members(
    db: AsyncSession,
    set_id: int,
    member_data: list[dict],
) -> TuneSet | None:
    tune_set = await db.get(TuneSet, set_id)
    if tune_set is None:
        return None
    await db.execute(delete(TuneSetMember).where(TuneSetMember.set_id == set_id))
    # Expire all session objects so the identity map doesn't serve stale members
    # when get_set re-fetches via selectinload below.
    db.expire_all()
    for order, item in enumerate(member_data):
        db.add(
            TuneSetMember(
                set_id=set_id,
                tune_id=item["tune_id"],
                setting_id=item.get("setting_id"),
                order=order,
            )
        )
    await db.commit()
    return await get_set(db, set_id)


async def get_set_tempo(db: AsyncSession, user_id: int, box_id: int, set_id: int) -> int | None:
    result = await db.execute(
        select(TuneSetTempo.tempo).where(
            TuneSetTempo.user_id == user_id,
            TuneSetTempo.box_id == box_id,
            TuneSetTempo.set_id == set_id,
        )
    )
    return result.scalar_one_or_none()


async def upsert_set_tempo(db: AsyncSession, user_id: int, box_id: int, set_id: int, tempo: int) -> None:
    stmt = (
        sqlite_insert(TuneSetTempo)
        .values(user_id=user_id, box_id=box_id, set_id=set_id, tempo=tempo)
        .on_conflict_do_update(
            index_elements=["user_id", "box_id", "set_id"],
            set_={"tempo": tempo},
        )
    )
    await db.execute(stmt)
    await db.commit()


async def add_box_set(db: AsyncSession, box_id: int, set_id: int) -> TuneBoxSetEntry:
    entry = TuneBoxSetEntry(box_id=box_id, set_id=set_id)
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


async def remove_box_set(db: AsyncSession, box_id: int, set_id: int) -> bool:
    result = await db.execute(
        select(TuneBoxSetEntry).where(
            TuneBoxSetEntry.box_id == box_id,
            TuneBoxSetEntry.set_id == set_id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        return False
    await db.delete(entry)
    await db.commit()
    return True


async def list_box_sets(db: AsyncSession, box_id: int) -> list[TuneBoxSetEntry]:
    result = await db.execute(
        select(TuneBoxSetEntry)
        .where(TuneBoxSetEntry.box_id == box_id)
        .options(
            selectinload(TuneBoxSetEntry.tune_set)
            .selectinload(TuneSet.members)
            .selectinload(TuneSetMember.tune)
            .selectinload(Tune.difficulties)
        )
        .join(TuneSet, TuneBoxSetEntry.set_id == TuneSet.id)
        .order_by(TuneSet.title)
    )
    return list(result.scalars().all())


def compute_default_set_difficulty(box: TuneBox, tune_set: TuneSet) -> int | None:
    """The hardest TuneDifficulty rating among the set's member tunes, for the box's own instrument(s).

    Ignores member tunes with no rating for any instrument the box supports.
    Returns None if no member has a relevant rating at all.
    """
    box_instruments = {bi.instrument for bi in box.instruments}
    ratings = [
        d.difficulty for member in tune_set.members for d in member.tune.difficulties if d.instrument in box_instruments
    ]
    return max(ratings) if ratings else None


async def get_set_difficulty_override(db: AsyncSession, box_id: int, set_id: int) -> int | None:
    result = await db.execute(
        select(TuneBoxSetDifficulty.difficulty).where(
            TuneBoxSetDifficulty.box_id == box_id,
            TuneBoxSetDifficulty.set_id == set_id,
        )
    )
    return result.scalar_one_or_none()


async def set_box_set_difficulty(db: AsyncSession, box_id: int, set_id: int, difficulty: int) -> None:
    stmt = (
        sqlite_insert(TuneBoxSetDifficulty)
        .values(box_id=box_id, set_id=set_id, difficulty=difficulty)
        .on_conflict_do_update(
            index_elements=["box_id", "set_id"],
            set_={"difficulty": difficulty},
        )
    )
    await db.execute(stmt)
    await db.commit()


async def clear_box_set_difficulty(db: AsyncSession, box_id: int, set_id: int) -> bool:
    result = await db.execute(
        select(TuneBoxSetDifficulty).where(
            TuneBoxSetDifficulty.box_id == box_id,
            TuneBoxSetDifficulty.set_id == set_id,
        )
    )
    override = result.scalar_one_or_none()
    if override is None:
        return False
    await db.delete(override)
    await db.commit()
    return True
