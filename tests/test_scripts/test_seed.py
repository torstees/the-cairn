from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import KeyMode, KeyRoot, TuneSet, TuneSetMember, TuneType
from cairn.schemas import TuneCreate
from cairn.services.tunes import create_tune
from scripts.export_seed import export_sets
from scripts.seed import seed_sets


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
