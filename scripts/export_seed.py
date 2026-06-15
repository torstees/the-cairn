#!/usr/bin/env python
"""
Export all tunes from the database to seeds/tunes.json.

Usage:
    uv run python scripts/export_seed.py [output_path]
    Defaults to seeds/tunes.json relative to the project root.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from cairn.database import AsyncSessionLocal
from cairn.services.tunes import list_tunes


async def main(out_path: Path) -> None:
    async with AsyncSessionLocal() as db:
        tunes = await list_tunes(db)

    records = []
    for tune in tunes:
        settings = []
        for s in tune.settings:
            settings.append({
                "label": s.label,
                "abc_notation": s.abc_notation,
                "is_core": s.is_core,
                "instrument": s.instrument.value if s.instrument else None,
                "source": s.source,
                "source_notes": s.source_notes,
                "ornamentation_level": s.ornamentation_level.value,
                "mutation_notation": s.mutation_notation,
            })

        difficulties = []
        for d in tune.difficulties:
            difficulties.append({
                "instrument": d.instrument.value,
                "difficulty": d.difficulty,
                "notes": d.notes,
            })

        records.append({
            "title": tune.title,
            "tune_type": tune.tune_type.value,
            "key_root": tune.key_root.value,
            "key_mode": tune.key_mode.value,
            "time_signature": tune.time_signature,
            "composer": tune.composer,
            "origin": tune.origin,
            "region": tune.region,
            "notes": tune.notes,
            "settings": settings,
            "difficulties": difficulties,
        })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Exported {len(records)} tunes to {out_path}")


if __name__ == "__main__":
    out_path = (
        Path(sys.argv[1]) if len(sys.argv) > 1
        else Path(__file__).parent.parent / "seeds" / "tunes.json"
    )
    asyncio.run(main(out_path))
