from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import KeyMode, KeyRoot, TuneAlias, TuneSetting, TuneType
from cairn.models_thesession_tunes import TheSessionAlias, TheSessionSetting, TheSessionTunePopularity
from cairn.schemas import TuneCreate
from cairn.services.thesession_link import (
    apply_thesession_link,
    build_thesession_preview_abc,
    get_thesession_aliases,
    get_thesession_settings,
    raw_to_tune_type,
    search_thesession_tunes,
    tune_type_to_raw,
)
from cairn.services.tunes import create_tune

ABC = "X:1\nT:Test\nM:4/4\nK:D\n|:DEFG|ABcd:|\n"


def _tune_create(**kwargs) -> TuneCreate:
    defaults = dict(
        title="The Morning Dew",
        tune_type=TuneType.reel,
        key_root=KeyRoot.D,
        key_mode=KeyMode.major,
        time_signature="4/4",
    )
    return TuneCreate(**{**defaults, **kwargs})


def _ext_setting(**kwargs) -> TheSessionSetting:
    defaults = dict(
        setting_id=1,
        tune_id=100,
        name="Cooley's",
        tune_type_raw="reel",
        meter="4/4",
        mode_raw="Edorian",
        abc="|:D2 FA DFAd|",
        username="danninagh",
    )
    return TheSessionSetting(**{**defaults, **kwargs})


# ── type mapping ─────────────────────────────────────────────────────────────


def test_raw_to_tune_type_normal_case() -> None:
    assert raw_to_tune_type("reel") == TuneType.reel


def test_raw_to_tune_type_slip_jig_has_space() -> None:
    assert raw_to_tune_type("slip jig") == TuneType.slip_jig


def test_raw_to_tune_type_unknown_returns_none() -> None:
    assert raw_to_tune_type("air") is None


def test_tune_type_to_raw_round_trip() -> None:
    for tt in [TuneType.reel, TuneType.jig, TuneType.slip_jig, TuneType.mazurka, TuneType.three_two]:
        raw = tune_type_to_raw(tt)
        assert raw_to_tune_type(raw) == tt


# ── build_thesession_preview_abc ─────────────────────────────────────────────


def test_build_preview_abc_parses_mode() -> None:
    setting = _ext_setting(mode_raw="Edorian", meter="6/8")
    abc = build_thesession_preview_abc(setting)
    assert "K:Edor" in abc
    assert "M:6/8" in abc
    assert "|:D2 FA DFAd|" in abc


def test_build_preview_abc_falls_back_on_unparseable_mode() -> None:
    setting = _ext_setting(mode_raw="nonsense")
    abc = build_thesession_preview_abc(setting)
    assert "K:C" in abc


# ── search ───────────────────────────────────────────────────────────────────


async def _seed_search_data(db: AsyncSession) -> None:
    db.add_all(
        [
            _ext_setting(setting_id=1, tune_id=100, name="Cooley's", tune_type_raw="reel"),
            _ext_setting(setting_id=2, tune_id=101, name="The Kesh", tune_type_raw="jig"),
            _ext_setting(setting_id=3, tune_id=102, name="Drowsy Maggie", tune_type_raw="reel"),
            # two rows for tune_id=100 (a tune can have multiple settings) — search should dedupe
            _ext_setting(setting_id=4, tune_id=100, name="Cooley's", tune_type_raw="reel"),
        ]
    )
    db.add(TheSessionAlias(tune_id=101, alias="Kesh Jig, The", canonical_name="The Kesh"))
    await db.commit()


async def test_search_by_title(db: AsyncSession) -> None:
    await _seed_search_data(db)
    results = await search_thesession_tunes(db, q="cooley")
    assert [r.tune_id for r in results] == [100]


async def test_search_dedupes_by_tune_id(db: AsyncSession) -> None:
    await _seed_search_data(db)
    results = await search_thesession_tunes(db, q="cooley")
    assert len(results) == 1


async def test_search_matches_alias(db: AsyncSession) -> None:
    await _seed_search_data(db)
    results = await search_thesession_tunes(db, q="kesh jig")
    assert [r.tune_id for r in results] == [101]


async def test_search_filters_by_type(db: AsyncSession) -> None:
    await _seed_search_data(db)
    results = await search_thesession_tunes(db, tune_type=TuneType.jig)
    assert [r.tune_id for r in results] == [101]


async def test_search_filters_by_family(db: AsyncSession) -> None:
    await _seed_search_data(db)
    results = await search_thesession_tunes(db, family="reel_family")
    tune_ids = {r.tune_id for r in results}
    assert tune_ids == {100, 102}


async def test_search_no_query_orders_by_popularity_and_handles_setting_skew(db: AsyncSession) -> None:
    """A tune with many settings must not crowd other tunes out of the
    popularity-ordered browse view — regression test for an under-fill bug
    where a naive overfetch-and-dedupe under-counted distinct tunes whenever
    the front of the sort order was dominated by one heavily-set tune."""
    # tune_id=200 has 10 settings (like a heavily-arranged session staple).
    db.add_all([_ext_setting(setting_id=i, tune_id=200, name="Drowsy Maggie") for i in range(1, 11)])
    db.add_all(
        [
            _ext_setting(setting_id=20, tune_id=201, name="The Kesh"),
            _ext_setting(setting_id=21, tune_id=202, name="Cooley's"),
        ]
    )
    db.add_all(
        [
            TheSessionTunePopularity(tune_id=200, name="Drowsy Maggie", tunebooks=5000),
            TheSessionTunePopularity(tune_id=201, name="The Kesh", tunebooks=3000),
            TheSessionTunePopularity(tune_id=202, name="Cooley's", tunebooks=1000),
        ]
    )
    await db.commit()

    results = await search_thesession_tunes(db, limit=3)
    assert [r.tune_id for r in results] == [200, 201, 202]


async def test_search_no_query_falls_back_to_tunes_without_popularity_data(db: AsyncSession) -> None:
    """A tune absent from tune_popularity.csv (true for roughly half of real
    TheSession tunes) must still be reachable when browsing without a search
    term, not just when it happens to also be a popularity-table entry."""
    db.add(_ext_setting(setting_id=1, tune_id=300, name="Unranked Reel", tune_type_raw="reel"))
    await db.commit()

    results = await search_thesession_tunes(db, tune_type=TuneType.reel, limit=10)
    assert [r.tune_id for r in results] == [300]


# ── get_thesession_aliases / get_thesession_settings ─────────────────────────


async def test_get_thesession_aliases_scoped_to_tune(db: AsyncSession) -> None:
    db.add_all(
        [
            TheSessionAlias(tune_id=100, alias="A", canonical_name="Cooley's"),
            TheSessionAlias(tune_id=100, alias="B", canonical_name="Cooley's"),
            TheSessionAlias(tune_id=101, alias="C", canonical_name="Other"),
        ]
    )
    await db.commit()
    aliases = await get_thesession_aliases(db, 100)
    assert {a.alias for a in aliases} == {"A", "B"}


async def test_get_thesession_settings_scoped_to_tune(db: AsyncSession) -> None:
    db.add_all(
        [
            _ext_setting(setting_id=1, tune_id=100),
            _ext_setting(setting_id=2, tune_id=100),
            _ext_setting(setting_id=3, tune_id=999),
        ]
    )
    await db.commit()
    settings = await get_thesession_settings(db, 100)
    assert {s.setting_id for s in settings} == {1, 2}


# ── apply_thesession_link ────────────────────────────────────────────────────


async def test_apply_link_sets_tune_attribution(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    ext = _ext_setting(setting_id=477, tune_id=100, username="Josh Kane")
    db.add(ext)
    await db.commit()
    await db.refresh(ext)

    updated = await apply_thesession_link(db, tune.id, 100, [], [ext.id], ext.id)
    assert updated.thesession_tune_id == 100
    assert updated.thesession_username == "Josh Kane"


async def test_apply_link_never_overwrites_existing_core_setting(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    ext = _ext_setting(setting_id=477, tune_id=100)
    db.add(ext)
    await db.commit()
    await db.refresh(ext)

    await apply_thesession_link(db, tune.id, 100, [], [ext.id], ext.id)

    result = await db.execute(select(TuneSetting).where(TuneSetting.tune_id == tune.id))
    settings = result.scalars().all()
    core = next(s for s in settings if s.is_core)
    assert core.abc_notation == ABC
    non_core = [s for s in settings if not s.is_core]
    assert len(non_core) == 1
    assert non_core[0].thesession_setting_id == 477


async def test_apply_link_imported_setting_carries_thesession_ids(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    ext = _ext_setting(setting_id=477, tune_id=100, username="Josh Kane")
    db.add(ext)
    await db.commit()
    await db.refresh(ext)

    await apply_thesession_link(db, tune.id, 100, [], [ext.id], None)

    result = await db.execute(select(TuneSetting).where(TuneSetting.tune_id == tune.id, TuneSetting.is_core.is_(False)))
    imported = result.scalars().all()
    assert len(imported) == 1
    assert imported[0].thesession_setting_id == 477
    assert imported[0].thesession_username == "Josh Kane"
    assert imported[0].abc_notation == ext.abc


async def test_apply_link_deduplicates_aliases_case_insensitive(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    db.add(TuneAlias(tune_id=tune.id, name="cooley's", sort_name="cooley's"))
    await db.commit()

    ext_alias_dup = TheSessionAlias(tune_id=100, alias="Cooley's", canonical_name="Cooley's")
    ext_alias_new = TheSessionAlias(tune_id=100, alias="Drag Her Round the Road", canonical_name="Cooley's")
    db.add_all([ext_alias_dup, ext_alias_new])
    await db.commit()
    await db.refresh(ext_alias_dup)
    await db.refresh(ext_alias_new)

    await apply_thesession_link(db, tune.id, 100, [ext_alias_dup.id, ext_alias_new.id], [], None)

    result = await db.execute(select(TuneAlias).where(TuneAlias.tune_id == tune.id))
    names = {a.name for a in result.scalars().all()}
    assert names == {"cooley's", "Drag Her Round the Road"}


async def test_apply_link_no_settings_checked_still_sets_attribution(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    updated = await apply_thesession_link(db, tune.id, 100, [], [], None)
    assert updated.thesession_tune_id == 100
    assert updated.thesession_username is None


async def test_apply_link_unknown_tune_returns_none(db: AsyncSession) -> None:
    result = await apply_thesession_link(db, 999, 100, [], [], None)
    assert result is None


async def test_apply_link_populates_brand_new_tune_from_default(db: AsyncSession) -> None:
    """A tune with no core setting yet — not reachable via the wizard's sole
    entry point today, but the save logic must still handle it correctly."""
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    existing_core = (
        await db.execute(select(TuneSetting).where(TuneSetting.tune_id == tune.id, TuneSetting.is_core.is_(True)))
    ).scalar_one()
    await db.delete(existing_core)
    await db.commit()

    ext = _ext_setting(
        setting_id=477,
        tune_id=100,
        username="Josh Kane",
        tune_type_raw="jig",
        meter="6/8",
        mode_raw="Gmajor",
        abc="|:GAB c2A|",
    )
    db.add(ext)
    await db.commit()
    await db.refresh(ext)

    updated = await apply_thesession_link(db, tune.id, 100, [], [ext.id], ext.id)

    result = await db.execute(select(TuneSetting).where(TuneSetting.tune_id == tune.id))
    settings = result.scalars().all()
    assert len(settings) == 1
    new_core = settings[0]
    assert new_core.is_core is True
    assert new_core.thesession_setting_id == 477
    assert new_core.abc_notation == "|:GAB c2A|"
    assert updated.tune_type == TuneType.jig
    assert updated.time_signature == "6/8"
    assert updated.key_root == KeyRoot.G
    assert updated.key_mode == KeyMode.major
