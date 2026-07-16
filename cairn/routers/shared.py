from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_db
from cairn.services.abc_utils import build_abc
from cairn.services.share_links import get_share_link_by_token
from cairn.templating import templates

router = APIRouter(prefix="/shared", tags=["shared"])


@router.get("/{token}", name="shared_detail")
async def shared_detail(request: Request, token: str, db: AsyncSession = Depends(get_db)) -> Response:
    link = await get_share_link_by_token(db, token)
    if link is None:
        raise HTTPException(status_code=404, detail="This shared link doesn't exist or has been revoked")

    if link.setting_id is not None:
        tune = link.setting.tune
        setting = link.setting
    else:
        tune = link.tune
        setting = next((s for s in tune.settings if s.is_core and s.instrument is None), None)

    abc = build_abc(tune, setting) if setting else ""
    return templates.TemplateResponse(
        request,
        "shared/detail.html",
        {"tune": tune, "setting": setting, "abc": abc},
    )
