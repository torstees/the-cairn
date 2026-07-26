from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import (
    ContentVisibility,
    KeyMode,
    KeyRoot,
    PracticeList,
    PracticeListType,
    ProgressStatus,
    Recording,
    RecordingReference,
    Tune,
    TuneAlias,
    TuneBox,
    TuneBoxEntry,
    TuneListEntry,
    TuneSet,
    TuneSetMember,
    TuneSetting,
    TuneType,
    WarmupInstrument,
    WarmupItem,
)
from cairn.schemas import TuneCreate, TuneSettingCreate
from cairn.services.recordings import add_reference, create_recording
from cairn.services.tune_sets import (
    add_box_set,
    add_list_set,
    create_set,
    get_set_difficulty_override,
    list_box_sets,
    list_list_sets,
    set_box_set_difficulty,
    set_members,
)
from cairn.services.tunes import add_alias, create_setting, create_tune
from scripts.export_seed import export_boxes, export_lists, export_recordings, export_sets, export_tunes
from scripts.seed import seed_boxes, seed_lists, seed_recordings, seed_sets, seed_tunes, seed_warmups


async def _tune(db: AsyncSession, title: str = "The Morning Dew"):
    return await create_tune(
        db,
        TuneCreate(
            title=title,
            tune_type=TuneType.reel,
            key_root=KeyRoot.D,
            key_mode=KeyMode.major,
            time_signature="4/4",
        ),
        abc_notation="|:DEFA BAFA|DEFA BAFA:|\n",
    )


# ── seed_tunes ───────────────────────────────────────────────────────────────


def _tune_record(**overrides) -> dict:
    rec = {
        "title": "The Kesh",
        "tune_type": "reel",
        "key_root": "G",
        "key_mode": "major",
        "time_signature": "4/4",
        "settings": [{"label": "Standard", "abc_notation": "|:GABc dedB|dedB dedB:|\n", "is_core": True}],
    }
    rec.update(overrides)
    return rec


async def test_seed_tunes_creates_aliases(db: AsyncSession) -> None:
    rec = _tune_record(aliases=[{"name": "The Kesh Jig", "notes": "common misnomer"}, {"name": "An Ciseach"}])
    created, updated, errors = await seed_tunes(db, [rec])
    assert (created, updated, errors) == (1, 0, 0)

    tune = (await db.execute(select(Tune).where(Tune.title == "The Kesh"))).scalar_one()
    aliases = (await db.execute(select(TuneAlias).where(TuneAlias.tune_id == tune.id))).scalars().all()
    names = {a.name: a.notes for a in aliases}
    assert names == {"The Kesh Jig": "common misnomer", "An Ciseach": None}


async def test_seed_tunes_preserves_tune_visibility_and_thesession_fields(db: AsyncSession) -> None:
    rec = _tune_record(visibility="enrolled", thesession_tune_id=123, thesession_username="someuser")
    await seed_tunes(db, [rec])
    tune = (await db.execute(select(Tune).where(Tune.title == "The Kesh"))).scalar_one()
    assert tune.visibility == ContentVisibility.enrolled
    assert tune.thesession_tune_id == 123
    assert tune.thesession_username == "someuser"


async def test_seed_tunes_defaults_tune_visibility_when_absent(db: AsyncSession) -> None:
    await seed_tunes(db, [_tune_record()])
    tune = (await db.execute(select(Tune).where(Tune.title == "The Kesh"))).scalar_one()
    assert tune.visibility == ContentVisibility.public
    assert tune.thesession_tune_id is None


async def test_seed_tunes_preserves_setting_visibility_and_thesession_fields(db: AsyncSession) -> None:
    rec = _tune_record(
        settings=[
            {
                "label": "Standard",
                "abc_notation": "|:GABc dedB|dedB dedB:|\n",
                "is_core": True,
                "visibility": "enrolled",
                "thesession_setting_id": 456,
                "thesession_username": "coreuser",
            },
            {
                "label": "Alt",
                "abc_notation": "|:GABc dedB|dedB dedB:|\n",
                "is_core": False,
                "visibility": "enrolled",
                "thesession_setting_id": 789,
                "thesession_username": "altuser",
            },
        ]
    )
    await seed_tunes(db, [rec])
    tune = (await db.execute(select(Tune).where(Tune.title == "The Kesh"))).scalar_one()
    settings = {
        s.label: s for s in (await db.execute(select(TuneSetting).where(TuneSetting.tune_id == tune.id))).scalars()
    }
    assert settings["Standard"].visibility == ContentVisibility.enrolled
    assert settings["Standard"].thesession_setting_id == 456
    assert settings["Standard"].thesession_username == "coreuser"
    assert settings["Alt"].visibility == ContentVisibility.enrolled
    assert settings["Alt"].thesession_setting_id == 789
    assert settings["Alt"].thesession_username == "altuser"


async def test_seed_tunes_reconcile_adds_setting_and_alias(db: AsyncSession) -> None:
    await seed_tunes(db, [_tune_record(aliases=[{"name": "An Ciseach"}])])

    rec = _tune_record(
        settings=[
            {"label": "Standard", "abc_notation": "|:GABc dedB|dedB dedB:|\n", "is_core": True},
            {"label": "Alt", "abc_notation": "|:GABc dedB|dedB dedB:|\n", "is_core": False},
        ],
        aliases=[{"name": "An Ciseach"}, {"name": "The Kesh Jig"}],
    )
    created, updated, errors = await seed_tunes(db, [rec])
    assert (created, updated, errors) == (0, 1, 0)

    tune = (await db.execute(select(Tune).where(Tune.title == "The Kesh"))).scalar_one()
    labels = {s.label for s in (await db.execute(select(TuneSetting).where(TuneSetting.tune_id == tune.id))).scalars()}
    assert labels == {"Standard", "Alt"}
    names = {a.name for a in (await db.execute(select(TuneAlias).where(TuneAlias.tune_id == tune.id))).scalars()}
    assert names == {"An Ciseach", "The Kesh Jig"}


async def test_seed_tunes_reconcile_updates_changed_fields(db: AsyncSession) -> None:
    await seed_tunes(db, [_tune_record(composer="Unknown", visibility="public")])
    await seed_tunes(db, [_tune_record(composer="O'Carolan", visibility="enrolled")])

    tune = (await db.execute(select(Tune).where(Tune.title == "The Kesh"))).scalar_one()
    assert tune.composer == "O'Carolan"
    assert tune.visibility == ContentVisibility.enrolled


async def test_seed_tunes_reconcile_removes_setting_and_alias_no_longer_present(db: AsyncSession) -> None:
    rec = _tune_record(
        settings=[
            {"label": "Standard", "abc_notation": "|:GABc dedB|dedB dedB:|\n", "is_core": True},
            {"label": "Alt", "abc_notation": "|:GABc dedB|dedB dedB:|\n", "is_core": False},
        ],
        aliases=[{"name": "An Ciseach"}, {"name": "The Kesh Jig"}],
    )
    await seed_tunes(db, [rec])

    await seed_tunes(db, [_tune_record(aliases=[{"name": "An Ciseach"}])])

    tune = (await db.execute(select(Tune).where(Tune.title == "The Kesh"))).scalar_one()
    labels = {s.label for s in (await db.execute(select(TuneSetting).where(TuneSetting.tune_id == tune.id))).scalars()}
    assert labels == {"Standard"}
    names = {a.name for a in (await db.execute(select(TuneAlias).where(TuneAlias.tune_id == tune.id))).scalars()}
    assert names == {"An Ciseach"}


async def test_seed_tunes_reconcile_warns_instead_of_deleting_a_still_referenced_setting(db: AsyncSession) -> None:
    # sqlite here doesn't enforce FKs (no PRAGMA foreign_keys), so a stale
    # setting still pointed to by a box entry must be guarded explicitly
    # rather than relying on the DB to reject the delete.
    rec = _tune_record(
        settings=[
            {"label": "Standard", "abc_notation": "|:GABc dedB|dedB dedB:|\n", "is_core": True},
            {"label": "Alt", "abc_notation": "|:GABc dedB|dedB dedB:|\n", "is_core": False},
        ]
    )
    await seed_tunes(db, [rec])
    tune = (await db.execute(select(Tune).where(Tune.title == "The Kesh"))).scalar_one()
    alt_setting_id = (
        await db.execute(select(TuneSetting.id).where(TuneSetting.tune_id == tune.id, TuneSetting.label == "Alt"))
    ).scalar_one()
    box = TuneBox(user_id=1, name="Referencing Box")
    db.add(box)
    await db.flush()
    db.add(TuneBoxEntry(box_id=box.id, tune_id=tune.id, setting_id=alt_setting_id))
    await db.commit()

    created, updated, errors = await seed_tunes(db, [_tune_record()])  # drops "Alt" from settings
    assert (created, updated, errors) == (0, 1, 0)
    # the still-referenced setting must survive, not get silently deleted
    still_there = (
        await db.execute(select(TuneSetting.id).where(TuneSetting.id == alt_setting_id))
    ).scalar_one_or_none()
    assert still_there == alt_setting_id


# ── export_tunes ─────────────────────────────────────────────────────────────


async def test_export_tunes_includes_aliases(db: AsyncSession, tmp_path: Path) -> None:
    tune = await _tune(db, "The Abbey")
    await add_alias(db, tune.id, "Alt Name", notes="a note")

    await export_tunes(db, tmp_path)
    import json

    data = json.loads((tmp_path / "tunes.json").read_text())
    rec = next(r for r in data if r["title"] == "The Abbey")
    assert rec["aliases"] == [{"name": "Alt Name", "notes": "a note"}]


async def test_export_tunes_includes_visibility_and_thesession_fields(db: AsyncSession, tmp_path: Path) -> None:
    tune = await _tune(db, "The Abbey")
    # created_by=stub user so a non-public visibility doesn't drop it out of
    # list_tunes()'s own visibility filter (export_tunes queries as the stub
    # user, same as any other user would) -- not what's under test here.
    tune.created_by = 1
    tune.visibility = ContentVisibility.enrolled
    tune.thesession_tune_id = 42
    tune.thesession_username = "exportuser"
    await db.commit()
    core = (await db.execute(select(TuneSetting).where(TuneSetting.tune_id == tune.id))).scalar_one()
    core.visibility = ContentVisibility.enrolled
    core.thesession_setting_id = 99
    core.thesession_username = "settinguser"
    await db.commit()
    await create_setting(
        db,
        tune.id,
        TuneSettingCreate(
            tune_id=tune.id, label="Alt", abc_notation="|:DEFA BAFA:|\n", visibility=ContentVisibility.public
        ),
    )

    await export_tunes(db, tmp_path)
    import json

    data = json.loads((tmp_path / "tunes.json").read_text())
    rec = next(r for r in data if r["title"] == "The Abbey")
    assert rec["visibility"] == "enrolled"
    assert rec["thesession_tune_id"] == 42
    assert rec["thesession_username"] == "exportuser"
    settings = {s["label"]: s for s in rec["settings"]}
    assert settings["Standard"]["visibility"] == "enrolled"
    assert settings["Standard"]["thesession_setting_id"] == 99
    assert settings["Standard"]["thesession_username"] == "settinguser"
    assert settings["Alt"]["visibility"] == "public"
    assert settings["Alt"]["thesession_setting_id"] is None


# ── seed_warmups ─────────────────────────────────────────────────────────────


def _warmup_record(**overrides) -> dict:
    rec = {
        "title": "Long Tones",
        "warmup_type": "scale",
        "content": "Hold each note for 8 counts.",
        "difficulty": 1,
        "instruments": ["flute"],
    }
    rec.update(overrides)
    return rec


async def test_seed_warmups_creates_warmup(db: AsyncSession) -> None:
    created, updated, errors = await seed_warmups(db, [_warmup_record()])
    assert (created, updated, errors) == (1, 0, 0)
    warmup = (await db.execute(select(WarmupItem).where(WarmupItem.title == "Long Tones"))).scalar_one()
    assert warmup.difficulty == 1
    instruments = (
        (await db.execute(select(WarmupInstrument).where(WarmupInstrument.warmup_id == warmup.id))).scalars().all()
    )
    assert {i.instrument.value for i in instruments} == {"flute"}


async def test_seed_warmups_reconcile_updates_field_and_instruments(db: AsyncSession) -> None:
    await seed_warmups(db, [_warmup_record(difficulty=1, instruments=["flute"])])

    created, updated, errors = await seed_warmups(db, [_warmup_record(difficulty=3, instruments=["fiddle"])])
    assert (created, updated, errors) == (0, 1, 0)

    warmup = (await db.execute(select(WarmupItem).where(WarmupItem.title == "Long Tones"))).scalar_one()
    assert warmup.difficulty == 3
    instruments = (
        (await db.execute(select(WarmupInstrument).where(WarmupInstrument.warmup_id == warmup.id))).scalars().all()
    )
    assert {i.instrument.value for i in instruments} == {"fiddle"}


# ── seed_sets ─────────────────────────────────────────────────────────────────


async def test_seed_sets_creates_set(db: AsyncSession) -> None:
    await _tune(db, "The Morning Dew")
    records = [
        {
            "title": "Morning Set",
            "description": None,
            "source": None,
            "abc_header": None,
            "flow_difficulty": None,
            "flow_difficulty_notes": None,
            "members": [{"tune_title": "The Morning Dew", "setting_label": None}],
        }
    ]
    created, updated, errors = await seed_sets(db, records)
    assert created == 1
    assert updated == 0
    assert errors == 0
    result = (await db.execute(select(TuneSet).where(TuneSet.title == "Morning Set"))).scalar_one_or_none()
    assert result is not None


async def test_seed_sets_reconciles_existing_set(db: AsyncSession) -> None:
    t1 = await _tune(db, "Tune A")
    t2 = await _tune(db, "Tune B")
    await seed_sets(db, [{"title": "My Set", "description": "Old", "members": [{"tune_title": "Tune A"}]}])

    created, updated, errors = await seed_sets(
        db,
        [
            {
                "title": "My Set",
                "description": "New",
                "members": [{"tune_title": "Tune A"}, {"tune_title": "Tune B"}],
            }
        ],
    )
    assert (created, updated, errors) == (0, 1, 0)

    result = (await db.execute(select(TuneSet).where(TuneSet.title == "My Set"))).scalar_one()
    assert result.description == "New"
    members = (
        (await db.execute(select(TuneSetMember).where(TuneSetMember.set_id == result.id).order_by(TuneSetMember.order)))
        .scalars()
        .all()
    )
    assert [m.tune_id for m in members] == [t1.id, t2.id]


async def test_seed_sets_reconcile_removes_member_no_longer_in_record(db: AsyncSession) -> None:
    t1 = await _tune(db, "Tune A")
    await _tune(db, "Tune B")
    await seed_sets(db, [{"title": "My Set", "members": [{"tune_title": "Tune A"}, {"tune_title": "Tune B"}]}])
    await seed_sets(db, [{"title": "My Set", "members": [{"tune_title": "Tune A"}]}])

    result = (await db.execute(select(TuneSet).where(TuneSet.title == "My Set"))).scalar_one()
    members = (await db.execute(select(TuneSetMember).where(TuneSetMember.set_id == result.id))).scalars().all()
    assert [m.tune_id for m in members] == [t1.id]


async def test_seed_sets_stores_members_in_order(db: AsyncSession) -> None:
    t1 = await _tune(db, "Tune A")
    t2 = await _tune(db, "Tune B")
    records = [
        {
            "title": "Two Tune Set",
            "members": [
                {"tune_title": "Tune A", "setting_label": None},
                {"tune_title": "Tune B", "setting_label": None},
            ],
        }
    ]
    await seed_sets(db, records)
    members = (
        (
            await db.execute(
                select(TuneSetMember).join(TuneSet).where(TuneSet.title == "Two Tune Set").order_by(TuneSetMember.order)
            )
        )
        .scalars()
        .all()
    )
    assert len(members) == 2
    assert members[0].tune_id == t1.id
    assert members[1].tune_id == t2.id
    assert members[0].order == 0
    assert members[1].order == 1


async def test_seed_sets_warns_on_missing_tune(db: AsyncSession, capsys) -> None:
    records = [{"title": "Broken Set", "members": [{"tune_title": "Nonexistent Tune", "setting_label": None}]}]
    created, updated, errors = await seed_sets(db, records)
    assert created == 1
    assert errors == 0
    out = capsys.readouterr().out
    assert "WARN" in out
    assert "Nonexistent Tune" in out


async def test_seed_sets_stores_metadata(db: AsyncSession) -> None:
    records = [
        {
            "title": "Meta Set",
            "description": "Great set",
            "source": "Session",
            "abc_header": "P:AB",
            "flow_difficulty": 4,
            "flow_difficulty_notes": "Tricky transition",
            "members": [],
        }
    ]
    await seed_sets(db, records)
    result = (await db.execute(select(TuneSet).where(TuneSet.title == "Meta Set"))).scalar_one()
    assert result.description == "Great set"
    assert result.source == "Session"
    assert result.abc_header == "P:AB"
    assert result.flow_difficulty == 4
    assert result.flow_difficulty_notes == "Tricky transition"


# ── export_sets ───────────────────────────────────────────────────────────────


async def test_export_sets_writes_file(db: AsyncSession, tmp_path: Path) -> None:
    t = await _tune(db, "The Morning Dew")
    tune_set = TuneSet(title="Export Set", source="Catskills", flow_difficulty=2)
    db.add(tune_set)
    await db.flush()
    db.add(TuneSetMember(set_id=tune_set.id, tune_id=t.id, order=0))
    await db.commit()

    n = await export_sets(db, tmp_path)
    assert n == 1
    path = tmp_path / "sets.json"
    assert path.exists()
    import json

    data = json.loads(path.read_text())
    assert len(data) == 1
    rec = data[0]
    assert rec["title"] == "Export Set"
    assert rec["source"] == "Catskills"
    assert rec["flow_difficulty"] == 2
    assert rec["members"][0]["tune_title"] == "The Morning Dew"
    assert rec["members"][0]["setting_label"] is None


# ── seed_recordings ──────────────────────────────────────────────────────────


async def test_seed_recordings_creates_recording_with_setting_reference(db: AsyncSession) -> None:
    await _tune(db, "The Morning Dew")
    records = [
        {
            "artist": "Lúnasa",
            "title": "Otherworld",
            "links": {"youtube": "https://www.youtube.com/watch?v=abc"},
            "references": [
                {"tune_title": "The Morning Dew", "setting_label": "Standard", "track_number": 3, "position": 1}
            ],
        }
    ]
    created, updated, errors = await seed_recordings(db, records)
    assert (created, updated, errors) == (1, 0, 0)

    recording = (
        await db.execute(select(Recording).where(Recording.artist == "Lúnasa", Recording.title == "Otherworld"))
    ).scalar_one()
    assert recording.links == {"youtube": "https://www.youtube.com/watch?v=abc"}
    ref = (
        await db.execute(select(RecordingReference).where(RecordingReference.recording_id == recording.id))
    ).scalar_one()
    assert ref.track_number == 3
    assert ref.position == 1
    assert ref.set_id is None


async def test_seed_recordings_creates_recording_with_set_reference(db: AsyncSession) -> None:
    t = await _tune(db, "The Morning Dew")
    tune_set = await create_set(db, title="Morning Set")
    await set_members(db, tune_set.id, [{"tune_id": t.id, "setting_id": None}])
    records = [{"artist": "Various", "title": "Live Set", "links": None, "references": [{"set_title": "Morning Set"}]}]
    created, updated, errors = await seed_recordings(db, records)
    assert (created, updated, errors) == (1, 0, 0)

    recording = (
        await db.execute(select(Recording).where(Recording.artist == "Various", Recording.title == "Live Set"))
    ).scalar_one()
    ref = (
        await db.execute(select(RecordingReference).where(RecordingReference.recording_id == recording.id))
    ).scalar_one()
    assert ref.set_id == tune_set.id
    assert ref.setting_id is None


async def test_seed_recordings_reconcile_removes_stale_reference(db: AsyncSession) -> None:
    await _tune(db, "Tune A")
    await _tune(db, "Tune B")
    links = {"youtube": "abc"}
    base_refs = [
        {"tune_title": "Tune A", "setting_label": "Standard"},
        {"tune_title": "Tune B", "setting_label": "Standard"},
    ]
    await seed_recordings(db, [{"artist": "Lúnasa", "title": "Otherworld", "links": links, "references": base_refs}])

    created, updated, errors = await seed_recordings(
        db,
        [
            {
                "artist": "Lúnasa",
                "title": "Otherworld",
                "links": links,
                "references": [{"tune_title": "Tune A", "setting_label": "Standard"}],
            }
        ],
    )
    assert (created, updated, errors) == (0, 1, 0)

    recording = (
        await db.execute(select(Recording).where(Recording.artist == "Lúnasa", Recording.title == "Otherworld"))
    ).scalar_one()
    refs = (
        (await db.execute(select(RecordingReference).where(RecordingReference.recording_id == recording.id)))
        .scalars()
        .all()
    )
    assert len(refs) == 1


async def test_seed_recordings_treats_different_links_as_a_distinct_recording(db: AsyncSession) -> None:
    # Recording has no DB uniqueness on (artist, title) -- the real catalog
    # has genuinely distinct recordings sharing a title, distinguished only
    # by their links. A naive (artist, title) natural key would collapse
    # them onto one row and silently drop references processed earlier in
    # the same run; links must be part of the identity.
    await _tune(db, "Tune A")
    await _tune(db, "Tune B")
    records = [
        {
            "artist": "Ceoltóirí Cultúrlainne",
            "title": "Foinn Seisiún 2",
            "links": {"youtube": "aaa"},
            "references": [{"tune_title": "Tune A", "setting_label": "Standard"}],
        },
        {
            "artist": "Ceoltóirí Cultúrlainne",
            "title": "Foinn Seisiún 2",
            "links": {"youtube": "bbb"},
            "references": [{"tune_title": "Tune B", "setting_label": "Standard"}],
        },
    ]
    created, updated, errors = await seed_recordings(db, records)
    assert (created, updated, errors) == (2, 0, 0)

    recordings = (
        (
            await db.execute(
                select(Recording).where(
                    Recording.artist == "Ceoltóirí Cultúrlainne", Recording.title == "Foinn Seisiún 2"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(recordings) == 2
    refs_by_link = {}
    for r in recordings:
        refs = (
            (await db.execute(select(RecordingReference).where(RecordingReference.recording_id == r.id)))
            .scalars()
            .all()
        )
        assert len(refs) == 1
        refs_by_link[r.links["youtube"]] = refs[0]
    assert refs_by_link["aaa"].setting_id is not None
    assert refs_by_link["bbb"].setting_id is not None
    assert refs_by_link["aaa"].setting_id != refs_by_link["bbb"].setting_id


async def test_seed_recordings_warns_on_missing_tune(db: AsyncSession, capsys) -> None:
    records = [
        {
            "artist": "Lúnasa",
            "title": "Otherworld",
            "references": [{"tune_title": "Nonexistent Tune", "setting_label": "Standard"}],
        }
    ]
    created, updated, errors = await seed_recordings(db, records)
    assert (created, errors) == (1, 0)
    out = capsys.readouterr().out
    assert "WARN setting not found" in out
    assert "Nonexistent Tune" in out


# ── export_recordings ────────────────────────────────────────────────────────


async def test_export_recordings_includes_setting_and_set_references(db: AsyncSession, tmp_path: Path) -> None:
    t = await _tune(db, "The Morning Dew")
    tune_set = await create_set(db, title="Morning Set")
    await set_members(db, tune_set.id, [{"tune_id": t.id, "setting_id": None}])
    setting_id = (await db.execute(select(TuneSetting.id).where(TuneSetting.tune_id == t.id))).scalar_one()

    recording = await create_recording(db, "Lúnasa", "Otherworld", {"youtube": "https://youtu.be/abc"})
    await add_reference(db, recording.id, setting_id=setting_id, track_number=3, position=1)
    await add_reference(db, recording.id, set_id=tune_set.id)

    await export_recordings(db, tmp_path)
    import json

    data = json.loads((tmp_path / "recordings.json").read_text())
    rec = next(r for r in data if r["artist"] == "Lúnasa" and r["title"] == "Otherworld")
    assert rec["links"] == {"youtube": "https://youtu.be/abc"}
    refs = rec["references"]
    setting_ref = next(r for r in refs if r["tune_title"] is not None)
    set_ref = next(r for r in refs if r["set_title"] is not None)
    assert setting_ref["tune_title"] == "The Morning Dew"
    assert setting_ref["setting_label"] == "Standard"
    assert setting_ref["track_number"] == 3
    assert setting_ref["position"] == 1
    assert set_ref["set_title"] == "Morning Set"


# ── seed_boxes ───────────────────────────────────────────────────────────────


async def test_seed_boxes_creates_entry_with_alias_and_transpose(db: AsyncSession) -> None:
    tune = await _tune(db, "The Morning Dew")
    await add_alias(db, tune.id, "Morning Air")
    records = [
        {
            "name": "My Box",
            "instruments": [],
            "entries": [
                {
                    "tune_title": "The Morning Dew",
                    "setting_label": None,
                    "display_alias_name": "Morning Air",
                    "transpose_key_root": "G",
                    "transpose_octave": -1,
                }
            ],
        }
    ]
    created, updated, errors = await seed_boxes(db, records)
    assert (created, updated, errors) == (1, 0, 0)

    entry = (await db.execute(select(TuneBoxEntry).join(TuneBox).where(TuneBox.name == "My Box"))).scalar_one()
    alias = (await db.execute(select(TuneAlias).where(TuneAlias.id == entry.display_alias_id))).scalar_one()
    assert alias.name == "Morning Air"
    assert entry.transpose_key_root == KeyRoot.G
    assert entry.transpose_octave == -1


async def test_seed_boxes_creates_embedded_set_with_difficulty_override(db: AsyncSession) -> None:
    tune = await _tune(db, "The Morning Dew")
    tune_set = await create_set(db, title="Morning Set")
    await set_members(db, tune_set.id, [{"tune_id": tune.id, "setting_id": None}])

    records = [
        {
            "name": "My Box",
            "entries": [],
            "set_entries": [{"set_title": "Morning Set", "difficulty_override": 4}],
        }
    ]
    created, updated, errors = await seed_boxes(db, records)
    assert (created, updated, errors) == (1, 0, 0)

    box = (await db.execute(select(TuneBox).where(TuneBox.name == "My Box"))).scalar_one()
    difficulty = await get_set_difficulty_override(db, box.id, tune_set.id)
    assert difficulty == 4


async def test_seed_boxes_warns_on_missing_set(db: AsyncSession, capsys) -> None:
    records = [{"name": "My Box", "entries": [], "set_entries": [{"set_title": "Nonexistent Set"}]}]
    created, updated, errors = await seed_boxes(db, records)
    assert (created, errors) == (1, 0)
    out = capsys.readouterr().out
    assert "WARN set not found" in out
    assert "Nonexistent Set" in out


async def test_seed_boxes_reconcile_updates_entry_and_removes_stale(db: AsyncSession) -> None:
    t1 = await _tune(db, "Tune A")
    t2 = await _tune(db, "Tune B")
    await seed_boxes(
        db,
        [
            {
                "name": "My Box",
                "entries": [
                    {"tune_title": "Tune A", "transpose_octave": 0},
                    {"tune_title": "Tune B", "transpose_octave": 0},
                ],
            }
        ],
    )

    created, updated, errors = await seed_boxes(
        db, [{"name": "My Box", "entries": [{"tune_title": "Tune A", "transpose_octave": -1}]}]
    )
    assert (created, updated, errors) == (0, 1, 0)

    box = (await db.execute(select(TuneBox).where(TuneBox.name == "My Box"))).scalar_one()
    entries = (await db.execute(select(TuneBoxEntry).where(TuneBoxEntry.box_id == box.id))).scalars().all()
    assert len(entries) == 1
    assert entries[0].tune_id == t1.id
    assert entries[0].transpose_octave == -1
    assert not any(e.tune_id == t2.id for e in entries)


async def test_seed_boxes_reconcile_removes_embedded_set_no_longer_present(db: AsyncSession) -> None:
    tune = await _tune(db, "The Morning Dew")
    tune_set = await create_set(db, title="Morning Set")
    await set_members(db, tune_set.id, [{"tune_id": tune.id, "setting_id": None}])
    await seed_boxes(db, [{"name": "My Box", "entries": [], "set_entries": [{"set_title": "Morning Set"}]}])

    await seed_boxes(db, [{"name": "My Box", "entries": [], "set_entries": []}])

    box = (await db.execute(select(TuneBox).where(TuneBox.name == "My Box"))).scalar_one()
    assert await list_box_sets(db, box.id) == []


# ── export_boxes ─────────────────────────────────────────────────────────────


async def test_export_boxes_includes_entry_overrides_and_set_entries(db: AsyncSession, tmp_path: Path) -> None:
    tune = await _tune(db, "The Morning Dew")
    alias = await add_alias(db, tune.id, "Morning Air")
    tune_set = await create_set(db, title="Morning Set")

    box = TuneBox(user_id=1, name="My Box")
    db.add(box)
    await db.flush()
    db.add(
        TuneBoxEntry(
            box_id=box.id,
            tune_id=tune.id,
            display_alias_id=alias.id,
            transpose_key_root=KeyRoot.G,
            transpose_octave=-1,
        )
    )
    await db.commit()
    await add_box_set(db, box.id, tune_set.id)
    await set_box_set_difficulty(db, box.id, tune_set.id, 4)

    await export_boxes(db, tmp_path)
    import json

    data = json.loads((tmp_path / "boxes.json").read_text())
    rec = next(r for r in data if r["name"] == "My Box")
    entry = rec["entries"][0]
    assert entry["display_alias_name"] == "Morning Air"
    assert entry["transpose_key_root"] == "G"
    assert entry["transpose_octave"] == -1
    assert rec["set_entries"] == [{"set_title": "Morning Set", "difficulty_override": 4}]


# ── seed_lists ───────────────────────────────────────────────────────────────


async def test_seed_lists_creates_entry_with_focus_and_transpose(db: AsyncSession) -> None:
    await seed_boxes(db, [{"name": "My Box", "entries": []}])
    tune = await _tune(db, "The Morning Dew")
    await add_alias(db, tune.id, "Morning Air")
    records = [
        {
            "name": "My List",
            "box_name": "My Box",
            "list_type": "woodshed",
            "progress_goal": "committed",
            "entries": [
                {
                    "tune_title": "The Morning Dew",
                    "setting_label": None,
                    "display_alias_name": "Morning Air",
                    "transpose_key_root": "G",
                    "transpose_octave": 1,
                    "is_focus": True,
                }
            ],
        }
    ]
    created, updated, errors = await seed_lists(db, records)
    assert (created, updated, errors) == (1, 0, 0)

    entry = (
        await db.execute(select(TuneListEntry).join(PracticeList).where(PracticeList.name == "My List"))
    ).scalar_one()
    assert entry.transpose_key_root == KeyRoot.G
    assert entry.transpose_octave == 1
    assert entry.is_focus is True


async def test_seed_lists_creates_embedded_set(db: AsyncSession) -> None:
    await seed_boxes(db, [{"name": "My Box", "entries": []}])
    tune = await _tune(db, "The Morning Dew")
    tune_set = await create_set(db, title="Morning Set")
    await set_members(db, tune_set.id, [{"tune_id": tune.id, "setting_id": None}])

    records = [
        {
            "name": "My List",
            "box_name": "My Box",
            "list_type": "woodshed",
            "progress_goal": "committed",
            "entries": [],
            "set_entries": [{"set_title": "Morning Set"}],
        }
    ]
    await seed_lists(db, records)
    pl = (await db.execute(select(PracticeList).where(PracticeList.name == "My List"))).scalar_one()
    set_entries = await list_list_sets(db, pl.id)
    assert len(set_entries) == 1
    assert set_entries[0].set_id == tune_set.id


async def test_seed_lists_reconcile_updates_entry_and_removes_stale(db: AsyncSession) -> None:
    await seed_boxes(db, [{"name": "My Box", "entries": []}])
    t1 = await _tune(db, "Tune A")
    t2 = await _tune(db, "Tune B")
    base = {"name": "My List", "box_name": "My Box", "list_type": "woodshed", "progress_goal": "committed"}
    await seed_lists(
        db,
        [
            {
                **base,
                "entries": [
                    {"tune_title": "Tune A", "is_focus": False},
                    {"tune_title": "Tune B", "is_focus": False},
                ],
            }
        ],
    )

    created, updated, errors = await seed_lists(db, [{**base, "entries": [{"tune_title": "Tune A", "is_focus": True}]}])
    assert (created, updated, errors) == (0, 1, 0)

    pl = (await db.execute(select(PracticeList).where(PracticeList.name == "My List"))).scalar_one()
    entries = (await db.execute(select(TuneListEntry).where(TuneListEntry.list_id == pl.id))).scalars().all()
    assert len(entries) == 1
    assert entries[0].tune_id == t1.id
    assert entries[0].is_focus is True
    assert not any(e.tune_id == t2.id for e in entries)


# ── export_lists ─────────────────────────────────────────────────────────────


async def test_export_lists_includes_entry_overrides_focus_and_set_entries(db: AsyncSession, tmp_path: Path) -> None:
    tune = await _tune(db, "The Morning Dew")
    alias = await add_alias(db, tune.id, "Morning Air")
    tune_set = await create_set(db, title="Morning Set")

    box = TuneBox(user_id=1, name="My Box")
    db.add(box)
    await db.flush()
    pl = PracticeList(
        user_id=1,
        box_id=box.id,
        name="My List",
        list_type=PracticeListType.woodshed,
        progress_goal=ProgressStatus.committed,
    )
    db.add(pl)
    await db.flush()
    db.add(
        TuneListEntry(
            list_id=pl.id,
            tune_id=tune.id,
            display_alias_id=alias.id,
            transpose_key_root=KeyRoot.G,
            transpose_octave=1,
            is_focus=True,
        )
    )
    await db.commit()
    await add_list_set(db, pl.id, tune_set.id)

    await export_lists(db, tmp_path)
    import json

    data = json.loads((tmp_path / "lists.json").read_text())
    rec = next(r for r in data if r["name"] == "My List")
    entry = rec["entries"][0]
    assert entry["display_alias_name"] == "Morning Air"
    assert entry["transpose_key_root"] == "G"
    assert entry["transpose_octave"] == 1
    assert entry["is_focus"] is True
    assert rec["set_entries"] == [{"set_title": "Morning Set", "difficulty_override": None}]


async def test_export_sets_empty(db: AsyncSession, tmp_path: Path) -> None:
    n = await export_sets(db, tmp_path)
    assert n == 0
    import json

    data = json.loads((tmp_path / "sets.json").read_text())
    assert data == []
