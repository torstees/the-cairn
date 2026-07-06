"""Service logic for the TheSession.org tune-linking wizard (TODO 8.2)."""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import KeyMode, KeyRoot, Tune, TuneAlias, TuneSetting, TuneType
from cairn.models_thesession_tunes import TheSessionAlias, TheSessionSetting, TheSessionTunePopularity
from cairn.services.abc_utils import ABC_MODE_SUFFIX, parse_key
from cairn.services.tunes import TUNE_FAMILIES, core_setting, existing_alias_names, get_tune, sort_key

# TheSession's type vocabulary matches ours 1:1 except "slip jig" (space, not
# underscore). Two of our types (mazurka, three_two) exist only to receive
# TheSession data — see TODO 8.1's mapping notes. Our own "air" has no
# TheSession equivalent, so it's intentionally absent here.
_RAW_TO_TUNE_TYPE: dict[str, TuneType] = {
    "barndance": TuneType.barndance,
    "hornpipe": TuneType.hornpipe,
    "slip jig": TuneType.slip_jig,
    "polka": TuneType.polka,
    "reel": TuneType.reel,
    "jig": TuneType.jig,
    "march": TuneType.march,
    "mazurka": TuneType.mazurka,
    "slide": TuneType.slide,
    "strathspey": TuneType.strathspey,
    "three-two": TuneType.three_two,
    "waltz": TuneType.waltz,
}
_TUNE_TYPE_TO_RAW: dict[TuneType, str] = {v: k for k, v in _RAW_TO_TUNE_TYPE.items()}


def raw_to_tune_type(raw: str) -> TuneType | None:
    return _RAW_TO_TUNE_TYPE.get(raw.strip().lower())


def tune_type_to_raw(tune_type: TuneType) -> str:
    return _TUNE_TYPE_TO_RAW.get(tune_type, tune_type.value)


def build_thesession_preview_abc(setting: TheSessionSetting, x: int = 1) -> str:
    """Assemble a minimal ABC string (headers + body) so a TheSessionSetting can be
    rendered by ABCJS — TheSessionSetting.abc is the music body only, same convention
    as our own TuneSetting.abc_notation."""
    parsed = parse_key(setting.mode_raw)
    key_line = f"K:{parsed[0].value}{ABC_MODE_SUFFIX[parsed[1].value]}" if parsed else "K:C"
    return f"X:{x}\nT:{setting.name}\nM:{setting.meter}\n{key_line}\n{setting.abc}"


def split_settings_by_key_match(
    settings: list[TheSessionSetting], key_root: KeyRoot, key_mode: KeyMode
) -> tuple[list[TheSessionSetting], list[TheSessionSetting]]:
    """Split settings into (same key/mode as the tune, everything else).

    A setting whose mode_raw doesn't parse is treated as non-matching rather
    than raising, since Step 3 of the wizard must still be able to show it
    under "show all".
    """
    matching: list[TheSessionSetting] = []
    other: list[TheSessionSetting] = []
    for setting in settings:
        parsed = parse_key(setting.mode_raw)
        (matching if parsed == (key_root, key_mode) else other).append(setting)
    return matching, other


def _escape_like(value: str) -> str:
    """Escape LIKE/ILIKE metacharacters so user text is matched literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _dedupe_by_tune_id(rows: list[TheSessionSetting], limit: int) -> list[TheSessionSetting]:
    seen: dict[int, TheSessionSetting] = {}
    for row in rows:
        if row.tune_id not in seen:
            seen[row.tune_id] = row
        if len(seen) >= limit:
            break
    return list(seen.values())


async def search_thesession_tunes(
    db: AsyncSession,
    q: str = "",
    tune_type: TuneType | None = None,
    family: str | None = None,
    limit: int = 100,
) -> list[TheSessionSetting]:
    """Return up to `limit` distinct tunes (one representative setting row each).

    A tune_id can have many setting rows (a popular session tune may have
    dozens), so naively deduping an overfetched, popularity-ordered batch in
    Python can under-fill results — the front of that order is dominated by a
    handful of very popular tunes' many settings. The no-search-text (browse
    by popularity) path avoids this by starting from `TheSessionTunePopularity`
    (one row per tune, so ordering it costs nothing extra) and only fetching
    matching settings for the tune_ids it surfaces, rather than ranking the
    full ~55k-row settings table. The free-text path keeps a bounded
    overfetch-and-dedupe instead, since a text match already narrows the
    candidate set enough in practice, and a SQL-side rank/dedupe (e.g. a
    window function) was measured to cost seconds rather than milliseconds
    over the full table on this dataset.
    """
    type_filter = None
    if tune_type is not None:
        type_filter = TheSessionSetting.tune_type_raw == tune_type_to_raw(tune_type)
    elif family is not None:
        raw_types = [tune_type_to_raw(t) for t in TUNE_FAMILIES.get(family, [])]
        if raw_types:
            type_filter = TheSessionSetting.tune_type_raw.in_(raw_types)

    if q:
        escaped = _escape_like(q)
        alias_tune_ids = select(TheSessionAlias.tune_id).where(TheSessionAlias.alias.ilike(f"%{escaped}%", escape="\\"))
        stmt = select(TheSessionSetting).where(
            or_(
                TheSessionSetting.name.ilike(f"%{escaped}%", escape="\\"), TheSessionSetting.tune_id.in_(alias_tune_ids)
            )
        )
        if type_filter is not None:
            stmt = stmt.where(type_filter)
        stmt = stmt.order_by(TheSessionSetting.name).limit(limit * 10)
        rows = (await db.execute(stmt)).scalars().all()
        return _dedupe_by_tune_id(rows, limit)

    pop_tune_ids = list(
        (
            await db.execute(
                select(TheSessionTunePopularity.tune_id)
                .order_by(TheSessionTunePopularity.tunebooks.desc())
                .limit(limit * 5)
            )
        ).scalars()
    )
    ordered: list[TheSessionSetting] = []
    if pop_tune_ids:
        stmt = select(TheSessionSetting).where(TheSessionSetting.tune_id.in_(pop_tune_ids))
        if type_filter is not None:
            stmt = stmt.where(type_filter)
        rows = (await db.execute(stmt)).scalars().all()
        by_tune_id = {row.tune_id: row for row in rows}
        ordered = [by_tune_id[tid] for tid in pop_tune_ids if tid in by_tune_id][:limit]

    # Roughly half of tunes have no tune_popularity.csv entry at all (e.g.
    # rarely-tunebooked ones), which the popularity-first pass above can
    # never surface. Only fall back to a bounded scan of the rest when the
    # popularity pass didn't already fill `limit` — the common case (a
    # popular-enough tune matches) never pays this extra cost.
    if len(ordered) < limit:
        stmt = select(TheSessionSetting)
        if pop_tune_ids:
            stmt = stmt.where(TheSessionSetting.tune_id.not_in(pop_tune_ids))
        if type_filter is not None:
            stmt = stmt.where(type_filter)
        needed = limit - len(ordered)
        rows = (await db.execute(stmt.order_by(TheSessionSetting.name).limit(needed * 10))).scalars().all()
        ordered.extend(_dedupe_by_tune_id(rows, needed))

    return ordered[:limit]


async def get_thesession_aliases(db: AsyncSession, external_tune_id: int) -> list[TheSessionAlias]:
    result = await db.execute(
        select(TheSessionAlias).where(TheSessionAlias.tune_id == external_tune_id).order_by(TheSessionAlias.alias)
    )
    return list(result.scalars().all())


async def get_thesession_settings(
    db: AsyncSession, external_tune_id: int, setting_ids: list[int] | None = None
) -> list[TheSessionSetting]:
    stmt = select(TheSessionSetting).where(TheSessionSetting.tune_id == external_tune_id)
    if setting_ids is not None:
        stmt = stmt.where(TheSessionSetting.id.in_(setting_ids))
    result = await db.execute(stmt.order_by(TheSessionSetting.id))
    return list(result.scalars().all())


def _thesession_setting_label(setting: TheSessionSetting) -> str:
    """Match the label shown next to each setting's checkbox in the wizard
    (see _thesession_wizard_settings.html) so the saved TuneSetting.label
    isn't a different, less informative string than what the user picked."""
    return f"#{setting.setting_id} by {setting.username or 'unknown'} @ TheSession.org"


async def apply_thesession_link(
    db: AsyncSession,
    tune_id: int,
    external_tune_id: int,
    alias_ids: list[int],
    setting_ids: list[int],
    default_setting_id: int | None,
) -> Tune | None:
    """Apply the user's wizard choices to an existing tune.

    Creates a non-core TuneSetting for every checked setting. If the tune has
    no core setting yet (not reachable via the current single entry point,
    which always operates on an existing — and therefore already-cored —
    tune, but kept as a safety net per the original spec), the chosen
    default setting becomes the core setting and populates the tune's own
    descriptive fields instead. Never overwrites an existing core setting.
    """
    tune = await get_tune(db, tune_id)
    if tune is None:
        return None

    existing_names = existing_alias_names(tune)
    if alias_ids:
        result = await db.execute(
            select(TheSessionAlias).where(
                TheSessionAlias.id.in_(alias_ids), TheSessionAlias.tune_id == external_tune_id
            )
        )
        for ext_alias in result.scalars().all():
            normalized = ext_alias.alias.strip().lower()
            if normalized not in existing_names:
                stripped = ext_alias.alias.strip()
                db.add(TuneAlias(tune_id=tune.id, name=stripped, sort_name=sort_key(stripped)))
                existing_names.add(normalized)

    settings_by_id: dict[int, TheSessionSetting] = {}
    if setting_ids:
        result = await db.execute(
            select(TheSessionSetting).where(
                TheSessionSetting.id.in_(setting_ids), TheSessionSetting.tune_id == external_tune_id
            )
        )
        settings_by_id = {s.id: s for s in result.scalars().all()}

    default_ext_setting = settings_by_id.get(default_setting_id) if default_setting_id is not None else None
    existing_core = core_setting(tune)
    remaining_setting_ids = setting_ids

    if default_ext_setting is not None and existing_core is None:
        db.add(
            TuneSetting(
                tune_id=tune.id,
                label=_thesession_setting_label(default_ext_setting),
                abc_notation=default_ext_setting.abc,
                is_core=True,
                thesession_setting_id=default_ext_setting.setting_id,
                thesession_username=default_ext_setting.username,
            )
        )
        mapped_type = raw_to_tune_type(default_ext_setting.tune_type_raw)
        if mapped_type is not None:
            tune.tune_type = mapped_type
        tune.time_signature = default_ext_setting.meter
        parsed_key = parse_key(default_ext_setting.mode_raw)
        if parsed_key is not None:
            tune.key_root, tune.key_mode = parsed_key
        remaining_setting_ids = [sid for sid in setting_ids if sid != default_setting_id]

    for sid in remaining_setting_ids:
        ext_setting = settings_by_id.get(sid)
        if ext_setting is None:
            continue
        db.add(
            TuneSetting(
                tune_id=tune.id,
                label=_thesession_setting_label(ext_setting),
                abc_notation=ext_setting.abc,
                is_core=False,
                thesession_setting_id=ext_setting.setting_id,
                thesession_username=ext_setting.username,
            )
        )

    tune.thesession_tune_id = external_tune_id
    if default_ext_setting is not None:
        tune.thesession_username = default_ext_setting.username

    await db.commit()
    await db.refresh(tune)
    return tune
