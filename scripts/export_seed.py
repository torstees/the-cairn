#!/usr/bin/env python
"""
Export all seedable data to the seeds/ directory.

Files written:
  seeds/tunes.json    — Tune + TuneSetting + TuneDifficulty
  seeds/warmups.json  — WarmupItem + WarmupInstrument
  seeds/boxes.json    — TuneBox + TuneBoxInstrument + TuneBoxEntry
  seeds/lists.json    — PracticeList + TuneListEntry
  seeds/sets.json     — TuneSet + TuneSetMember

Cross-references (box entries, list entries, set members) use stable
human-readable keys (tune title, setting label, box name) so seeds survive
a fresh database.

Usage:
    uv run python scripts/export_seed.py [seeds_dir]
    Defaults to seeds/ relative to the project root.
    Also: make export-seed
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from cairn.database import AsyncSessionLocal
from cairn.models import PracticeList, TuneBox, TuneBoxEntry, TuneListEntry, TuneSet, TuneSetMember, WarmupItem
from cairn.services.tunes import list_tunes
from cairn.services.warmups import list_warmups

_STUB_USER_ID = 1


def _write(path: Path, records: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


async def export_tunes(db, out_dir: Path) -> int:
    tunes = await list_tunes(db)
    records = []
    for tune in tunes:
        records.append(
            {
                "title": tune.title,
                "tune_type": tune.tune_type.value,
                "key_root": tune.key_root.value,
                "key_mode": tune.key_mode.value,
                "time_signature": tune.time_signature,
                "composer": tune.composer,
                "origin": tune.origin,
                "region": tune.region,
                "notes": tune.notes,
                "settings": [
                    {
                        "label": s.label,
                        "abc_notation": s.abc_notation,
                        "is_core": s.is_core,
                        "instrument": s.instrument.value if s.instrument else None,
                        "source": s.source,
                        "source_notes": s.source_notes,
                        "ornamentation_level": s.ornamentation_level.value,
                        "mutation_notation": s.mutation_notation,
                    }
                    for s in tune.settings
                ],
                "difficulties": [
                    {
                        "instrument": d.instrument.value,
                        "difficulty": d.difficulty,
                        "notes": d.notes,
                    }
                    for d in tune.difficulties
                ],
            }
        )
    _write(out_dir / "tunes.json", records)
    return len(records)


async def export_warmups(db, out_dir: Path) -> int:
    warmups = await list_warmups(db)
    records = [
        {
            "title": w.title,
            "warmup_type": w.warmup_type.value,
            "content": w.content,
            "difficulty": w.difficulty,
            "default_tempo": w.default_tempo,
            "instruments": [i.instrument.value for i in w.instruments],
        }
        for w in warmups
    ]
    _write(out_dir / "warmups.json", records)
    return len(records)


async def export_boxes(db, out_dir: Path) -> int:
    result = await db.execute(
        select(TuneBox)
        .where(TuneBox.user_id == _STUB_USER_ID)
        .options(
            selectinload(TuneBox.instruments),
            selectinload(TuneBox.entries).selectinload(TuneBoxEntry.tune),
            selectinload(TuneBox.entries).selectinload(TuneBoxEntry.setting),
        )
        .order_by(TuneBox.name)
    )
    boxes = list(result.scalars().all())
    records = [
        {
            "name": box.name,
            "instruments": [i.instrument.value for i in box.instruments],
            "entries": [
                {
                    "tune_title": entry.tune.title,
                    "setting_label": entry.setting.label if entry.setting else None,
                }
                for entry in box.entries
            ],
        }
        for box in boxes
    ]
    _write(out_dir / "boxes.json", records)
    return len(records)


async def export_lists(db, out_dir: Path) -> int:
    result = await db.execute(
        select(PracticeList)
        .where(PracticeList.user_id == _STUB_USER_ID)
        .options(
            selectinload(PracticeList.box),
            selectinload(PracticeList.entries).selectinload(TuneListEntry.tune),
            selectinload(PracticeList.entries).selectinload(TuneListEntry.setting),
        )
        .order_by(PracticeList.name)
    )
    lists = list(result.scalars().all())
    records = [
        {
            "name": pl.name,
            "box_name": pl.box.name,
            "list_type": pl.list_type.value,
            "progress_goal": pl.progress_goal.value,
            "target_date": pl.target_date.isoformat() if pl.target_date else None,
            "is_active": pl.is_active,
            "entries": [
                {
                    "tune_title": entry.tune.title,
                    "setting_label": entry.setting.label if entry.setting else None,
                }
                for entry in pl.entries
            ],
        }
        for pl in lists
    ]
    _write(out_dir / "lists.json", records)
    return len(records)


async def export_sets(db, out_dir: Path) -> int:
    result = await db.execute(
        select(TuneSet)
        .options(
            selectinload(TuneSet.members).selectinload(TuneSetMember.tune),
            selectinload(TuneSet.members).selectinload(TuneSetMember.setting),
        )
        .order_by(TuneSet.title)
    )
    sets = list(result.scalars().all())
    records = [
        {
            "title": s.title,
            "description": s.description,
            "source": s.source,
            "abc_header": s.abc_header,
            "flow_difficulty": s.flow_difficulty,
            "flow_difficulty_notes": s.flow_difficulty_notes,
            "members": [
                {
                    "tune_title": m.tune.title,
                    "setting_label": m.setting.label if m.setting else None,
                }
                for m in s.members
            ],
        }
        for s in sets
    ]
    _write(out_dir / "sets.json", records)
    return len(records)


async def main(out_dir: Path) -> None:
    async with AsyncSessionLocal() as db:
        n_tunes = await export_tunes(db, out_dir)
        n_warmups = await export_warmups(db, out_dir)
        n_boxes = await export_boxes(db, out_dir)
        n_lists = await export_lists(db, out_dir)
        n_sets = await export_sets(db, out_dir)

    print(f"Exported to {out_dir}/")
    print(f"  {n_tunes:>4} tunes")
    print(f"  {n_warmups:>4} warmups")
    print(f"  {n_boxes:>4} boxes")
    print(f"  {n_lists:>4} lists")
    print(f"  {n_sets:>4} sets")


if __name__ == "__main__":
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent / "seeds"
    asyncio.run(main(out_dir))
