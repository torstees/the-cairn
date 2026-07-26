#!/usr/bin/env python
"""
Seed the database from the seeds/ directory.

Files read (if present, processed in dependency order — sets before boxes/lists,
since box/list set_entries reference sets by title):
  seeds/tunes.json    — Tune + TuneSetting + TuneDifficulty + TuneAlias
  seeds/warmups.json  — WarmupItem + WarmupInstrument
  seeds/sets.json     — TuneSet + TuneSetMember
  seeds/boxes.json    — TuneBox + TuneBoxInstrument + TuneBoxEntry + TuneBoxSetEntry
  seeds/lists.json    — PracticeList + TuneListEntry + TuneListSetEntry

Records are matched by natural key (title / name / label) and reconciled against
the seed record rather than skipped when they already exist: scalar fields are
overwritten, missing child records (settings, aliases, entries, ...) are added,
and child records no longer present in the seed record are removed. seeds/ is
the source of truth -- re-running this after editing/exporting seeds/ brings
the database in line with it. Cross-references are resolved by title / label /
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
    ContentVisibility,
    Instrument,
    KeyMode,
    KeyRoot,
    OrnamentationLevel,
    PracticeList,
    PracticeListType,
    ProgressStatus,
    Tune,
    TuneAlias,
    TuneBox,
    TuneBoxEntry,
    TuneBoxInstrument,
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
from cairn.schemas import TuneCreate, TuneDifficultyCreate
from cairn.services.tune_sets import (
    add_box_set,
    add_list_set,
    clear_box_set_difficulty,
    clear_list_set_difficulty,
    list_box_sets,
    list_list_sets,
    remove_box_set,
    remove_list_set,
    set_box_set_difficulty,
    set_list_set_difficulty,
    set_members,
)
from cairn.services.tunes import add_alias, create_tune, set_difficulty

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
        await db.execute(select(TuneSetting.id).where(TuneSetting.tune_id == tune_id, TuneSetting.label == label))
    ).scalar_one_or_none()


async def _resolve_alias_id(db, tune_id: int, name: str | None) -> int | None:
    if name is None:
        return None
    return (
        await db.execute(select(TuneAlias.id).where(TuneAlias.tune_id == tune_id, TuneAlias.name == name))
    ).scalar_one_or_none()


async def _resolve_set_id(db, title: str) -> int | None:
    return (await db.execute(select(TuneSet.id).where(TuneSet.title == title))).scalar_one_or_none()


async def _delete_stale(db, existing: list, keep_keys: set, key_fn, guard=None) -> int:
    """Delete any of existing whose key_fn(obj) isn't in keep_keys -- the
    common "remove children no longer present in the seed record" half of
    reconciliation. If guard is given, it's awaited per candidate and, if it
    returns True, the deletion is skipped and reported as a warning instead
    of going through -- this app's sqlite connections don't enable
    PRAGMA foreign_keys, so a stale setting/alias still pointed to by a
    box/list/set entry would otherwise be silently deleted out from under
    that reference rather than caught. Returns the warning count.
    """
    warns = 0
    for obj in existing:
        if key_fn(obj) in keep_keys:
            continue
        if guard is not None and await guard(obj):
            print(f"    WARN not removing {key_fn(obj)!r} — still referenced elsewhere")
            warns += 1
            continue
        await db.delete(obj)
    await db.commit()
    return warns


async def _setting_still_referenced(db, setting_id: int) -> bool:
    for col in (TuneBoxEntry.setting_id, TuneListEntry.setting_id, TuneSetMember.setting_id):
        if (await db.execute(select(col).where(col == setting_id))).first() is not None:
            return True
    return False


async def _alias_still_referenced(db, alias_id: int) -> bool:
    for col in (TuneBoxEntry.display_alias_id, TuneListEntry.display_alias_id):
        if (await db.execute(select(col).where(col == alias_id))).first() is not None:
            return True
    return False


async def _sync_set_entries(
    db, records: list, list_existing, add_set, remove_set, set_diff, clear_diff, entity_id: int
) -> int:
    """Shared by seed_boxes/seed_lists: reconcile embedded TuneSet entries
    (add missing, remove stale, sync each entry's difficulty override)
    against set_entries records resolved by set title -- requires
    seed_sets() to have already run (see step order in main()). Returns a
    warning count for set titles that don't resolve to an existing TuneSet.
    """
    warns = 0
    existing = await list_existing(db, entity_id)
    existing_set_ids = {se.set_id for se in existing}
    keep_set_ids = set()
    for se_rec in records:
        set_id = await _resolve_set_id(db, se_rec["set_title"])
        if set_id is None:
            print(f"    WARN set not found: {se_rec['set_title']!r}")
            warns += 1
            continue
        keep_set_ids.add(set_id)
        if set_id not in existing_set_ids:
            await add_set(db, entity_id, set_id)
        if se_rec.get("difficulty_override") is not None:
            await set_diff(db, entity_id, set_id, se_rec["difficulty_override"])
        else:
            await clear_diff(db, entity_id, set_id)
    for se in existing:
        if se.set_id not in keep_set_ids:
            await remove_set(db, entity_id, se.set_id)
    return warns


async def seed_tunes(db, records: list) -> tuple[int, int, int]:
    created = updated = errors = 0
    for rec in records:
        title = rec["title"]
        try:
            existing_tune = (await db.execute(select(Tune).where(Tune.title == title))).scalar_one_or_none()
            is_new = existing_tune is None

            if is_new:
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
                        visibility=ContentVisibility(rec.get("visibility", ContentVisibility.public.value)),
                    ),
                    abc_notation=core_setting["abc_notation"],
                    setting_label=core_setting["label"],
                )
            else:
                tune = existing_tune
                tune.tune_type = TuneType(rec["tune_type"])
                tune.key_root = KeyRoot(rec["key_root"])
                tune.key_mode = KeyMode(rec["key_mode"])
                tune.time_signature = rec.get("time_signature", "4/4")
                tune.composer = rec.get("composer")
                tune.origin = rec.get("origin")
                tune.region = rec.get("region")
                tune.notes = rec.get("notes")
                tune.visibility = ContentVisibility(rec.get("visibility", ContentVisibility.public.value))
            # thesession_tune_id/username aren't on TuneCreate (permanent attribution
            # link set directly by services/thesession_link.py, not a user-editable
            # field) -- set them the same way here, for both branches.
            tune.thesession_tune_id = rec.get("thesession_tune_id")
            tune.thesession_username = rec.get("thesession_username")
            await db.commit()

            existing_settings = (
                (await db.execute(select(TuneSetting).where(TuneSetting.tune_id == tune.id))).scalars().all()
            )
            existing_by_label = {s.label: s for s in existing_settings}
            for s in rec["settings"]:
                row = existing_by_label.get(s["label"])
                if row is None:
                    row = TuneSetting(tune_id=tune.id, label=s["label"])
                    db.add(row)
                row.abc_notation = s["abc_notation"]
                row.is_core = s["is_core"]
                row.instrument = Instrument(s["instrument"]) if s.get("instrument") else None
                row.source = s.get("source")
                row.source_notes = s.get("source_notes")
                row.ornamentation_level = OrnamentationLevel(s.get("ornamentation_level", "none"))
                row.mutation_notation = s.get("mutation_notation")
                row.visibility = ContentVisibility(s.get("visibility", ContentVisibility.public.value))
                row.thesession_setting_id = s.get("thesession_setting_id")
                row.thesession_username = s.get("thesession_username")
            await db.commit()
            warns = await _delete_stale(
                db,
                existing_settings,
                {s["label"] for s in rec["settings"]},
                lambda x: x.label,
                guard=lambda x: _setting_still_referenced(db, x.id),
            )

            existing_difficulties = (
                (await db.execute(select(TuneDifficulty).where(TuneDifficulty.tune_id == tune.id))).scalars().all()
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
            await _delete_stale(
                db,
                existing_difficulties,
                {d["instrument"] for d in rec.get("difficulties", [])},
                lambda x: x.instrument.value,
            )

            existing_aliases = (await db.execute(select(TuneAlias).where(TuneAlias.tune_id == tune.id))).scalars().all()
            existing_alias_by_name = {a.name: a for a in existing_aliases}
            for a in rec.get("aliases", []):
                row = existing_alias_by_name.get(a["name"])
                if row is None:
                    await add_alias(db, tune.id, a["name"], a.get("notes"))
                elif row.notes != a.get("notes"):
                    row.notes = a.get("notes")
                    await db.commit()
            warns += await _delete_stale(
                db,
                existing_aliases,
                {a["name"] for a in rec.get("aliases", [])},
                lambda x: x.name,
                guard=lambda x: _alias_still_referenced(db, x.id),
            )

            suffix = f" ({warns} warnings)" if warns else ""
            print(f"  {'NEW' if is_new else 'UPD'}{suffix}  {title!r}")
            created += is_new
            updated += not is_new
        except Exception as exc:
            print(f"  ERR {title!r} — {exc}")
            errors += 1
    return created, updated, errors


async def seed_warmups(db, records: list) -> tuple[int, int, int]:
    created = updated = errors = 0
    for rec in records:
        title = rec["title"]
        try:
            existing = (await db.execute(select(WarmupItem).where(WarmupItem.title == title))).scalar_one_or_none()
            is_new = existing is None
            warmup = existing
            if is_new:
                warmup = WarmupItem(title=title)
                db.add(warmup)
            warmup.warmup_type = WarmupType(rec["warmup_type"])
            warmup.content = rec["content"]
            warmup.difficulty = rec["difficulty"]
            warmup.default_tempo = rec.get("default_tempo")
            await db.flush()

            existing_instruments = (
                (await db.execute(select(WarmupInstrument).where(WarmupInstrument.warmup_id == warmup.id)))
                .scalars()
                .all()
            )
            existing_values = {i.instrument.value for i in existing_instruments}
            for inst_val in rec.get("instruments", []):
                if inst_val not in existing_values:
                    db.add(WarmupInstrument(warmup_id=warmup.id, instrument=Instrument(inst_val)))
            await db.commit()
            await _delete_stale(db, existing_instruments, set(rec.get("instruments", [])), lambda x: x.instrument.value)

            print(f"  {'NEW' if is_new else 'UPD'}  {title!r}")
            created += is_new
            updated += not is_new
        except Exception as exc:
            print(f"  ERR {title!r} — {exc}")
            errors += 1
    return created, updated, errors


async def seed_boxes(db, records: list) -> tuple[int, int, int]:
    created = updated = errors = 0
    for rec in records:
        name = rec["name"]
        try:
            existing = (
                await db.execute(select(TuneBox).where(TuneBox.user_id == _STUB_USER_ID, TuneBox.name == name))
            ).scalar_one_or_none()
            is_new = existing is None
            box = existing
            if is_new:
                box = TuneBox(user_id=_STUB_USER_ID, name=name)
                db.add(box)
            await db.flush()

            existing_instruments = (
                (await db.execute(select(TuneBoxInstrument).where(TuneBoxInstrument.box_id == box.id))).scalars().all()
            )
            existing_inst_values = {i.instrument.value for i in existing_instruments}
            for inst_val in rec.get("instruments", []):
                if inst_val not in existing_inst_values:
                    db.add(TuneBoxInstrument(box_id=box.id, instrument=Instrument(inst_val)))
            await db.flush()
            await _delete_stale(db, existing_instruments, set(rec.get("instruments", [])), lambda x: x.instrument.value)

            warns = 0
            existing_entries = (
                (await db.execute(select(TuneBoxEntry).where(TuneBoxEntry.box_id == box.id))).scalars().all()
            )
            existing_by_tune = {e.tune_id: e for e in existing_entries}
            keep_tune_ids = set()
            for entry_rec in rec.get("entries", []):
                tune_id = await _resolve_tune_id(db, entry_rec["tune_title"])
                if tune_id is None:
                    print(f"    WARN tune not found: {entry_rec['tune_title']!r}")
                    warns += 1
                    continue
                keep_tune_ids.add(tune_id)
                row = existing_by_tune.get(tune_id)
                if row is None:
                    row = TuneBoxEntry(box_id=box.id, tune_id=tune_id)
                    db.add(row)
                row.setting_id = await _resolve_setting_id(db, tune_id, entry_rec.get("setting_label"))
                row.display_alias_id = await _resolve_alias_id(db, tune_id, entry_rec.get("display_alias_name"))
                row.transpose_key_root = (
                    KeyRoot(entry_rec["transpose_key_root"]) if entry_rec.get("transpose_key_root") else None
                )
                row.transpose_octave = entry_rec.get("transpose_octave", 0)
            await db.commit()
            await _delete_stale(db, existing_entries, keep_tune_ids, lambda x: x.tune_id)

            warns += await _sync_set_entries(
                db,
                rec.get("set_entries", []),
                list_box_sets,
                add_box_set,
                remove_box_set,
                set_box_set_difficulty,
                clear_box_set_difficulty,
                box.id,
            )

            suffix = f" ({warns} warnings)" if warns else ""
            print(f"  {'NEW' if is_new else 'UPD'}{suffix}  {name!r}")
            created += is_new
            updated += not is_new
        except Exception as exc:
            print(f"  ERR {name!r} — {exc}")
            errors += 1
    return created, updated, errors


async def seed_lists(db, records: list) -> tuple[int, int, int]:
    created = updated = errors = 0
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
        try:
            existing = (
                await db.execute(
                    select(PracticeList).where(
                        PracticeList.user_id == _STUB_USER_ID,
                        PracticeList.box_id == box_id,
                        PracticeList.name == name,
                    )
                )
            ).scalar_one_or_none()
            is_new = existing is None
            pl = existing
            if is_new:
                pl = PracticeList(user_id=_STUB_USER_ID, box_id=box_id, name=name)
                db.add(pl)
            pl.list_type = PracticeListType(rec["list_type"])
            pl.progress_goal = ProgressStatus(rec["progress_goal"])
            pl.target_date = date.fromisoformat(rec["target_date"]) if rec.get("target_date") else None
            pl.is_active = rec.get("is_active", False)
            await db.flush()

            warns = 0
            existing_entries = (
                (await db.execute(select(TuneListEntry).where(TuneListEntry.list_id == pl.id))).scalars().all()
            )
            existing_by_tune = {e.tune_id: e for e in existing_entries}
            keep_tune_ids = set()
            for entry_rec in rec.get("entries", []):
                tune_id = await _resolve_tune_id(db, entry_rec["tune_title"])
                if tune_id is None:
                    print(f"    WARN tune not found: {entry_rec['tune_title']!r}")
                    warns += 1
                    continue
                keep_tune_ids.add(tune_id)
                row = existing_by_tune.get(tune_id)
                if row is None:
                    row = TuneListEntry(list_id=pl.id, tune_id=tune_id)
                    db.add(row)
                row.setting_id = await _resolve_setting_id(db, tune_id, entry_rec.get("setting_label"))
                row.display_alias_id = await _resolve_alias_id(db, tune_id, entry_rec.get("display_alias_name"))
                row.transpose_key_root = (
                    KeyRoot(entry_rec["transpose_key_root"]) if entry_rec.get("transpose_key_root") else None
                )
                row.transpose_octave = entry_rec.get("transpose_octave", 0)
                row.is_focus = entry_rec.get("is_focus", False)
            await db.commit()
            await _delete_stale(db, existing_entries, keep_tune_ids, lambda x: x.tune_id)

            warns += await _sync_set_entries(
                db,
                rec.get("set_entries", []),
                list_list_sets,
                add_list_set,
                remove_list_set,
                set_list_set_difficulty,
                clear_list_set_difficulty,
                pl.id,
            )

            suffix = f" ({warns} warnings)" if warns else ""
            print(f"  {'NEW' if is_new else 'UPD'}{suffix}  {name!r}")
            created += is_new
            updated += not is_new
        except Exception as exc:
            print(f"  ERR {name!r} — {exc}")
            errors += 1
    return created, updated, errors


async def seed_sets(db, records: list) -> tuple[int, int, int]:
    created = updated = errors = 0
    for rec in records:
        title = rec["title"]
        try:
            existing_id = (await db.execute(select(TuneSet.id).where(TuneSet.title == title))).scalar_one_or_none()
            is_new = existing_id is None
            if is_new:
                tune_set = TuneSet(title=title)
                db.add(tune_set)
                await db.flush()
            else:
                tune_set = await db.get(TuneSet, existing_id)
            tune_set.description = rec.get("description")
            tune_set.source = rec.get("source")
            tune_set.abc_header = rec.get("abc_header")
            tune_set.flow_difficulty = rec.get("flow_difficulty")
            tune_set.flow_difficulty_notes = rec.get("flow_difficulty_notes")
            await db.commit()

            warns = 0
            member_data = []
            for member_rec in rec.get("members", []):
                tune_id = await _resolve_tune_id(db, member_rec["tune_title"])
                if tune_id is None:
                    print(f"    WARN tune not found: {member_rec['tune_title']!r}")
                    warns += 1
                    continue
                setting_id = await _resolve_setting_id(db, tune_id, member_rec.get("setting_label"))
                member_data.append({"tune_id": tune_id, "setting_id": setting_id})
            # set_members() replaces the full member list in one shot (delete all,
            # recreate from member_data) -- already exactly the reconciliation
            # semantics wanted here, for both a new and an already-seeded set.
            await set_members(db, tune_set.id, member_data)

            suffix = f" ({warns} warnings)" if warns else ""
            print(f"  {'NEW' if is_new else 'UPD'}{suffix}  {title!r}")
            created += is_new
            updated += not is_new
        except Exception as exc:
            print(f"  ERR {title!r} — {exc}")
            errors += 1
    return created, updated, errors


async def main(seeds_dir: Path) -> None:
    total_created = total_updated = total_errors = 0

    steps = [
        ("tunes", "tunes.json", seed_tunes),
        ("warmups", "warmups.json", seed_warmups),
        # sets before boxes/lists: box/list set_entries resolve set titles that
        # must already exist (#267).
        ("sets", "sets.json", seed_sets),
        ("boxes", "boxes.json", seed_boxes),
        ("lists", "lists.json", seed_lists),
    ]

    async with AsyncSessionLocal() as db:
        for label, filename, fn in steps:
            records = _load(seeds_dir / filename)
            if records is None:
                print(f"\n{label}: (no {filename}, skipping)")
                continue
            print(f"\n{label}: {len(records)} records from {seeds_dir / filename}")
            cr, up, er = await fn(db, records)
            total_created += cr
            total_updated += up
            total_errors += er

    print(f"\n{total_created} created   {total_updated} updated   {total_errors} errors")


if __name__ == "__main__":
    seeds_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent / "seeds"
    asyncio.run(main(seeds_dir))
