from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import Instrument, KeyMode, KeyRoot, OrnamentationLevel, TuneSetting, TuneType
from cairn.schemas import TuneCreate, TuneDifficultyCreate, TuneSettingCreate, TuneUpdate
from cairn.services.tunes import (
    TUNE_FAMILIES,
    add_alias,
    build_tune_previews,
    create_setting,
    create_tune,
    delete_tune,
    get_tune,
    list_tunes,
    preview_abc,
    resolve_display_context,
    set_core_setting,
    set_difficulty,
    sort_key,
    update_tune,
)

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


# ── create_tune ────────────────────────────────────────────────────────────────


async def test_create_tune_returns_tune_with_id(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    assert tune.id is not None
    assert tune.title == "The Morning Dew"


async def test_create_tune_creates_exactly_one_core_setting(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)

    result = await db.execute(select(TuneSetting).where(TuneSetting.tune_id == tune.id))
    settings = result.scalars().all()
    assert len(settings) == 1
    assert settings[0].is_core is True
    assert settings[0].abc_notation == ABC


async def test_create_tune_setting_label_default(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)

    result = await db.execute(select(TuneSetting).where(TuneSetting.tune_id == tune.id))
    setting = result.scalar_one()
    assert setting.label == "Standard"


async def test_create_tune_setting_label_custom(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC, setting_label="Clare style")

    result = await db.execute(select(TuneSetting).where(TuneSetting.tune_id == tune.id))
    setting = result.scalar_one()
    assert setting.label == "Clare style"


# ── get_tune ──────────────────────────────────────────────────────────────────


async def test_get_tune_returns_tune(db: AsyncSession) -> None:
    created = await create_tune(db, _tune_create(), abc_notation=ABC)
    found = await get_tune(db, created.id)
    assert found is not None
    assert found.id == created.id
    assert found.title == created.title


async def test_get_tune_loads_settings(db: AsyncSession) -> None:
    created = await create_tune(db, _tune_create(), abc_notation=ABC)
    found = await get_tune(db, created.id)
    assert found is not None
    assert len(found.settings) == 1
    assert found.settings[0].is_core is True


async def test_get_tune_returns_none_for_missing_id(db: AsyncSession) -> None:
    result = await get_tune(db, 99999)
    assert result is None


# ── list_tunes ────────────────────────────────────────────────────────────────


async def test_list_tunes_returns_all(db: AsyncSession) -> None:
    await create_tune(db, _tune_create(title="Banish Misfortune"), abc_notation=ABC)
    await create_tune(db, _tune_create(title="The Foxhunter"), abc_notation=ABC)
    tunes = await list_tunes(db)
    assert len(tunes) == 2


async def test_list_tunes_ordered_by_title(db: AsyncSession) -> None:
    await create_tune(db, _tune_create(title="The Foxhunter"), abc_notation=ABC)
    await create_tune(db, _tune_create(title="Banish Misfortune"), abc_notation=ABC)
    tunes = await list_tunes(db)
    assert tunes[0].title == "Banish Misfortune"
    assert tunes[1].title == "The Foxhunter"


async def test_list_tunes_article_sort_order(db: AsyncSession) -> None:
    await create_tune(db, _tune_create(title="The Foxhunter"), abc_notation=ABC)
    await create_tune(db, _tune_create(title="An Rogaire Dubh"), abc_notation=ABC)
    await create_tune(db, _tune_create(title="A Fig For A Kiss"), abc_notation=ABC)
    await create_tune(db, _tune_create(title="Banish Misfortune"), abc_notation=ABC)
    tunes = await list_tunes(db)
    titles = [t.title for t in tunes]
    assert titles == ["Banish Misfortune", "A Fig For A Kiss", "The Foxhunter", "An Rogaire Dubh"]


async def test_sort_key_strips_the(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(title="The Morning Dew"), abc_notation=ABC)
    assert tune.sort_title == "Morning Dew"


async def test_sort_key_strips_a(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(title="A Fig For A Kiss"), abc_notation=ABC)
    assert tune.sort_title == "Fig For A Kiss"


async def test_sort_key_strips_an(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(title="An Rogaire Dubh"), abc_notation=ABC)
    assert tune.sort_title == "Rogaire Dubh"


async def test_sort_key_no_article(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(title="Banish Misfortune"), abc_notation=ABC)
    assert tune.sort_title == "Banish Misfortune"


async def test_sort_key_title_update_refreshes_sort_title(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(title="Banish Misfortune"), abc_notation=ABC)
    updated = await update_tune(db, tune.id, TuneUpdate(title="The Morning Dew"))
    assert updated is not None
    assert updated.sort_title == "Morning Dew"


def test_sort_key_function_cases() -> None:
    assert sort_key("The Morning Dew") == "Morning Dew"
    assert sort_key("A Fig For A Kiss") == "Fig For A Kiss"
    assert sort_key("An Rogaire Dubh") == "Rogaire Dubh"
    assert sort_key("Banish Misfortune") == "Banish Misfortune"
    assert sort_key("the morning dew") == "morning dew"
    assert sort_key("THE FOXHUNTER") == "FOXHUNTER"
    assert sort_key("Anthology") == "Anthology"  # 'An' not followed by space


async def test_list_tunes_empty(db: AsyncSession) -> None:
    tunes = await list_tunes(db)
    assert tunes == []


async def test_list_tunes_filter_by_type(db: AsyncSession) -> None:
    await create_tune(db, _tune_create(title="The Morning Dew", tune_type=TuneType.reel), abc_notation=ABC)
    await create_tune(db, _tune_create(title="Banish Misfortune", tune_type=TuneType.jig), abc_notation=ABC)
    reels = await list_tunes(db, tune_type=TuneType.reel)
    assert len(reels) == 1
    assert reels[0].title == "The Morning Dew"


async def test_list_tunes_filter_by_family(db: AsyncSession) -> None:
    await create_tune(db, _tune_create(title="A Jig", tune_type=TuneType.jig), abc_notation=ABC)
    await create_tune(db, _tune_create(title="A Slip Jig", tune_type=TuneType.slip_jig), abc_notation=ABC)
    await create_tune(db, _tune_create(title="A Reel", tune_type=TuneType.reel), abc_notation=ABC)
    results = await list_tunes(db, family="jig_family")
    titles = {t.title for t in results}
    assert titles == {"A Jig", "A Slip Jig"}


async def test_list_tunes_unknown_family_returns_all(db: AsyncSession) -> None:
    await create_tune(db, _tune_create(title="A Reel", tune_type=TuneType.reel), abc_notation=ABC)
    results = await list_tunes(db, family="nonexistent")
    assert len(results) == 1  # unknown family → no WHERE clause → all tunes


async def test_tune_families_cover_all_tune_types(db: AsyncSession) -> None:
    all_covered = {t for types in TUNE_FAMILIES.values() for t in types}
    assert all_covered == set(TuneType)


# ── update_tune ───────────────────────────────────────────────────────────────


async def test_update_tune_changes_fields(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    updated = await update_tune(
        db, tune.id, TuneUpdate(title="Revised Title", key_root=KeyRoot.G, key_mode=KeyMode.major)
    )
    assert updated is not None
    assert updated.title == "Revised Title"
    assert updated.key_root == KeyRoot.G
    assert updated.key_mode == KeyMode.major
    assert updated.time_signature == "4/4"  # unchanged


async def test_update_tune_exclude_unset(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(region="Clare"), abc_notation=ABC)
    updated = await update_tune(db, tune.id, TuneUpdate(title="New Title"))
    assert updated is not None
    assert updated.region == "Clare"  # untouched field preserved


async def test_update_tune_returns_none_for_missing_id(db: AsyncSession) -> None:
    result = await update_tune(db, 99999, TuneUpdate(title="Ghost"))
    assert result is None


# ── delete_tune ───────────────────────────────────────────────────────────────


async def test_delete_tune_removes_tune(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    result = await delete_tune(db, tune.id)
    assert result is True
    assert await get_tune(db, tune.id) is None


async def test_delete_tune_cascades_to_settings(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    tune_id = tune.id
    await delete_tune(db, tune_id)

    result = await db.execute(select(TuneSetting).where(TuneSetting.tune_id == tune_id))
    assert result.scalars().all() == []


async def test_delete_tune_returns_false_for_missing_id(db: AsyncSession) -> None:
    result = await delete_tune(db, 99999)
    assert result is False


# ── create_setting ────────────────────────────────────────────────────────────


def _setting_create(tune_id: int, **kwargs) -> TuneSettingCreate:
    defaults = dict(
        tune_id=tune_id,
        label="Clare style",
        abc_notation="|:DEFG ABcd:|\n",
        ornamentation_level=OrnamentationLevel.none,
    )
    return TuneSettingCreate(**{**defaults, **kwargs})


async def test_create_setting_is_never_core(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    setting = await create_setting(db, tune.id, _setting_create(tune.id))
    assert setting is not None
    assert setting.is_core is False


async def test_create_setting_stores_fields(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    setting = await create_setting(
        db,
        tune.id,
        _setting_create(tune.id, label="Fiddle arrangement", instrument=Instrument.fiddle, source="Tommy Peoples"),
    )
    assert setting is not None
    assert setting.label == "Fiddle arrangement"
    assert setting.instrument == Instrument.fiddle
    assert setting.source == "Tommy Peoples"


async def test_create_setting_returns_none_for_missing_tune(db: AsyncSession) -> None:
    result = await create_setting(db, 99999, _setting_create(99999))
    assert result is None


async def test_create_setting_tune_now_has_two_settings(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    await create_setting(db, tune.id, _setting_create(tune.id))
    found = await get_tune(db, tune.id)
    assert found is not None
    assert len(found.settings) == 2


# ── set_core_setting ──────────────────────────────────────────────────────────


async def test_set_core_promotes_target(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    new_s = await create_setting(db, tune.id, _setting_create(tune.id))
    assert new_s is not None
    result = await set_core_setting(db, tune.id, new_s.id)
    assert result is not None
    assert result.is_core is True


async def test_set_core_demotes_old_core(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    loaded = await get_tune(db, tune.id)
    assert loaded is not None
    old_core_id = loaded.settings[0].id
    new_s = await create_setting(db, tune.id, _setting_create(tune.id))
    assert new_s is not None
    await set_core_setting(db, tune.id, new_s.id)
    old_core = await db.get(TuneSetting, old_core_id)
    assert old_core is not None
    assert old_core.is_core is False


async def test_set_core_exactly_one_core_after_swap(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    new_s = await create_setting(db, tune.id, _setting_create(tune.id))
    assert new_s is not None
    await set_core_setting(db, tune.id, new_s.id)
    result = await db.execute(select(TuneSetting).where(TuneSetting.tune_id == tune.id, TuneSetting.is_core.is_(True)))
    cores = result.scalars().all()
    assert len(cores) == 1
    assert cores[0].id == new_s.id


async def test_set_core_idempotent_when_already_core(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    loaded = await get_tune(db, tune.id)
    assert loaded is not None
    core_id = loaded.settings[0].id
    result = await set_core_setting(db, tune.id, core_id)
    assert result is not None
    assert result.is_core is True


async def test_set_core_returns_none_for_wrong_tune(db: AsyncSession) -> None:
    tune_a = await create_tune(db, _tune_create(title="A"), abc_notation=ABC)
    tune_b = await create_tune(db, _tune_create(title="B"), abc_notation=ABC)
    loaded_b = await get_tune(db, tune_b.id)
    assert loaded_b is not None
    setting_b_id = loaded_b.settings[0].id
    result = await set_core_setting(db, tune_a.id, setting_b_id)
    assert result is None


async def test_set_core_returns_none_for_missing_setting(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    result = await set_core_setting(db, tune.id, 99999)
    assert result is None


# ── set_difficulty ────────────────────────────────────────────────────────────


def _difficulty_create(tune_id: int, **kwargs) -> TuneDifficultyCreate:
    defaults = dict(tune_id=tune_id, instrument=Instrument.fiddle, difficulty=3)
    return TuneDifficultyCreate(**{**defaults, **kwargs})


async def test_set_difficulty_creates_rating(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    result = await set_difficulty(db, tune.id, _difficulty_create(tune.id))
    assert result is not None
    assert result.instrument == Instrument.fiddle
    assert result.difficulty == 3


async def test_set_difficulty_updates_existing(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    await set_difficulty(db, tune.id, _difficulty_create(tune.id, difficulty=2))
    result = await set_difficulty(db, tune.id, _difficulty_create(tune.id, difficulty=5))
    assert result is not None
    assert result.difficulty == 5
    found = await get_tune(db, tune.id)
    assert found is not None
    assert len(found.difficulties) == 1


async def test_set_difficulty_returns_none_for_missing_tune(db: AsyncSession) -> None:
    result = await set_difficulty(db, 99999, _difficulty_create(99999))
    assert result is None


async def test_set_difficulty_different_instruments_are_independent(db: AsyncSession) -> None:
    tune = await create_tune(db, _tune_create(), abc_notation=ABC)
    await set_difficulty(db, tune.id, _difficulty_create(tune.id, instrument=Instrument.fiddle, difficulty=3))
    await set_difficulty(db, tune.id, _difficulty_create(tune.id, instrument=Instrument.flute, difficulty=5))
    found = await get_tune(db, tune.id)
    assert found is not None
    assert len(found.difficulties) == 2
    by_instrument = {d.instrument: d.difficulty for d in found.difficulties}
    assert by_instrument[Instrument.fiddle] == 3
    assert by_instrument[Instrument.flute] == 5


# ── preview_abc / build_tune_previews ────────────────────────────────────────


async def test_preview_abc_returns_opening_bars(db: AsyncSession) -> None:
    created = await create_tune(db, _tune_create(), abc_notation="X:1\nT:x\nM:4/4\nK:D\n|:DEFG|ABcd|efga|bagf:|\n")
    tune = await get_tune(db, created.id)  # eager-loads .settings; core_setting() needs it loaded
    assert tune is not None
    preview = preview_abc(tune, n_bars=2)
    assert preview is not None
    assert preview.endswith("|:DEFG|ABcd|\n")
    assert "efga" not in preview


async def test_preview_abc_strips_tempo_header(db: AsyncSession) -> None:
    # build_abc() always injects a Q: tempo header (the tune's own, or a
    # type-based default) — issue #118: this must not leak into previews,
    # which are static and never reflect a tempo the user actually controls.
    created = await create_tune(db, _tune_create(), abc_notation=ABC)
    tune = await get_tune(db, created.id)
    assert tune is not None
    preview = preview_abc(tune)
    assert preview is not None
    assert "Q:" not in preview


async def test_preview_abc_prefers_given_setting_over_core(db: AsyncSession) -> None:
    created = await create_tune(db, _tune_create(), abc_notation=ABC)
    alt = await create_setting(
        db,
        created.id,
        TuneSettingCreate(tune_id=created.id, label="Alternate", abc_notation="X:1\nT:x\nK:D\n|:GABc|dcBA:|\n"),
    )
    assert alt is not None
    tune = await get_tune(db, created.id)
    assert tune is not None
    preview = preview_abc(tune, setting=alt)
    assert preview is not None
    assert "GABc" in preview


async def test_preview_abc_display_name_overrides_title(db: AsyncSession) -> None:
    created = await create_tune(db, _tune_create(), abc_notation=ABC)
    tune = await get_tune(db, created.id)
    assert tune is not None
    preview = preview_abc(tune, display_name="Sunrise Reel")
    assert preview is not None
    assert "T:Sunrise Reel" in preview
    assert "T:Test" not in preview


async def test_preview_abc_n_bars_none_returns_full_tune(db: AsyncSession) -> None:
    created = await create_tune(db, _tune_create(), abc_notation="X:1\nT:x\nM:4/4\nK:D\n|:DEFG|ABcd|efga|bagf:|\n")
    tune = await get_tune(db, created.id)
    assert tune is not None
    preview = preview_abc(tune, n_bars=None)
    assert preview is not None
    assert "bagf" in preview


async def test_preview_abc_notes_only_strips_decorative_headers(db: AsyncSession) -> None:
    created = await create_tune(db, _tune_create(composer="Ed Reavy", origin="Ireland"), abc_notation=ABC)
    tune = await get_tune(db, created.id)
    assert tune is not None
    preview = preview_abc(tune, notes_only=True)
    assert preview is not None
    assert "T:" not in preview
    assert "C:" not in preview
    assert "O:" not in preview
    assert "K:" in preview
    assert "M:" in preview


async def test_preview_abc_notes_only_strips_source_notes(db: AsyncSession) -> None:
    created = await create_tune(db, _tune_create(), abc_notation=ABC)
    alt = await create_setting(
        db,
        created.id,
        TuneSettingCreate(
            tune_id=created.id,
            label="Alternate",
            abc_notation="X:1\nT:x\nK:D\n|:GABc|dcBA:|\n",
            source_notes="as played by so-and-so",
        ),
    )
    assert alt is not None
    tune = await get_tune(db, created.id)
    assert tune is not None
    preview = preview_abc(tune, setting=alt, notes_only=True)
    assert preview is not None
    assert "Z:" not in preview


def test_preview_abc_returns_none_without_a_core_setting() -> None:
    from cairn.models import Tune

    tune = Tune(
        title="No Settings Yet",
        sort_title="No Settings Yet",
        tune_type=TuneType.reel,
        key_root=KeyRoot.D,
        key_mode=KeyMode.major,
        time_signature="4/4",
    )
    tune.settings = []
    assert preview_abc(tune) is None


async def test_build_tune_previews_maps_tune_id_to_abc(db: AsyncSession) -> None:
    created = await create_tune(db, _tune_create(), abc_notation=ABC)
    tune = await get_tune(db, created.id)
    assert tune is not None
    previews = build_tune_previews([tune])
    assert tune.id in previews
    preview = previews[tune.id]
    assert "Q:" not in preview.column
    assert "Q:" not in preview.popup
    # This fixture's tune is exactly 2 bars, so column == popup here; the
    # column-is-a-shorter-prefix behavior for longer tunes is covered by
    # tests/test_routers/test_tunes.py::test_tune_column_preview_is_shorter_than_popup_preview.
    assert len(preview.column) <= len(preview.popup)


# ── resolve_display_context ───────────────────────────────────────────────────


def _entry(setting_id=None, setting=None, display_alias_id=None, display_alias=None):
    from types import SimpleNamespace

    return SimpleNamespace(
        setting_id=setting_id, setting=setting, display_alias_id=display_alias_id, display_alias=display_alias
    )


async def test_resolve_display_context_no_overrides_falls_back_to_title(db: AsyncSession) -> None:
    created = await create_tune(db, _tune_create(), abc_notation=ABC)
    tune = await get_tune(db, created.id)
    setting, display_name = resolve_display_context(tune, None, None)
    assert display_name == tune.title
    assert setting is not None and setting.is_core


async def test_resolve_display_context_box_alias_used_when_no_list(db: AsyncSession) -> None:
    created = await create_tune(db, _tune_create(), abc_notation=ABC)
    alias = await add_alias(db, created.id, "Sunrise Reel")
    tune = await get_tune(db, created.id)
    box_entry = _entry(display_alias_id=alias.id, display_alias=alias)
    _, display_name = resolve_display_context(tune, box_entry, None)
    assert display_name == "Sunrise Reel"


async def test_resolve_display_context_list_alias_outranks_box_alias(db: AsyncSession) -> None:
    created = await create_tune(db, _tune_create(), abc_notation=ABC)
    box_alias = await add_alias(db, created.id, "Box Name")
    list_alias = await add_alias(db, created.id, "List Name")
    tune = await get_tune(db, created.id)
    box_entry = _entry(display_alias_id=box_alias.id, display_alias=box_alias)
    list_entry = _entry(display_alias_id=list_alias.id, display_alias=list_alias)
    _, display_name = resolve_display_context(tune, box_entry, list_entry)
    assert display_name == "List Name"


async def test_resolve_display_context_list_setting_outranks_box_setting(db: AsyncSession) -> None:
    created = await create_tune(db, _tune_create(), abc_notation=ABC)
    tune = await get_tune(db, created.id)
    box_setting = await create_setting(
        db, created.id, TuneSettingCreate(tune_id=created.id, label="Box", abc_notation=ABC)
    )
    list_setting = await create_setting(
        db, created.id, TuneSettingCreate(tune_id=created.id, label="List", abc_notation=ABC)
    )
    box_entry = _entry(setting_id=box_setting.id, setting=box_setting)
    list_entry = _entry(setting_id=list_setting.id, setting=list_setting)
    setting, _ = resolve_display_context(tune, box_entry, list_entry)
    assert setting.id == list_setting.id
