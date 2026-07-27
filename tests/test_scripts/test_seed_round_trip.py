"""Export/seed round-trip fidelity tests (#269).

Each test builds a fully-populated record via the normal service functions
on one database, exports it, seeds a second, completely separate database
from that export, then compares the reconstructed record against the
original. Two independent databases (the `db`/`db2` fixtures) rather than
one shared session, so this is a real round trip through the seeds/*.json
file shape -- not just "does this ORM object still look the same in the
same session," which would prove nothing about the export/seed scripts
themselves.

Scalar-field comparisons use SQLAlchemy's own column introspection
(_fields()) rather than a hand-picked list of field names, specifically so
that adding a new column to one of these models is automatically covered
by this test without anyone remembering to update it here too -- a
hand-picked list would silently stop catching new-field drift the same
way the original bug (aliases/visibility/TheSession-link fields dropped)
went unnoticed. Foreign keys to sibling entities (e.g. TuneSetMember.tune_id)
can't be compared as raw ids -- ids aren't stable across two separate
databases -- so those are resolved and compared via natural keys instead,
and excluded from the introspected field set for that reason (not because
they don't matter).
"""

import json
from pathlib import Path

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import (
    ContentVisibility,
    Instrument,
    KeyMode,
    KeyRoot,
    OrnamentationLevel,
    PracticeList,
    PracticeListType,
    ProgressStatus,
    Recording,
    RecordingReference,
    Tune,
    TuneAlias,
    TuneBox,
    TuneBoxEntry,
    TuneDifficulty,
    TuneListEntry,
    TuneSet,
    TuneSetMember,
    TuneSetting,
    TuneType,
    WarmupInstrument,
    WarmupItem,
    WarmupType,
)
from cairn.schemas import TuneCreate, TuneDifficultyCreate, TuneSettingCreate
from cairn.services.recordings import add_reference, create_recording
from cairn.services.tune_sets import (
    add_box_set,
    create_set,
    get_set_difficulty_override,
    list_box_sets,
    set_box_set_difficulty,
    set_members,
)
from cairn.services.tunes import add_alias, create_setting, create_tune, set_difficulty
from cairn.services.warmups import create_warmup
from scripts.export_seed import export_boxes, export_lists, export_recordings, export_sets, export_tunes, export_warmups
from scripts.seed import seed_boxes, seed_lists, seed_recordings, seed_sets, seed_tunes, seed_warmups

_STUB_USER_ID = 1

_ID_TS = {"id", "created_at", "updated_at"}
_TUNE_EXCLUDE = _ID_TS | {"sort_title", "created_by"}


def _fields(obj, exclude: set[str]) -> dict:
    return {c.key: getattr(obj, c.key) for c in inspect(type(obj)).mapper.column_attrs if c.key not in exclude}


async def test_tune_round_trip(db: AsyncSession, db2: AsyncSession, tmp_path: Path) -> None:
    tune = await create_tune(
        db,
        TuneCreate(
            title="The Abbey",
            tune_type=TuneType.reel,
            key_root=KeyRoot.A,
            key_mode=KeyMode.dorian,
            time_signature="4/4",
            composer="Trad.",
            origin="Clare",
            region="Munster",
            notes="A session standard.",
            created_by=_STUB_USER_ID,
            visibility=ContentVisibility.enrolled,
        ),
        abc_notation="|:DEFA BAFA:|\n",
        setting_label="Standard",
    )
    tune.thesession_tune_id = 477
    tune.thesession_username = "Josh Kane"
    await db.commit()
    core = (
        await db.execute(select(TuneSetting).where(TuneSetting.tune_id == tune.id, TuneSetting.is_core.is_(True)))
    ).scalar_one()
    core.source = "TheSession.org"
    core.source_notes = "Cited from the community wiki."
    core.visibility = ContentVisibility.enrolled
    core.thesession_setting_id = 999
    core.thesession_username = "Josh Kane"
    await db.commit()
    await create_setting(
        db,
        tune.id,
        TuneSettingCreate(
            tune_id=tune.id,
            label="Ornamented",
            abc_notation="|:~D~EFA BAFA:|\n",
            instrument=Instrument.flute,
            source="Personal arrangement",
            source_notes="Adds rolls throughout.",
            ornamentation_level=OrnamentationLevel.full,
            mutation_notation="some notation",
            visibility=ContentVisibility.public,
        ),
    )
    await set_difficulty(
        db,
        tune.id,
        TuneDifficultyCreate(tune_id=tune.id, instrument=Instrument.flute, difficulty=3, notes="Fast fingering"),
    )
    await add_alias(db, tune.id, "Abbey Reel", notes="common alt spelling")
    await add_alias(db, tune.id, "An Mhainistir")

    await export_tunes(db, tmp_path)
    records = json.loads((tmp_path / "tunes.json").read_text())
    created, updated, errors = await seed_tunes(db2, records)
    assert (created, updated, errors) == (1, 0, 0)

    original = (await db.execute(select(Tune).where(Tune.title == "The Abbey"))).scalar_one()
    reconstructed = (await db2.execute(select(Tune).where(Tune.title == "The Abbey"))).scalar_one()
    assert _fields(original, _TUNE_EXCLUDE) == _fields(reconstructed, _TUNE_EXCLUDE)

    orig_settings = (await db.execute(select(TuneSetting).where(TuneSetting.tune_id == original.id))).scalars().all()
    recon_settings = {
        s.label: s
        for s in (await db2.execute(select(TuneSetting).where(TuneSetting.tune_id == reconstructed.id))).scalars()
    }
    assert {s.label for s in orig_settings} == set(recon_settings)
    for s in orig_settings:
        exclude = _ID_TS | {"tune_id"}
        assert _fields(s, exclude) == _fields(recon_settings[s.label], exclude)

    orig_diffs = (await db.execute(select(TuneDifficulty).where(TuneDifficulty.tune_id == original.id))).scalars().all()
    recon_diffs = {
        d.instrument: d
        for d in (await db2.execute(select(TuneDifficulty).where(TuneDifficulty.tune_id == reconstructed.id))).scalars()
    }
    assert {d.instrument for d in orig_diffs} == set(recon_diffs)
    for d in orig_diffs:
        exclude = _ID_TS | {"tune_id"}
        assert _fields(d, exclude) == _fields(recon_diffs[d.instrument], exclude)

    orig_aliases = (await db.execute(select(TuneAlias).where(TuneAlias.tune_id == original.id))).scalars().all()
    recon_aliases = {
        a.name: a for a in (await db2.execute(select(TuneAlias).where(TuneAlias.tune_id == reconstructed.id))).scalars()
    }
    assert {a.name for a in orig_aliases} == set(recon_aliases)
    for a in orig_aliases:
        exclude = _ID_TS | {"tune_id", "sort_name"}
        assert _fields(a, exclude) == _fields(recon_aliases[a.name], exclude)


async def test_warmup_round_trip(db: AsyncSession, db2: AsyncSession, tmp_path: Path) -> None:
    await create_warmup(
        db,
        title="Long Tones",
        warmup_type=WarmupType.scale,
        content="Hold each note for 8 counts, ascending and descending.",
        difficulty=2,
        instruments=[Instrument.flute, Instrument.tin_whistle],
        default_tempo=60,
    )

    await export_warmups(db, tmp_path)
    records = json.loads((tmp_path / "warmups.json").read_text())
    created, updated, errors = await seed_warmups(db2, records)
    assert (created, updated, errors) == (1, 0, 0)

    original = (await db.execute(select(WarmupItem).where(WarmupItem.title == "Long Tones"))).scalar_one()
    reconstructed = (await db2.execute(select(WarmupItem).where(WarmupItem.title == "Long Tones"))).scalar_one()
    assert _fields(original, _ID_TS) == _fields(reconstructed, _ID_TS)
    orig_instruments = (
        (await db.execute(select(WarmupInstrument).where(WarmupInstrument.warmup_id == original.id))).scalars().all()
    )
    recon_instruments = (
        (await db2.execute(select(WarmupInstrument).where(WarmupInstrument.warmup_id == reconstructed.id)))
        .scalars()
        .all()
    )
    assert {i.instrument for i in orig_instruments} == {i.instrument for i in recon_instruments}


async def _tune(db: AsyncSession, title: str) -> Tune:
    return await create_tune(
        db,
        TuneCreate(
            title=title, tune_type=TuneType.reel, key_root=KeyRoot.D, key_mode=KeyMode.major, time_signature="4/4"
        ),
        abc_notation="|:DEFA BAFA:|\n",
    )


async def _carry_tunes(db: AsyncSession, db2: AsyncSession, tmp_path: Path) -> None:
    """Seed whatever tunes already exist on db into db2 -- boxes/lists/sets/
    recordings all resolve their tune/setting references by title, so db2
    needs the referenced tunes seeded first, the same way main()'s own step
    order requires."""
    await export_tunes(db, tmp_path)
    await seed_tunes(db2, json.loads((tmp_path / "tunes.json").read_text()))


async def test_set_round_trip(db: AsyncSession, db2: AsyncSession, tmp_path: Path) -> None:
    t1 = await _tune(db, "Tune A")
    t2 = await _tune(db, "Tune B")
    tune_set = await create_set(
        db,
        title="Morning Set",
        description="A gentle opener",
        source="Catskills 2023",
        abc_header="P:AABB",
        flow_difficulty=3,
        flow_difficulty_notes="Watch the key change",
    )
    await set_members(db, tune_set.id, [{"tune_id": t1.id, "setting_id": None}, {"tune_id": t2.id, "setting_id": None}])

    await _carry_tunes(db, db2, tmp_path)
    await export_sets(db, tmp_path)
    records = json.loads((tmp_path / "sets.json").read_text())
    created, updated, errors = await seed_sets(db2, records)
    assert (created, updated, errors) == (1, 0, 0)

    original = (await db.execute(select(TuneSet).where(TuneSet.title == "Morning Set"))).scalar_one()
    reconstructed = (await db2.execute(select(TuneSet).where(TuneSet.title == "Morning Set"))).scalar_one()
    assert _fields(original, _ID_TS) == _fields(reconstructed, _ID_TS)

    orig_members = (
        (
            await db.execute(
                select(TuneSetMember).where(TuneSetMember.set_id == original.id).order_by(TuneSetMember.order)
            )
        )
        .scalars()
        .all()
    )
    recon_members = (
        (
            await db2.execute(
                select(TuneSetMember).where(TuneSetMember.set_id == reconstructed.id).order_by(TuneSetMember.order)
            )
        )
        .scalars()
        .all()
    )
    orig_titles = []
    for m in orig_members:
        tune = await db.get(Tune, m.tune_id)
        orig_titles.append((tune.title, m.order))
    recon_titles = []
    for m in recon_members:
        tune = await db2.get(Tune, m.tune_id)
        recon_titles.append((tune.title, m.order))
    assert orig_titles == recon_titles == [("Tune A", 0), ("Tune B", 1)]


async def test_box_round_trip(db: AsyncSession, db2: AsyncSession, tmp_path: Path) -> None:
    tune = await _tune(db, "The Morning Dew")
    alias = await add_alias(db, tune.id, "Morning Air")
    tune_set = await create_set(db, title="Morning Set")
    await set_members(db, tune_set.id, [{"tune_id": tune.id, "setting_id": None}])

    box = TuneBox(user_id=_STUB_USER_ID, name="Flute Tunes")
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

    await _carry_tunes(db, db2, tmp_path)
    await export_sets(db, tmp_path)
    await seed_sets(db2, json.loads((tmp_path / "sets.json").read_text()))
    await export_boxes(db, tmp_path)
    records = json.loads((tmp_path / "boxes.json").read_text())
    created, updated, errors = await seed_boxes(db2, records)
    assert (created, updated, errors) == (1, 0, 0)

    original = (await db.execute(select(TuneBox).where(TuneBox.name == "Flute Tunes"))).scalar_one()
    reconstructed = (await db2.execute(select(TuneBox).where(TuneBox.name == "Flute Tunes"))).scalar_one()
    assert _fields(original, _ID_TS) == _fields(reconstructed, _ID_TS)

    orig_entry = (await db.execute(select(TuneBoxEntry).where(TuneBoxEntry.box_id == original.id))).scalar_one()
    recon_entry = (await db2.execute(select(TuneBoxEntry).where(TuneBoxEntry.box_id == reconstructed.id))).scalar_one()
    assert orig_entry.transpose_key_root == recon_entry.transpose_key_root == KeyRoot.G
    assert orig_entry.transpose_octave == recon_entry.transpose_octave == -1
    recon_alias = await db2.get(TuneAlias, recon_entry.display_alias_id)
    assert recon_alias.name == "Morning Air"

    recon_set_entries = await list_box_sets(db2, reconstructed.id)
    assert len(recon_set_entries) == 1
    assert recon_set_entries[0].tune_set.title == "Morning Set"
    assert await get_set_difficulty_override(db2, reconstructed.id, recon_set_entries[0].set_id) == 4


async def test_list_round_trip(db: AsyncSession, db2: AsyncSession, tmp_path: Path) -> None:
    tune = await _tune(db, "The Morning Dew")
    alias = await add_alias(db, tune.id, "Morning Air")
    box = TuneBox(user_id=_STUB_USER_ID, name="Flute Tunes")
    db.add(box)
    await db.flush()
    pl = PracticeList(
        user_id=_STUB_USER_ID,
        box_id=box.id,
        name="Favorites",
        list_type=PracticeListType.woodshed,
        progress_goal=ProgressStatus.performance_ready,
        is_active=True,
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

    await _carry_tunes(db, db2, tmp_path)
    await export_boxes(db, tmp_path)
    await seed_boxes(db2, json.loads((tmp_path / "boxes.json").read_text()))
    await export_lists(db, tmp_path)
    records = json.loads((tmp_path / "lists.json").read_text())
    created, updated, errors = await seed_lists(db2, records)
    assert (created, updated, errors) == (1, 0, 0)

    original = (await db.execute(select(PracticeList).where(PracticeList.name == "Favorites"))).scalar_one()
    reconstructed = (await db2.execute(select(PracticeList).where(PracticeList.name == "Favorites"))).scalar_one()
    exclude = _ID_TS | {"box_id"}
    assert _fields(original, exclude) == _fields(reconstructed, exclude)

    orig_entry = (await db.execute(select(TuneListEntry).where(TuneListEntry.list_id == original.id))).scalar_one()
    recon_entry = (
        await db2.execute(select(TuneListEntry).where(TuneListEntry.list_id == reconstructed.id))
    ).scalar_one()
    assert orig_entry.transpose_key_root == recon_entry.transpose_key_root == KeyRoot.G
    assert orig_entry.transpose_octave == recon_entry.transpose_octave == 1
    assert orig_entry.is_focus == recon_entry.is_focus is True
    recon_alias = await db2.get(TuneAlias, recon_entry.display_alias_id)
    assert recon_alias.name == "Morning Air"


async def test_recording_round_trip(db: AsyncSession, db2: AsyncSession, tmp_path: Path) -> None:
    tune = await _tune(db, "The Morning Dew")
    tune_set = await create_set(db, title="Morning Set")
    await set_members(db, tune_set.id, [{"tune_id": tune.id, "setting_id": None}])
    setting_id = (await db.execute(select(TuneSetting.id).where(TuneSetting.tune_id == tune.id))).scalar_one()

    recording = await create_recording(db, "Lúnasa", "Otherworld", {"youtube": "https://youtu.be/abc"})
    await add_reference(db, recording.id, setting_id=setting_id, track_number=3, position=1)
    await add_reference(db, recording.id, set_id=tune_set.id)

    await _carry_tunes(db, db2, tmp_path)
    await export_sets(db, tmp_path)
    await seed_sets(db2, json.loads((tmp_path / "sets.json").read_text()))
    await export_recordings(db, tmp_path)
    records = json.loads((tmp_path / "recordings.json").read_text())
    created, updated, errors = await seed_recordings(db2, records)
    assert (created, updated, errors) == (1, 0, 0)

    original = (
        await db.execute(select(Recording).where(Recording.artist == "Lúnasa", Recording.title == "Otherworld"))
    ).scalar_one()
    reconstructed = (
        await db2.execute(select(Recording).where(Recording.artist == "Lúnasa", Recording.title == "Otherworld"))
    ).scalar_one()
    assert _fields(original, _ID_TS) == _fields(reconstructed, _ID_TS)

    orig_refs = (
        (await db.execute(select(RecordingReference).where(RecordingReference.recording_id == original.id)))
        .scalars()
        .all()
    )
    recon_refs = (
        (await db2.execute(select(RecordingReference).where(RecordingReference.recording_id == reconstructed.id)))
        .scalars()
        .all()
    )
    assert len(orig_refs) == len(recon_refs) == 2

    async def _describe(session, ref):
        if ref.setting_id is not None:
            setting = await session.get(TuneSetting, ref.setting_id)
            tune = await session.get(Tune, setting.tune_id)
            return ("setting", tune.title, setting.label, ref.track_number, ref.position)
        tset = await session.get(TuneSet, ref.set_id)
        return ("set", tset.title, ref.track_number, ref.position)

    orig_described = {await _describe(db, r) for r in orig_refs}
    recon_described = {await _describe(db2, r) for r in recon_refs}
    assert orig_described == recon_described
