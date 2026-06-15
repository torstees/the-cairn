#!/usr/bin/env python
"""
Import ABC files from a directory into The Cairn database.

Usage:
    uv run python scripts/import_abc.py [path/to/abc/dir]
    Defaults to !ABC/ relative to the project root.

Skips:
- Files whose name starts with 'set-' or 'set_' (multi-tune set files)
- Files missing R: (tune type unknown) or K: (key unknown) or music body
- Tunes whose title already exists in the database

For files with multiple X: blocks the first becomes the core setting;
additional blocks are added as alternate TuneSettings on the same tune.
"""
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from cairn.database import AsyncSessionLocal
from cairn.models import KeyMode, KeyRoot, OrnamentationLevel, Tune, TuneSetting, TuneType
from cairn.schemas import TuneCreate, TuneSettingCreate
from cairn.services.tunes import create_setting, create_tune

_MAPPED = frozenset("XTCOARMSZNK")

_KEY_ROOT_MAP: dict[str, KeyRoot] = {
    "c": KeyRoot.C, "c#": KeyRoot.C_sharp, "db": KeyRoot.D_flat,
    "d": KeyRoot.D, "eb": KeyRoot.E_flat, "e": KeyRoot.E,
    "f": KeyRoot.F, "f#": KeyRoot.F_sharp, "gb": KeyRoot.G_flat,
    "g": KeyRoot.G, "ab": KeyRoot.A_flat, "a": KeyRoot.A,
    "bb": KeyRoot.B_flat, "b": KeyRoot.B,
}

_KEY_MODE_MAP: dict[str, KeyMode] = {
    "": KeyMode.major, "maj": KeyMode.major, "major": KeyMode.major,
    "m": KeyMode.minor, "min": KeyMode.minor, "minor": KeyMode.minor,
    "dor": KeyMode.dorian, "dorian": KeyMode.dorian,
    "mix": KeyMode.mixolydian, "mixolydian": KeyMode.mixolydian,
    "lyd": KeyMode.lydian, "lydian": KeyMode.lydian,
}


def _parse_key(raw: str) -> tuple[KeyRoot, KeyMode] | None:
    """Parse K: values: 'Dmaj', 'Ador', 'Bbdor', 'A mixolydian', 'G', 'Bm', etc."""
    m = re.match(r'^([A-Ga-g][b#]?)\s*(.*)', raw.strip())
    if not m:
        return None
    root = _KEY_ROOT_MAP.get(m.group(1).lower())
    mode = _KEY_MODE_MAP.get(m.group(2).strip().lower())
    if root is None or mode is None:
        return None
    return root, mode


def _parse_time_sig(raw: str) -> str:
    """Normalise M: values: C → 4/4, C| → 2/2, others pass through."""
    v = raw.strip()
    if v == "C":
        return "4/4"
    if v in ("C|", "c|"):
        return "2/2"
    return v


def _split_blocks(text: str) -> list[str]:
    """Split file content on X: markers into individual tune blocks."""
    blocks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if re.match(r'^X\s*:', line) and current:
            blocks.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return [b for b in blocks if b.strip()]


def _parse_block(text: str) -> dict | None:
    """
    Parse one ABC tune block into {'headers': {...}, 'abc_notation': str}.
    Returns None if the block is missing T:, K:, or a music body.
    The first T: is used as the title; additional T: lines are ignored.
    For K:, the last value wins (some files declare K: twice).
    User headers (L:, D:, F:, etc.) are preserved in abc_notation.
    """
    first_title: str | None = None
    headers: dict[str, str] = {}
    user_headers: list[str] = []
    music_lines: list[str] = []
    in_music = False

    for line in text.splitlines():
        s = line.rstrip()
        if not in_music:
            if not s or s.startswith("%"):
                # blank lines and ABC comments before the music body → skip
                continue
            if len(s) >= 2 and s[1] == ":" and s[0].isalpha():
                key = s[0].upper()
                value = s[2:].strip()
                if key in _MAPPED:
                    if key == "T" and first_title is None:
                        first_title = value
                    elif key != "T":
                        headers[key] = value  # last wins (e.g. duplicate K:)
                else:
                    user_headers.append(s)
            else:
                in_music = True
                music_lines.append(s)
        else:
            music_lines.append(s)

    while music_lines and not music_lines[-1].strip():
        music_lines.pop()

    if first_title is None or "K" not in headers or not music_lines:
        return None

    headers["T"] = first_title

    # abc_notation = user headers + blank separator + music body
    parts: list[str] = user_headers[:]
    if music_lines:
        if parts:
            parts.append("")
        parts.extend(music_lines)
    abc_notation = "\n".join(parts).strip() + "\n"

    return {"headers": headers, "abc_notation": abc_notation}


def _build_tune_create(headers: dict[str, str]) -> TuneCreate | None:
    """Return a TuneCreate from parsed headers, or None if required fields are missing."""
    title = headers.get("T", "").strip()
    if not title:
        return None

    r_raw = headers.get("R", "").strip().lower().replace(" ", "_")
    try:
        tune_type = TuneType(r_raw)
    except ValueError:
        return None

    key_parsed = _parse_key(headers.get("K", ""))
    if key_parsed is None:
        return None
    key_root, key_mode = key_parsed

    return TuneCreate(
        title=title,
        tune_type=tune_type,
        key_root=key_root,
        key_mode=key_mode,
        time_signature=_parse_time_sig(headers.get("M", "4/4")),
        composer=headers.get("C") or None,
        origin=headers.get("O") or None,
        region=headers.get("A") or None,
        notes=headers.get("N") or None,
    )


async def main(abc_dir: Path) -> None:
    files = sorted(
        f for f in abc_dir.glob("*.abc")
        if not f.name.startswith(("set-", "set_"))
    )
    print(f"Found {len(files)} candidate files in {abc_dir}\n")

    imported = skipped_dup = skipped_err = 0
    warnings: list[str] = []

    async with AsyncSessionLocal() as db:
        for path in files:
            text = path.read_text(encoding="utf-8", errors="replace")
            raw_blocks = _split_blocks(text) or [text]

            primary: dict | None = None
            alternates: list[dict] = []
            for block in raw_blocks:
                parsed = _parse_block(block)
                if parsed is None:
                    continue
                if primary is None:
                    primary = parsed
                else:
                    alternates.append(parsed)

            if primary is None:
                warnings.append(f"SKIP (unparse)  {path.name}")
                skipped_err += 1
                continue

            tune_in = _build_tune_create(primary["headers"])
            if tune_in is None:
                h = primary["headers"]
                warnings.append(
                    f"SKIP (fields)   {path.name}"
                    f" — R:{h.get('R', '?')}  K:{h.get('K', '?')}"
                )
                skipped_err += 1
                continue

            # Dedup by title
            exists = (await db.execute(
                select(Tune.id).where(Tune.title == tune_in.title)
            )).scalar_one_or_none()
            if exists is not None:
                warnings.append(f"SKIP (dup)      {path.name} — \"{tune_in.title}\"")
                skipped_dup += 1
                continue

            # Create tune + core setting
            tune = await create_tune(
                db, tune_in,
                abc_notation=primary["abc_notation"],
                setting_label="Standard",
            )

            # Patch source / source_notes onto the core setting if present
            ph = primary["headers"]
            if ph.get("S") or ph.get("Z"):
                core = (await db.execute(
                    select(TuneSetting).where(
                        TuneSetting.tune_id == tune.id,
                        TuneSetting.is_core.is_(True),
                    )
                )).scalar_one_or_none()
                if core:
                    core.source = ph.get("S") or None
                    core.source_notes = ph.get("Z") or None
                    await db.commit()

            # Add alternate settings
            for i, alt in enumerate(alternates, 1):
                alt_title = alt["headers"].get("T", "").strip()
                label = (
                    alt_title
                    if alt_title and alt_title.lower() != tune_in.title.lower()
                    else f"Alternate {i}"
                )
                setting_in = TuneSettingCreate(
                    tune_id=tune.id,
                    label=label,
                    abc_notation=alt["abc_notation"],
                    source=alt["headers"].get("S") or None,
                    source_notes=alt["headers"].get("Z") or None,
                    ornamentation_level=OrnamentationLevel.none,
                )
                await create_setting(db, tune.id, setting_in)

            alt_msg = f"  +{len(alternates)} alt" if alternates else ""
            mode = f"{tune_in.key_root.value} {tune_in.key_mode.label}"
            print(f"  OK  {tune_in.title}  ({tune_in.tune_type.label}, {mode}){alt_msg}")
            imported += 1

    print(f"\n{imported} imported   {skipped_dup} duplicate   {skipped_err} errors")
    if warnings:
        print("\nWarnings / skipped:")
        for w in warnings:
            print(f"  {w}")


if __name__ == "__main__":
    abc_dir = (
        Path(sys.argv[1]) if len(sys.argv) > 1
        else Path(__file__).parent.parent / "!ABC"
    )
    if not abc_dir.is_dir():
        print(f"Error: {abc_dir} is not a directory", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(abc_dir))
