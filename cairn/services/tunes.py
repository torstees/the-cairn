import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cairn.models import Instrument, OrnamentationLevel, Tune, TuneAlias, TuneDifficulty, TuneSetting, TuneType
from cairn.schemas import TuneCreate, TuneDifficultyCreate, TuneSettingCreate, TuneSettingUpdate, TuneUpdate

_ARTICLE_RE = re.compile(r"^(?:the|a|an)\s+", re.IGNORECASE)


def sort_key(title: str) -> str:
    """Return the sort key for a title by stripping a leading article."""
    return _ARTICLE_RE.sub("", title)


# Groupings are hardcoded for now; extracting to a user-editable DB table is a separate concern.
TUNE_FAMILIES: dict[str, list[TuneType]] = {
    "jig_family": [TuneType.jig, TuneType.slip_jig, TuneType.slide],
    "reel_family": [TuneType.reel, TuneType.hornpipe, TuneType.barndance],
    "march_family": [TuneType.march, TuneType.strathspey],
    "other": [TuneType.polka, TuneType.waltz, TuneType.air],
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
    alias = TuneAlias(tune_id=tune_id, name=name.strip(), notes=notes or None)
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
    *,
    tune_type: TuneType | None = None,
    family: str | None = None,
) -> list[Tune]:
    stmt = select(Tune).options(selectinload(Tune.settings), selectinload(Tune.difficulties)).order_by(Tune.sort_title)
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
