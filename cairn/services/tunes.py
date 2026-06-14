from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cairn.models import Instrument, OrnamentationLevel, Tune, TuneSetting
from cairn.schemas import TuneCreate, TuneSettingCreate, TuneUpdate


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
    tune = Tune(**tune_in.model_dump())
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
        .options(selectinload(Tune.settings), selectinload(Tune.difficulties))
    )
    return result.scalar_one_or_none()


async def list_tunes(db: AsyncSession) -> list[Tune]:
    result = await db.execute(
        select(Tune)
        .options(selectinload(Tune.settings), selectinload(Tune.difficulties))
        .order_by(Tune.title)
    )
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


async def delete_tune(db: AsyncSession, tune_id: int) -> bool:
    tune = await db.get(Tune, tune_id)
    if tune is None:
        return False
    await db.delete(tune)
    await db.commit()
    return True
