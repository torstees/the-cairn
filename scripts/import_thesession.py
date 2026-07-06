#!/usr/bin/env python
"""
Import TheSession.org reference data (tune settings, aliases, popularity)
into local side tables (TODO 8.1).

Downloads the CSVs fresh from TheSession-data's GitHub repo on every run —
nothing is vendored into this repo. These are pure read-only mirror tables
with no user-authored data mixed in, so each run fully replaces the
contents of each table (delete-all-then-bulk-reinsert) rather than tracking
per-row upserts; tunes.csv alone is tens of thousands of rows, so rows are
inserted in batches within one transaction per table, not one at a time.

No page in the app browses these tables directly — they exist to back the
tune-linking wizard (TODO 8.2). See TODO 8.4 for the remaining CSVs
(sets, recordings, venues, events), which this script does not touch.

Usage:
    uv run python scripts/import_thesession.py
    Also: make thesession-import
"""

import asyncio
import csv
import io
import sys
import urllib.request
from collections.abc import Iterable, Iterator
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import delete, insert

from cairn.database import AsyncSessionLocal
from cairn.models_thesession_tunes import TheSessionAlias, TheSessionSetting, TheSessionTunePopularity

_BASE_URL = "https://raw.githubusercontent.com/adactio/TheSession-data/main/csv"
_BATCH_SIZE = 2000


def _fetch_csv_rows(name: str) -> Iterator[dict]:
    """Stream-parse a CSV file fetched from TheSession-data's GitHub repo."""
    with urllib.request.urlopen(f"{_BASE_URL}/{name}.csv") as response:
        text_stream = io.TextIOWrapper(response, encoding="utf-8", newline="")
        yield from csv.DictReader(text_stream)


def _parse_date(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def parse_setting_row(row: dict) -> dict:
    """Map one tunes.csv row to TheSessionSetting column values."""
    return {
        "setting_id": int(row["setting_id"]),
        "tune_id": int(row["tune_id"]),
        "name": row["name"],
        "tune_type_raw": row["type"],
        "meter": row["meter"],
        "mode_raw": row["mode"],
        "abc": row["abc"],
        "submitted_date": _parse_date(row["date"]),
        "username": row["username"].strip() or None,
        "composer": row["composer"].strip() or None,
    }


def parse_alias_row(row: dict) -> dict:
    """Map one aliases.csv row to TheSessionAlias column values."""
    return {
        "tune_id": int(row["tune_id"]),
        "alias": row["alias"],
        "canonical_name": row["name"],
    }


def parse_tune_popularity_row(row: dict) -> dict:
    """Map one tune_popularity.csv row to TheSessionTunePopularity column values."""
    return {
        "tune_id": int(row["tune_id"]),
        "name": row["name"],
        "tunebooks": int(row["tunebooks"]),
    }


async def _replace_table(db, model, rows: Iterable[dict]) -> int:
    """Delete every existing row and bulk-insert `rows`, in one transaction."""
    await db.execute(delete(model))
    count = 0
    batch: list[dict] = []
    for row in rows:
        batch.append(row)
        count += 1
        if len(batch) >= _BATCH_SIZE:
            await db.execute(insert(model), batch)
            batch = []
    if batch:
        await db.execute(insert(model), batch)
    await db.commit()
    return count


async def import_settings(db, rows: Iterable[dict]) -> int:
    """Replace TheSessionSetting with the given already-parsed tunes.csv rows."""
    return await _replace_table(db, TheSessionSetting, (parse_setting_row(r) for r in rows))


async def import_aliases(db, rows: Iterable[dict]) -> int:
    """Replace TheSessionAlias with the given already-parsed aliases.csv rows."""
    return await _replace_table(db, TheSessionAlias, (parse_alias_row(r) for r in rows))


async def import_tune_popularity(db, rows: Iterable[dict]) -> int:
    """Replace TheSessionTunePopularity with the given already-parsed tune_popularity.csv rows."""
    return await _replace_table(db, TheSessionTunePopularity, (parse_tune_popularity_row(r) for r in rows))


async def main() -> None:
    async with AsyncSessionLocal() as db:
        print("Downloading tunes.csv ...")
        settings_count = await import_settings(db, _fetch_csv_rows("tunes"))
        print(f"  {settings_count} settings")

        print("Downloading aliases.csv ...")
        aliases_count = await import_aliases(db, _fetch_csv_rows("aliases"))
        print(f"  {aliases_count} aliases")

        print("Downloading tune_popularity.csv ...")
        popularity_count = await import_tune_popularity(db, _fetch_csv_rows("tune_popularity"))
        print(f"  {popularity_count} tune popularity rows")


if __name__ == "__main__":
    asyncio.run(main())
