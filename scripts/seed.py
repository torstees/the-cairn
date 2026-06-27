#!/usr/bin/env python
"""
Seed the database from the seeds/ directory.

Files read (if present, processed in dependency order):
  seeds/tunes.json    — Tune + TuneSetting + TuneDifficulty
  seeds/warmups.json  — WarmupItem + WarmupInstrument
  seeds/boxes.json    — TuneBox + TuneBoxInstrument + TuneBoxEntry
  seeds/lists.json    — PracticeList + TuneListEntry
  seeds/sets.json     — TuneSet + TuneSetMember

Missing files are skipped with a notice. Existing records are skipped by
natural key (safe to re-run). Cross-references are resolved by title / label /
name rather than by ID.

Usage:
    uv run python scripts/seed.py [seeds_dir]
    Defaults to seeds/ relative to the project root.
    Also: make seed
"""

import asyncio
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from cairn.database import AsyncSessionLocal
from cairn.models import (
    Instrument,
    KeyMode,
    KeyRoot,
    OrnamentationLevel,
    PracticeList,
    PracticeListType,
    ProgressStatus,
    Tune,
    TuneBox,
    TuneBoxEntry,
    TuneBoxInstrument,
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
from cairn.services.tunes import create_setting, create_tune, set_difficulty

_STUB_USER_ID = 1


def _load(path: Path) -> list | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


async def _resolve_tune_id(db, title: str) -> int | None:
    return (await db.execute(select(Tune.id).where(Tune.title == title))).scalar_one_or_none()


async def _resolve_setting_id(db, tune_id: int, label: str | None) -> int | None:
    if label is None:
        return None
    return (
        await db.execute(
            select(TuneSetting.id).where(TuneSetting.tune_id == tune_id, TuneSetting.label == label)
        )
    ).scalar_one_or_none()


async def seed_tunes(db, records: list) -> tuple[int, int, int]:
    loaded = skipped = errors = 0
    for rec in records:
        title = rec["title"]
        if (await db.execute(select(Tune.id).where(Tune.title == title))).scalar_one_or_none() is not None:
            skipped += 1
            continue
        try:
            core_setting = next(
                (s for s in rec["settings"] if s["is_core"]),
                rec["settings"][0] if rec["settings"] else None,
            )
            if core_setting is None:
                raise ValueError("no settings")
            tune = await create_tune(
                db,
                TuneCreate(
                    title=title,
                    tune_type=TuneType(rec["tune_type"]),
                    key_root=KeyRoot(rec["key_root"]),
                    key_mode=KeyMode(rec["key_mode"]),
                    time_signature=rec.get("time_signature", "4/4"),
                    composer=rec.get("composer"),
                    origin=rec.get("origin"),
                    region=rec.get("region"),
                    notes=rec.get("notes"),
                ),
                abc_notation=core_setting["abc_notation"],
                setting_label=core_setting["label"],
            )
            if core_setting.get("source") or core_setting.get("source_notes"):
                core_row = (
                    await db.execute(
                        select(TuneSetting).where(
                            TuneSetting.tune_id == tune.id, TuneSetting.is_core.is_(True)
                        )
                    )
                ).scalar_one_or_none()
                if core_row:
                    core_row.source = core_setting.get("source")
                    core_row.source_notes = core_setting.get("source_notes")
                    await db.commit()
            for s in rec["settings"]:
                if s["is_core"]:
                    continue
                await create_setting(
                    db,
                    tune.id,
                    TuneSettingCreate(
                        tune_id=tune.id,
                        label=s["label"],
                        abc_notation=s["abc_notation"],
                        instrument=Instrument(s["instrument"]) if s.get("instrument") else None,
                        source=s.get("source"),
                        source_notes=s.get("source_notes"),
                        ornamentation_level=OrnamentationLevel(s.get("ornamentation_level", "none")),
                        mutation_notation=s.get("mutation_notation"),
                    ),
                )
            for d in rec.get("difficulties", []):
                await set_difficulty(
                    db,
                    tune.id,
                    TuneDifficultyCreate(
                        tune_id=tune.id,
                        instrument=Instrument(d["instrument"]),
                        difficulty=d["difficulty"],
                        notes=d.get("notes"),
                    ),
                )
            print(f"  OK  {title!r}")
            loaded += 1
        except Exception as exc:
            print(f"  ERR {title!r} — {exc}")
            errors += 1
    return loaded, skipped, errors


async def seed_warmups(db, records: list) -> tuple[int, int, int]:
    loaded = skipped = errors = 0
    for rec in records:
        title = rec["title"]
        if (
            await db.execute(select(WarmupItem.id).where(WarmupItem.title == title))
        ).scalar_one_or_none() is not None:
            skipped += 1
            continue
        try:
            warmup = WarmupItem(
                title=title,
                warmup_type=WarmupType(rec["warmup_type"]),
                content=rec["content"],
                difficulty=rec["difficulty"],
                default_tempo=rec.get("default_tempo"),
            )
            db.add(warmup)
            await db.flush()
            for inst_val in rec.get("instruments", []):
                db.add(WarmupInstrument(warmup_id=warmup.id, instrument=Instrument(inst_val)))
            await db.commit()
            print(f"  OK  {title!r}")
            loaded += 1
        except Exception as exc:
            print(f"  ERR {title!r} — {exc}")
            errors += 1
    return loaded, skipped, errors


async def seed_boxes(db, records: list) -> tuple[int, int, int]:
    loaded = skipped = errors = 0
    for rec in records:
        name = rec["name"]
        if (
            await db.execute(
                select(TuneBox.id).where(TuneBox.user_id == _STUB_USER_ID, TuneBox.name == name)
            )
        ).scalar_one_or_none() is not None:
            skipped += 1
            continue
        try:
            box = TuneBox(user_id=_STUB_USER_ID, name=name)
            db.add(box)
            await db.flush()
            for inst_val in rec.get("instruments", []):
                db.add(TuneBoxInstrument(box_id=box.id, instrument=Instrument(inst_val)))
            await db.flush()
            entry_warns = 0
            for entry_rec in rec.get("entries", []):
                tune_id = await _resolve_tune_id(db, entry_rec["tune_title"])
                if tune_id is None:
                    print(f"    WARN tune not found: {entry_rec['tune_title']!r}")
                    entry_warns += 1
                    continue
                setting_id = await _resolve_setting_id(db, tune_id, entry_rec.get("setting_label"))
                db.add(TuneBoxEntry(box_id=box.id, tune_id=tune_id, setting_id=setting_id))
            await db.commit()
            suffix = f" ({entry_warns} entry warnings)" if entry_warns else ""
            print(f"  OK{suffix}  {name!r}")
            loaded += 1
        except Exception as exc:
            print(f"  ERR {name!r} — {exc}")
            errors += 1
    return loaded, skipped, errors


async def seed_lists(db, records: list) -> tuple[int, int, int]:
    loaded = skipped = errors = 0
    for rec in records:
        name = rec["name"]
        box_id = (
            await db.execute(
                select(TuneBox.id).where(TuneBox.user_id == _STUB_USER_ID, TuneBox.name == rec["box_name"])
            )
        ).scalar_one_or_none()
        if box_id is None:
            print(f"  ERR {name!r} — box not found: {rec['box_name']!r}")
            errors += 1
            continue
        if (
            await db.execute(
                select(PracticeList.id).where(
                    PracticeList.user_id == _STUB_USER_ID,
                    PracticeList.box_id == box_id,
                    PracticeList.name == name,
                )
            )
        ).scalar_one_or_none() is not None:
            skipped += 1
            continue
        try:
            pl = PracticeList(
                user_id=_STUB_USER_ID,
                box_id=box_id,
                name=name,
                list_type=PracticeListType(rec["list_type"]),
                progress_goal=ProgressStatus(rec["progress_goal"]),
                target_date=date.fromisoformat(rec["target_date"]) if rec.get("target_date") else None,
                is_active=rec.get("is_active", False),
            )
            db.add(pl)
            await db.flush()
            entry_warns = 0
            for entry_rec in rec.get("entries", []):
                tune_id = await _resolve_tune_id(db, entry_rec["tune_title"])
                if tune_id is None:
                    print(f"    WARN tune not found: {entry_rec['tune_title']!r}")
                    entry_warns += 1
                    continue
                setting_id = await _resolve_setting_id(db, tune_id, entry_rec.get("setting_label"))
                db.add(TuneListEntry(list_id=pl.id, tune_id=tune_id, setting_id=setting_id))
            await db.commit()
            suffix = f" ({entry_warns} entry warnings)" if entry_warns else ""
            print(f"  OK{suffix}  {name!r}")
            loaded += 1
        except Exception as exc:
            print(f"  ERR {name!r} — {exc}")
            errors += 1
    return loaded, skipped, errors


async def seed_sets(db, records: list) -> tuple[int, int, int]:
    loaded = skipped = errors = 0
    for rec in records:
        title = rec["title"]
        if (
            await db.execute(select(TuneSet.id).where(TuneSet.title == title))
        ).scalar_one_or_none() is not None:
            skipped += 1
            continue
        try:
            tune_set = TuneSet(
                title=title,
                description=rec.get("description"),
                source=rec.get("source"),
                abc_header=rec.get("abc_header"),
                flow_difficulty=rec.get("flow_difficulty"),
                flow_difficulty_notes=rec.get("flow_difficulty_notes"),
            )
            db.add(tune_set)
            await db.flush()
            entry_warns = 0
            for order, member_rec in enumerate(rec.get("members", [])):
                tune_id = await _resolve_tune_id(db, member_rec["tune_title"])
                if tune_id is None:
                    print(f"    WARN tune not found: {member_rec['tune_title']!r}")
                    entry_warns += 1
                    continue
                setting_id = await _resolve_setting_id(db, tune_id, member_rec.get("setting_label"))
                db.add(TuneSetMember(set_id=tune_set.id, tune_id=tune_id, setting_id=setting_id, order=order))
            await db.commit()
            suffix = f" ({entry_warns} member warnings)" if entry_warns else ""
            print(f"  OK{suffix}  {title!r}")
            loaded += 1
        except Exception as exc:
            print(f"  ERR {title!r} — {exc}")
            errors += 1
    return loaded, skipped, errors


async def main(seeds_dir: Path) -> None:
    total_loaded = total_skipped = total_errors = 0

    steps = [
        ("tunes", "tunes.json", seed_tunes),
        ("warmups", "warmups.json", seed_warmups),
        ("boxes", "boxes.json", seed_boxes),
        ("lists", "lists.json", seed_lists),
        ("sets", "sets.json", seed_sets),
    ]

    async with AsyncSessionLocal() as db:
        for label, filename, fn in steps:
            records = _load(seeds_dir / filename)
            if records is None:
                print(f"\n{label}: (no {filename}, skipping)")
                continue
            print(f"\n{label}: {len(records)} records from {seeds_dir / filename}")
            ld, sk, er = await fn(db, records)
            total_loaded += ld
            total_skipped += sk
            total_errors += er

    print(f"\n{total_loaded} loaded   {total_skipped} skipped   {total_errors} errors")


if __name__ == "__main__":
    seeds_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent / "seeds"
    asyncio.run(main(seeds_dir))
