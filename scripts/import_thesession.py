#!/usr/bin/env python
"""
Import TheSession.org reference data into local side tables: tune settings,
aliases, and popularity (TODO 8.1) plus community data -- sets, recordings,
venues, events (TODO 8.4).

Downloads the CSVs fresh from TheSession-data's GitHub repo on every run —
nothing is vendored into this repo. These are pure read-only mirror tables
with no user-authored data mixed in, so each run fully replaces the
contents of each table (delete-all-then-bulk-reinsert) rather than tracking
per-row upserts; tunes.csv alone is tens of thousands of rows, so rows are
inserted in batches within one transaction per table, not one at a time.

No page in the app browses these tables directly — the 8.1 group exists to
back the tune-linking wizard (TODO 8.2); the 8.4 group (community data) has
no consumer yet at all, imported purely so it's available to query later
without a re-import project.

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
from cairn.models_thesession_community import (
    TheSessionEvent,
    TheSessionRecording,
    TheSessionSet,
    TheSessionSetMember,
    TheSessionVenue,
)
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


def parse_set_header_row(row: dict) -> dict:
    """Map one sets.csv row to TheSessionSet column values.

    Every row of the same `tuneset` shares these same header fields — see
    import_sets() for the per-tuneset deduplication.
    """
    return {
        "tuneset_id": int(row["tuneset"]),
        "submitted_date": _parse_date(row["date"]),
        "member_id": int(row["member_id"]),
        "username": row["username"],
        "name": row["name"],
    }


def parse_set_member_row(row: dict) -> dict:
    """Map one sets.csv row to TheSessionSetMember column values."""
    return {
        "tuneset_id": int(row["tuneset"]),
        "position": int(row["settingorder"]),
        "tune_id": int(row["tune_id"]),
        "setting_id": int(row["setting_id"]),
    }


def parse_recording_row(row: dict) -> dict:
    """Map one recordings.csv row to TheSessionRecording column values.

    `artist` is stored as-is -- real current data is the artist's name as a
    plain string in all but a small legacy fraction still holding a bare
    numeric id (see the model's docstring).
    """
    return {
        "recording_id": int(row["id"]),
        "artist": row["artist"],
        "recording_name": row["recording"],
        "track_number": int(row["track"]),
        "position": int(row["number"]),
        "tune_name": row["tune"],
        "tune_id": int(row["tune_id"]) if row["tune_id"].strip() else None,
    }


def parse_venue_row(row: dict) -> dict:
    """Map one sessions.csv row to TheSessionVenue column values."""
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "address": row["address"].strip() or None,
        "town": row["town"].strip() or None,
        "area": row["area"].strip() or None,
        "country": row["country"].strip() or None,
        "latitude": float(row["latitude"]) if row["latitude"].strip() else None,
        "longitude": float(row["longitude"]) if row["longitude"].strip() else None,
        "submitted_date": _parse_date(row["date"]),
    }


def parse_event_row(row: dict) -> dict:
    """Map one events.csv row to TheSessionEvent column values."""
    return {
        "id": int(row["id"]),
        "name": row["event"],
        "starts_at": _parse_date(row["dtstart"]),
        "ends_at": _parse_date(row["dtend"]),
        "venue_name": row["venue"].strip() or None,
        "address": row["address"].strip() or None,
        "town": row["town"].strip() or None,
        "area": row["area"].strip() or None,
        "country": row["country"].strip() or None,
        "latitude": float(row["latitude"]) if row["latitude"].strip() else None,
        "longitude": float(row["longitude"]) if row["longitude"].strip() else None,
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


async def import_sets(db, rows: Iterable[dict]) -> tuple[int, int]:
    """Replace TheSessionSet and TheSessionSetMember from the given already-parsed sets.csv rows.

    One sets.csv row is one member tune of a set; the per-tuneset header
    fields (date/member_id/username/name) repeat across every member row
    sharing one `tuneset` id and are deduplicated into a single
    TheSessionSet row per tuneset here — the first row seen for a given
    tuneset wins (real data doesn't vary these fields across a set's own
    rows). Header rows are flushed ahead of each member batch (and once
    more at the end) so a set's own header is always inserted before its
    members, matching TheSessionSetMember.tuneset_id's FK.
    """
    await db.execute(delete(TheSessionSetMember))
    await db.execute(delete(TheSessionSet))

    seen_tunesets: set[int] = set()
    header_batch: list[dict] = []
    member_batch: list[dict] = []
    members_count = 0

    for row in rows:
        tuneset_id = int(row["tuneset"])
        if tuneset_id not in seen_tunesets:
            seen_tunesets.add(tuneset_id)
            header_batch.append(parse_set_header_row(row))
        member_batch.append(parse_set_member_row(row))
        members_count += 1
        if len(member_batch) >= _BATCH_SIZE:
            if header_batch:
                await db.execute(insert(TheSessionSet), header_batch)
                header_batch = []
            await db.execute(insert(TheSessionSetMember), member_batch)
            member_batch = []

    if header_batch:
        await db.execute(insert(TheSessionSet), header_batch)
    if member_batch:
        await db.execute(insert(TheSessionSetMember), member_batch)

    await db.commit()
    return len(seen_tunesets), members_count


async def import_recordings(db, rows: Iterable[dict]) -> int:
    """Replace TheSessionRecording with the given already-parsed recordings.csv rows."""
    return await _replace_table(db, TheSessionRecording, (parse_recording_row(r) for r in rows))


async def import_venues(db, rows: Iterable[dict]) -> int:
    """Replace TheSessionVenue with the given already-parsed sessions.csv rows."""
    return await _replace_table(db, TheSessionVenue, (parse_venue_row(r) for r in rows))


async def import_events(db, rows: Iterable[dict]) -> int:
    """Replace TheSessionEvent with the given already-parsed events.csv rows."""
    return await _replace_table(db, TheSessionEvent, (parse_event_row(r) for r in rows))


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

        print("Downloading sets.csv ...")
        sets_count, set_members_count = await import_sets(db, _fetch_csv_rows("sets"))
        print(f"  {sets_count} sets, {set_members_count} set members")

        print("Downloading recordings.csv ...")
        recordings_count = await import_recordings(db, _fetch_csv_rows("recordings"))
        print(f"  {recordings_count} recordings")

        print("Downloading sessions.csv ...")
        venues_count = await import_venues(db, _fetch_csv_rows("sessions"))
        print(f"  {venues_count} venues")

        print("Downloading events.csv ...")
        events_count = await import_events(db, _fetch_csv_rows("events"))
        print(f"  {events_count} events")


if __name__ == "__main__":
    asyncio.run(main())
