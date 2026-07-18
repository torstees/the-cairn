import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import Instrument, InstrumentTuning

# Fretted-string instruments only — abcjs's tablature rendering (fret
# position from a string tuning) has no meaning for anything else in the
# Instrument enum.
FRETTED_INSTRUMENTS: frozenset[Instrument] = frozenset(
    {Instrument.guitar, Instrument.banjo, Instrument.mandolin, Instrument.bouzouki}
)

# Well-known named tunings offered as a starting point so most users never
# need to type raw ABC pitch notation by hand. Bouzouki and (tenor) banjo
# share the mandolin's 4-string GDAE layout — neither has its own dedicated
# abcjs tablature preset, and this is the common case in Irish trad.
PRESET_TUNINGS: dict[Instrument, dict[str, list[str]]] = {
    Instrument.guitar: {
        "Standard (EADGBE)": ["E,", "A,", "D", "G", "B", "e"],
        "Drop D": ["D,", "A,", "D", "G", "B", "e"],
        "DADGAD": ["D,", "A,", "D", "G", "A", "d"],
        "Open D (DADF#AD)": ["D,", "A,", "D", "F#", "A", "d"],
        "Open G (DGDGBD)": ["D,", "G,", "D", "G", "B", "d"],
    },
    Instrument.mandolin: {
        "Standard (GDAE)": ["G,", "D", "A", "e"],
    },
    Instrument.bouzouki: {
        "Standard (GDAE)": ["G,", "D", "A", "e"],
        "GDAD": ["G,", "D", "A", "d"],
    },
    Instrument.banjo: {
        "Standard tenor (GDAE)": ["G,", "D", "A", "e"],
    },
}

# Precomputed once — Instrument-enum keys aren't directly JSON-serializable
# via Jinja's |tojson, so the presets picker's client-side JS gets a plain
# string-keyed blob instead.
PRESET_TUNINGS_JSON: str = json.dumps({instrument.value: presets for instrument, presets in PRESET_TUNINGS.items()})


def tunings_to_json(tunings: list[InstrumentTuning]) -> str:
    """Serialize for window.__cairnTunings — consumed by the tablature
    controls on tunes/detail.html (both the initial page render and the
    HTMX-refreshed tunings/_manage.html partial after an add/delete)."""
    return json.dumps([{"instrument": t.instrument.value, "name": t.name, "strings": t.strings} for t in tunings])


async def list_tunings(db: AsyncSession, user_id: int) -> list[InstrumentTuning]:
    result = await db.execute(
        select(InstrumentTuning)
        .where(InstrumentTuning.user_id == user_id)
        .order_by(InstrumentTuning.instrument, InstrumentTuning.name)
    )
    return list(result.scalars().all())


async def create_tuning(
    db: AsyncSession,
    user_id: int,
    instrument: Instrument,
    name: str,
    strings: list[str],
) -> InstrumentTuning:
    tuning = InstrumentTuning(user_id=user_id, instrument=instrument, name=name.strip(), strings=strings)
    db.add(tuning)
    await db.commit()
    await db.refresh(tuning)
    return tuning


async def delete_tuning(db: AsyncSession, tuning_id: int, user_id: int) -> bool:
    tuning = await db.get(InstrumentTuning, tuning_id)
    if tuning is None or tuning.user_id != user_id:
        return False
    await db.delete(tuning)
    await db.commit()
    return True
