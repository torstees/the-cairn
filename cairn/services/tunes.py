import re
from collections.abc import Iterable
from typing import NamedTuple

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cairn.models import (
    ContentVisibility,
    Instrument,
    OrnamentationLevel,
    TempoRecord,
    Tune,
    TuneAlias,
    TuneBoxEntry,
    TuneDifficulty,
    TuneListEntry,
    TuneSetting,
    TuneType,
)
from cairn.schemas import TuneCreate, TuneDifficultyCreate, TuneSettingCreate, TuneSettingUpdate, TuneUpdate
from cairn.services.abc_utils import build_abc, strip_chord_symbols, strip_decorative_headers, truncate_to_bars

_ARTICLE_RE = re.compile(r"^(?:the|a|an)\s+", re.IGNORECASE)
_TEMPO_HEADER_RE = re.compile(r"^Q:[^\n]*\n?", re.MULTILINE)

# Row-preview sizing (#164) — named so the popup's bar limit is easy to
# change if a full untransposed tune proves too large for the hover popup.
COLUMN_PREVIEW_N_BARS: int = 2
POPUP_PREVIEW_N_BARS: int | None = None  # None = full tune, no truncation


def sort_key(title: str) -> str:
    """Return the sort key for a title by stripping a leading article."""
    return _ARTICLE_RE.sub("", title)


# Groupings are hardcoded for now; extracting to a user-editable DB table is a separate concern.
TUNE_FAMILIES: dict[str, list[TuneType]] = {
    "jig_family": [TuneType.jig, TuneType.slip_jig, TuneType.slide],
    "reel_family": [TuneType.reel, TuneType.hornpipe, TuneType.barndance],
    "march_family": [TuneType.march, TuneType.strathspey],
    "other": [TuneType.polka, TuneType.waltz, TuneType.air, TuneType.mazurka, TuneType.three_two],
}

FAMILY_LABELS: dict[str, str] = {
    "jig_family": "Jig Family",
    "reel_family": "Reel Family",
    "march_family": "March Family",
    "other": "Other",
}


def get_setting_for_instrument(tune: Tune, instrument: Instrument | None) -> TuneSetting:
    """Return the best TuneSetting to display for the given instrument.

    Prefers a non-core setting explicitly marked for the instrument; falls back
    to the core setting (instrument=None, is_core=True).
    """
    if instrument is not None:
        specific = next(
            (s for s in tune.settings if s.instrument == instrument and not s.is_core),
            None,
        )
        if specific is not None:
            return specific
    core = next(s for s in tune.settings if s.is_core and s.instrument is None)
    return core


def core_setting(tune: Tune) -> TuneSetting | None:
    """Return the tune's instrument-agnostic core setting, if any."""
    return next((s for s in tune.settings if s.is_core and s.instrument is None), None)


def resolve_display_context(
    tune: Tune,
    box_entry: TuneBoxEntry | None,
    list_entry: TuneListEntry | None,
) -> tuple[TuneSetting | None, str]:
    """Resolve the effective setting and display name for a tune in a box/list
    context, following AGENTS.md's "Setting resolution order" (most to least
    specific: list override, box override, then a fallback) — the same
    precedence applies to the display name (#119): a list's own choice
    outranks the box's, which outranks the tune's own title.
    """
    active_setting = None
    active_display_alias = None
    if box_entry:
        if box_entry.setting_id is not None:
            active_setting = box_entry.setting
        if box_entry.display_alias_id is not None:
            active_display_alias = box_entry.display_alias
    if list_entry:
        if list_entry.setting_id is not None:
            active_setting = list_entry.setting
        if list_entry.display_alias_id is not None:
            active_display_alias = list_entry.display_alias

    if active_setting is None:
        active_setting = core_setting(tune)
    display_name = active_display_alias.name if active_display_alias else tune.title
    return active_setting, display_name


def existing_alias_names(tune: Tune) -> set[str]:
    """Return the tune's alias names normalised for case-insensitive dedup checks."""
    return {a.name.strip().lower() for a in tune.aliases}


class TunePreview(NamedTuple):
    """Two ABC renderings for the same entry (#164): a short always-visible
    column snippet, and a fuller one for the on-hover popup. column is a
    prefix-truncation of popup, guaranteeing they never drift apart."""

    column: str
    popup: str


def preview_abc(
    tune: Tune,
    setting: TuneSetting | None = None,
    n_bars: int | None = 4,
    display_name: str | None = None,
    notes_only: bool = False,
) -> str | None:
    """Return an ABC preview (opening bars) for tune, preferring `setting` over the core setting.

    n_bars=None returns the full tune, untruncated (same convention as
    build_set_abc()'s n_bars param in abc_utils.py).

    Strips the Q: tempo header — like the main score view's client-side
    stripping (app.js' render()), a tempo marking on a static preview is
    misleading since it never reflects anything the user can actually change
    there.

    display_name overrides the T: header, matching whatever name (tune title
    or box/list display alias, #119) the row this preview pops up from is
    itself showing.

    notes_only additionally strips title/composer/origin/region/rhythm-type/
    source/notes headers via strip_decorative_headers() (#164), for compact
    previews where only the notation itself should show.
    """
    setting = setting or core_setting(tune)
    if setting is None:
        return None
    abc = build_abc(tune, setting, display_name=display_name)
    if n_bars is not None:
        abc = truncate_to_bars(abc, n_bars)
    abc = _TEMPO_HEADER_RE.sub("", abc, count=1)
    if notes_only:
        abc = strip_decorative_headers(abc)
    return abc


def build_tune_previews(tunes: Iterable[Tune]) -> dict[int, TunePreview]:
    """Map tune id -> two-bar column + full popup preview (#179), for tunes that have a core setting."""
    previews: dict[int, TunePreview] = {}
    for tune in tunes:
        popup = preview_abc(tune, n_bars=POPUP_PREVIEW_N_BARS, notes_only=True)
        if popup is not None:
            column = strip_chord_symbols(truncate_to_bars(popup, COLUMN_PREVIEW_N_BARS))
            previews[tune.id] = TunePreview(column=column, popup=popup)
    return previews


async def create_tune(
    db: AsyncSession,
    tune_in: TuneCreate,
    *,
    abc_notation: str,
    setting_label: str = "Standard",
) -> Tune:
    """Create a tune and its mandatory core setting in a single transaction.

    The core setting always has instrument=None — it represents the traditional
    version valid for all instruments. abc_notation stores the music body only;
    headers are assembled at render time by build_abc.
    """
    tune = Tune(**tune_in.model_dump(), sort_title=sort_key(tune_in.title))
    db.add(tune)
    await db.flush()  # populate tune.id before referencing it in TuneSetting

    core_setting = TuneSetting(
        tune_id=tune.id,
        label=setting_label,
        abc_notation=abc_notation,
        is_core=True,
        instrument=None,
        ornamentation_level=OrnamentationLevel.none,
    )
    db.add(core_setting)
    await db.commit()
    await db.refresh(tune)
    return tune


async def get_tune(db: AsyncSession, tune_id: int) -> Tune | None:
    result = await db.execute(
        select(Tune)
        .where(Tune.id == tune_id)
        .options(selectinload(Tune.settings), selectinload(Tune.difficulties), selectinload(Tune.aliases))
    )
    return result.scalar_one_or_none()


async def add_alias(db: AsyncSession, tune_id: int, name: str, notes: str | None = None) -> TuneAlias | None:
    if await db.get(Tune, tune_id) is None:
        return None
    stripped = name.strip()
    alias = TuneAlias(tune_id=tune_id, name=stripped, sort_name=sort_key(stripped), notes=notes or None)
    db.add(alias)
    await db.commit()
    await db.refresh(alias)
    return alias


async def remove_alias(db: AsyncSession, alias_id: int) -> bool:
    alias = await db.get(TuneAlias, alias_id)
    if alias is None:
        return False
    await db.delete(alias)
    await db.commit()
    return True


async def list_tunes(
    db: AsyncSession,
    user_id: int,
    *,
    tune_type: TuneType | None = None,
    family: str | None = None,
) -> list[Tune]:
    stmt = (
        select(Tune)
        .options(selectinload(Tune.settings), selectinload(Tune.difficulties), selectinload(Tune.aliases))
        .where(or_(Tune.visibility == ContentVisibility.public, Tune.created_by == user_id))
        .order_by(Tune.sort_title)
    )
    if tune_type is not None:
        stmt = stmt.where(Tune.tune_type == tune_type)
    elif family is not None:
        types = TUNE_FAMILIES.get(family, [])
        if types:
            stmt = stmt.where(Tune.tune_type.in_(types))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_tune(
    db: AsyncSession,
    tune_id: int,
    tune_in: TuneUpdate,
    *,
    abc_notation: str | None = None,
) -> Tune | None:
    tune = await db.get(Tune, tune_id)
    if tune is None:
        return None
    for field, value in tune_in.model_dump(exclude_unset=True).items():
        setattr(tune, field, value)
    if "title" in tune_in.model_fields_set:
        tune.sort_title = sort_key(tune.title)
    if abc_notation is not None:
        result = await db.execute(
            select(TuneSetting).where(
                TuneSetting.tune_id == tune_id,
                TuneSetting.is_core.is_(True),
                TuneSetting.instrument.is_(None),
            )
        )
        core = result.scalar_one_or_none()
        if core:
            core.abc_notation = abc_notation
    await db.commit()
    await db.refresh(tune)
    return tune


async def create_setting(
    db: AsyncSession,
    tune_id: int,
    setting_in: TuneSettingCreate,
) -> TuneSetting | None:
    """Add a non-core TuneSetting to an existing tune."""
    if await db.get(Tune, tune_id) is None:
        return None
    setting = TuneSetting(
        tune_id=tune_id,
        label=setting_in.label,
        abc_notation=setting_in.abc_notation,
        is_core=False,
        instrument=setting_in.instrument,
        source=setting_in.source,
        ornamentation_level=setting_in.ornamentation_level,
        source_notes=setting_in.source_notes,
        mutation_notation=setting_in.mutation_notation,
        visibility=setting_in.visibility,
    )
    db.add(setting)
    await db.commit()
    await db.refresh(setting)
    return setting


async def set_core_setting(
    db: AsyncSession,
    tune_id: int,
    setting_id: int,
) -> TuneSetting | None:
    """Promote setting_id to core, demoting the existing core in one transaction."""
    target = await db.get(TuneSetting, setting_id)
    if target is None or target.tune_id != tune_id:
        return None
    if target.is_core:
        return target
    result = await db.execute(
        select(TuneSetting).where(
            TuneSetting.tune_id == tune_id,
            TuneSetting.is_core.is_(True),
        )
    )
    current_core = result.scalar_one_or_none()
    if current_core:
        current_core.is_core = False
    target.is_core = True
    await db.commit()
    await db.refresh(target)
    return target


async def update_setting(
    db: AsyncSession,
    tune_id: int,
    setting_id: int,
    setting_in: TuneSettingUpdate,
) -> TuneSetting | None:
    """Update fields on an existing TuneSetting."""
    setting = await db.get(TuneSetting, setting_id)
    if setting is None or setting.tune_id != tune_id:
        return None
    for field, value in setting_in.model_dump(exclude_unset=True).items():
        setattr(setting, field, value)
    await db.commit()
    await db.refresh(setting)
    return setting


async def set_difficulty(
    db: AsyncSession,
    tune_id: int,
    difficulty_in: TuneDifficultyCreate,
) -> TuneDifficulty | None:
    """Upsert a difficulty rating for a (tune, instrument) pair."""
    if await db.get(Tune, tune_id) is None:
        return None
    result = await db.execute(
        select(TuneDifficulty).where(
            TuneDifficulty.tune_id == tune_id,
            TuneDifficulty.instrument == difficulty_in.instrument,
        )
    )
    record = result.scalar_one_or_none()
    if record:
        record.difficulty = difficulty_in.difficulty
        record.notes = difficulty_in.notes
    else:
        record = TuneDifficulty(
            tune_id=tune_id,
            instrument=difficulty_in.instrument,
            difficulty=difficulty_in.difficulty,
            notes=difficulty_in.notes,
        )
        db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def delete_tune(db: AsyncSession, tune_id: int) -> bool:
    tune = await db.get(Tune, tune_id)
    if tune is None:
        return False
    await db.delete(tune)
    await db.commit()
    return True


async def record_tempo(db: AsyncSession, user_id: int, tune_id: int, box_id: int | None, tempo: int) -> TempoRecord:
    record = TempoRecord(user_id=user_id, tune_id=tune_id, box_id=box_id, tempo=tempo)
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def get_tempo_history(
    db: AsyncSession, user_id: int, tune_id: int, limit: int = 20
) -> tuple[int | None, list[TempoRecord]]:
    """Return (all-time min tempo, last `limit` records oldest-first).

    Orders by id as a tiebreaker after created_at — SQLite's CURRENT_TIMESTAMP
    only has second resolution, so two records logged within the same second
    (e.g. back-to-back metronome runs) would otherwise come back in an
    unpredictable order, silently breaking the oldest-first guarantee.
    """
    recent = (
        (
            await db.execute(
                select(TempoRecord)
                .where(TempoRecord.user_id == user_id, TempoRecord.tune_id == tune_id)
                .order_by(TempoRecord.created_at.desc(), TempoRecord.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    if not recent:
        return None, []

    min_tempo = (
        await db.execute(
            select(func.min(TempoRecord.tempo)).where(TempoRecord.user_id == user_id, TempoRecord.tune_id == tune_id)
        )
    ).scalar_one_or_none()

    return min_tempo, list(reversed(recent))
