from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import KeyMode, KeyRoot, TuneType
from cairn.schemas import TuneCreate
from cairn.services.tunes import add_alias, create_tune, get_tune, remove_alias

_ABC = "|:DEFA BAFA|DEFA BAFA:|"


async def _tune(db: AsyncSession, title: str = "The Morning Dew") -> object:
    return await create_tune(
        db,
        TuneCreate(
            title=title,
            tune_type=TuneType.reel,
            key_root=KeyRoot.D,
            key_mode=KeyMode.major,
            time_signature="4/4",
        ),
        abc_notation=_ABC,
    )


async def test_add_alias_creates_record(db: AsyncSession) -> None:
    t = await _tune(db)
    alias = await add_alias(db, t.id, "Rosie Anderson")
    assert alias is not None
    assert alias.id is not None
    assert alias.tune_id == t.id
    assert alias.name == "Rosie Anderson"
    assert alias.notes is None


async def test_add_alias_with_notes(db: AsyncSession) -> None:
    t = await _tune(db)
    alias = await add_alias(db, t.id, "Rosie Anderson", notes="Known in Clare")
    assert alias.notes == "Known in Clare"


async def test_add_alias_strips_whitespace(db: AsyncSession) -> None:
    t = await _tune(db)
    alias = await add_alias(db, t.id, "  Rosie Anderson  ")
    assert alias.name == "Rosie Anderson"


async def test_add_alias_returns_none_for_unknown_tune(db: AsyncSession) -> None:
    result = await add_alias(db, 9999, "Ghost")
    assert result is None


async def test_add_multiple_aliases(db: AsyncSession) -> None:
    t = await _tune(db)
    await add_alias(db, t.id, "Rosie Anderson")
    await add_alias(db, t.id, "Morning Dew")
    loaded = await get_tune(db, t.id)
    assert len(loaded.aliases) == 2


async def test_aliases_ordered_by_name(db: AsyncSession) -> None:
    t = await _tune(db)
    await add_alias(db, t.id, "Zebra Tune")
    await add_alias(db, t.id, "Apple Tune")
    loaded = await get_tune(db, t.id)
    names = [a.name for a in loaded.aliases]
    assert names == ["Apple Tune", "Zebra Tune"]


async def test_aliases_ordering_ignores_articles(db: AsyncSession) -> None:
    t = await _tune(db)
    await add_alias(db, t.id, "The Morning Star")
    await add_alias(db, t.id, "A Wandering Tune")
    await add_alias(db, t.id, "Banks of the Lee")
    loaded = await get_tune(db, t.id)
    names = [a.name for a in loaded.aliases]
    # sorts as: "Banks…", "Morning Star" (strip "The "), "Wandering…" (strip "A ")
    assert names == ["Banks of the Lee", "The Morning Star", "A Wandering Tune"]


async def test_remove_alias_returns_true_and_deletes(db: AsyncSession) -> None:
    t = await _tune(db)
    alias = await add_alias(db, t.id, "Rosie Anderson")
    result = await remove_alias(db, alias.id)
    assert result is True
    loaded = await get_tune(db, t.id)
    assert loaded.aliases == []


async def test_remove_alias_returns_false_for_unknown(db: AsyncSession) -> None:
    result = await remove_alias(db, 9999)
    assert result is False


async def test_get_tune_eager_loads_aliases(db: AsyncSession) -> None:
    t = await _tune(db)
    await add_alias(db, t.id, "Rosie Anderson")
    loaded = await get_tune(db, t.id)
    assert len(loaded.aliases) == 1
    assert loaded.aliases[0].name == "Rosie Anderson"
