from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import (
    ContentVisibility,
    KeyMode,
    KeyRoot,
    Tune,
    TuneAlias,
    TuneSet,
    TuneSetMember,
    TuneSetting,
    TuneType,
)
from cairn.schemas import TuneCreate, TuneSettingCreate
from cairn.services.tunes import add_alias, create_setting, create_tune
from scripts.export_seed import export_sets, export_tunes
from scripts.seed import seed_sets, seed_tunes


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
    loaded, skipped, errors = await seed_tunes(db, [rec])
    assert (loaded, skipped, errors) == (1, 0, 0)

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
    loaded, skipped, errors = await seed_sets(db, records)
    assert loaded == 1
    assert skipped == 0
    assert errors == 0
    result = (await db.execute(select(TuneSet).where(TuneSet.title == "Morning Set"))).scalar_one_or_none()
    assert result is not None


async def test_seed_sets_skips_duplicate_title(db: AsyncSession) -> None:
    records = [{"title": "My Set", "members": []}]
    await seed_sets(db, records)
    loaded, skipped, errors = await seed_sets(db, records)
    assert loaded == 0
    assert skipped == 1
    assert errors == 0


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
    loaded, skipped, errors = await seed_sets(db, records)
    assert loaded == 1
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


async def test_export_sets_empty(db: AsyncSession, tmp_path: Path) -> None:
    n = await export_sets(db, tmp_path)
    assert n == 0
    import json

    data = json.loads((tmp_path / "sets.json").read_text())
    assert data == []
