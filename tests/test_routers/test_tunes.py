from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import KeyMode, KeyRoot, TuneType
from cairn.schemas import TuneCreate
from cairn.services.tunes import create_tune

_ABC = "X:1\nT:x\nK:D\n|:DEFA BAFA|DEFA BAFA|DEFA BAFA|DEFA BAFA:|"


async def _seed_tune(db: AsyncSession):
    return await create_tune(
        db,
        TuneCreate(
            title="The Morning Dew",
            tune_type=TuneType.reel,
            key_root=KeyRoot.D,
            key_mode=KeyMode.major,
            time_signature="4/4",
        ),
        abc_notation=_ABC,
    )


async def test_tune_list_renders(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    resp = await client.get("/tunes/")
    assert resp.status_code == 200
    assert tune.title in resp.text


async def test_tune_list_includes_abc_hover_preview(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    resp = await client.get("/tunes/")
    assert resp.status_code == 200
    assert f'data-abc-preview-id="{tune.id}"' in resp.text
    marker = f'<template id="tune-abc-preview-{tune.id}">'
    assert marker in resp.text
    preview = resp.text.split(marker, 1)[1].split("</template>", 1)[0]
    # Only the first two bars should be present, not the closing repeat.
    assert "DEFA BAFA:|" not in preview
