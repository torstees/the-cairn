from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cairn.models import OrnamentationLevel, Tune, TuneSetting
from cairn.schemas import TuneCreate, TuneUpdate


async def create_tune(
    db: AsyncSession,
    tune_in: TuneCreate,
    *,
    abc_notation: str,
    setting_label: str = "Standard",
) -> Tune:
    """Create a tune and its mandatory core setting in a single transaction."""
    tune = Tune(**tune_in.model_dump())
    db.add(tune)
    await db.flush()  # populate tune.id before referencing it in TuneSetting

    core_setting = TuneSetting(
        tune_id=tune.id,
        label=setting_label,
        abc_notation=abc_notation,
        is_core=True,
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
    tune = await db.get(Tune, tune_id)
    if tune is None:
        return None
    for field, value in tune_in.model_dump(exclude_unset=True).items():
        setattr(tune, field, value)
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
