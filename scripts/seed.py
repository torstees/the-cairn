#!/usr/bin/env python
"""
Seed the database from seeds/tunes.json.

Usage:
    uv run python scripts/seed.py [input_path]
    Defaults to seeds/tunes.json relative to the project root.

Skips tunes whose title already exists (safe to re-run).
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from cairn.database import AsyncSessionLocal
from cairn.models import Instrument, KeyMode, KeyRoot, OrnamentationLevel, Tune, TuneSetting, TuneType
from cairn.schemas import TuneCreate, TuneDifficultyCreate, TuneSettingCreate
from cairn.services.tunes import create_setting, create_tune, set_difficulty


async def main(seed_path: Path) -> None:
    records = json.loads(seed_path.read_text(encoding="utf-8"))
    print(f"Seeding {len(records)} tunes from {seed_path}\n")

    loaded = skipped = errors = 0

    async with AsyncSessionLocal() as db:
        for rec in records:
            title = rec["title"]

            exists = (await db.execute(
                select(Tune.id).where(Tune.title == title)
            )).scalar_one_or_none()
            if exists is not None:
                print(f"  SKIP (dup)  {title!r}")
                skipped += 1
                continue

            try:
                # Find the core setting first
                core_setting = next(
                    (s for s in rec["settings"] if s["is_core"]),
                    rec["settings"][0] if rec["settings"] else None,
                )
                if core_setting is None:
                    raise ValueError("no settings")

                tune_in = TuneCreate(
                    title=title,
                    tune_type=TuneType(rec["tune_type"]),
                    key_root=KeyRoot(rec["key_root"]),
                    key_mode=KeyMode(rec["key_mode"]),
                    time_signature=rec.get("time_signature", "4/4"),
                    composer=rec.get("composer"),
                    origin=rec.get("origin"),
                    region=rec.get("region"),
                    notes=rec.get("notes"),
                )
                tune = await create_tune(
                    db, tune_in,
                    abc_notation=core_setting["abc_notation"],
                    setting_label=core_setting["label"],
                )

                # Patch source/source_notes on the core setting
                if core_setting.get("source") or core_setting.get("source_notes"):
                    core_row = (await db.execute(
                        select(TuneSetting).where(
                            TuneSetting.tune_id == tune.id,
                            TuneSetting.is_core.is_(True),
                        )
                    )).scalar_one_or_none()
                    if core_row:
                        core_row.source = core_setting.get("source")
                        core_row.source_notes = core_setting.get("source_notes")
                        await db.commit()

                # Alternate settings
                for s in rec["settings"]:
                    if s["is_core"]:
                        continue
                    setting_in = TuneSettingCreate(
                        tune_id=tune.id,
                        label=s["label"],
                        abc_notation=s["abc_notation"],
                        instrument=Instrument(s["instrument"]) if s.get("instrument") else None,
                        source=s.get("source"),
                        source_notes=s.get("source_notes"),
                        ornamentation_level=OrnamentationLevel(s.get("ornamentation_level", "none")),
                        mutation_notation=s.get("mutation_notation"),
                    )
                    await create_setting(db, tune.id, setting_in)

                # Difficulties
                for d in rec.get("difficulties", []):
                    diff_in = TuneDifficultyCreate(
                        tune_id=tune.id,
                        instrument=Instrument(d["instrument"]),
                        difficulty=d["difficulty"],
                        notes=d.get("notes"),
                    )
                    await set_difficulty(db, tune.id, diff_in)

                print(f"  OK  {title!r}")
                loaded += 1

            except Exception as exc:
                print(f"  ERR {title!r} — {exc}")
                errors += 1

    print(f"\n{loaded} loaded   {skipped} skipped   {errors} errors")


if __name__ == "__main__":
    seed_path = (
        Path(sys.argv[1]) if len(sys.argv) > 1
        else Path(__file__).parent.parent / "seeds" / "tunes.json"
    )
    if not seed_path.exists():
        print(f"Error: {seed_path} not found", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(seed_path))
