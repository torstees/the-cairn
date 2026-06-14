from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cairn.models import Instrument, KeyMode, KeyRoot, OrnamentationLevel, Tune, TuneSetting
from cairn.schemas import TuneCreate, TuneUpdate

_ABC_MODE_SUFFIX: dict[str, str] = {
    "major": "",
    "minor": "m",
    "dorian": "Dor",
    "mixolydian": "Mix",
    "lydian": "Lyd",
}


def _sync_abc_key(abc_notation: str, key_root: KeyRoot, key_mode: KeyMode) -> str:
    """Rewrite (or append) the K: header so it matches key_root and key_mode."""
    key_str = f"K:{key_root.value}{_ABC_MODE_SUFFIX[key_mode.value]}"
    trailing_newline = abc_notation.endswith("\n")
    lines = abc_notation.splitlines()
    replaced = False
    new_lines = []
    for line in lines:
        if line.startswith("K:") and not replaced:
            new_lines.append(key_str)
            replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        new_lines.append(key_str)
    result = "\n".join(new_lines)
    if trailing_newline:
        result += "\n"
    return result


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
    version valid for all instruments.
    """
    tune = Tune(**tune_in.model_dump())
    db.add(tune)
    await db.flush()  # populate tune.id before referencing it in TuneSetting

    synced_abc = _sync_abc_key(abc_notation, tune_in.key_root, tune_in.key_mode)
    core_setting = TuneSetting(
        tune_id=tune.id,
        label=setting_label,
        abc_notation=synced_abc,
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


async def update_tune(db: AsyncSession, tune_id: int, tune_in: TuneUpdate) -> Tune | None:
    tune = await get_tune(db, tune_id)  # load settings for potential K: sync
    if tune is None:
        return None
    update_data = tune_in.model_dump(exclude_unset=True)
    key_changed = "key_root" in update_data or "key_mode" in update_data
    for field, value in update_data.items():
        setattr(tune, field, value)
    if key_changed:
        core = next((s for s in tune.settings if s.is_core and s.instrument is None), None)
        if core:
            core.abc_notation = _sync_abc_key(core.abc_notation, tune.key_root, tune.key_mode)
    await db.commit()
    await db.refresh(tune)
    return tune


async def delete_tune(db: AsyncSession, tune_id: int) -> bool:
    tune = await db.get(Tune, tune_id)
    if tune is None:
        return False
    await db.delete(tune)
    await db.commit()
    return True
