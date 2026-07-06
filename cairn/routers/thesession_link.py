from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_db
from cairn.models import TuneType
from cairn.services.abc_utils import truncate_to_bars
from cairn.services.thesession_link import (
    apply_thesession_link,
    build_thesession_preview_abc,
    get_thesession_aliases,
    get_thesession_settings,
    search_thesession_tunes,
)
from cairn.services.tunes import FAMILY_LABELS, existing_alias_names, get_tune
from cairn.templating import templates

router = APIRouter(prefix="/tunes", tags=["thesession-link"])

_TUNE_TYPES = list(TuneType)


def _parse_tune_type(raw: str) -> TuneType | None:
    """Parse the `type` query param, tolerating "" — sent by the wizard's hidden
    field when no type filter is active, which a plain `TuneType | None` Query
    param would reject with a 422 (FastAPI does not coerce "" to None for enums).
    """
    try:
        return TuneType(raw) if raw else None
    except ValueError:
        return None


async def _results_context(
    db: AsyncSession, tune_id: int, q: str, tune_type: TuneType | None, family: str | None
) -> dict:
    results = await search_thesession_tunes(db, q=q, tune_type=tune_type, family=family)
    previews = {
        r.tune_id: truncate_to_bars(build_thesession_preview_abc(r), 4) for r in results if r.abc and r.abc.strip()
    }
    return {
        "tune_id": tune_id,
        "results": results,
        "previews": previews,
        "q": q,
        "tune_types": _TUNE_TYPES,
        "family_labels": FAMILY_LABELS,
        "active_type": tune_type,
        "active_family": family,
    }


@router.get("/{tune_id}/thesession-search")
async def thesession_search_open(
    request: Request,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    q: str = "",
    type: str = Query(default=""),
    family: str | None = None,
) -> Response:
    tune = await get_tune(db, tune_id)
    if tune is None:
        raise HTTPException(status_code=404, detail="Tune not found")
    ctx = await _results_context(db, tune_id, q, _parse_tune_type(type), family or None)
    return templates.TemplateResponse(request, "tunes/partials/_thesession_wizard_search.html", ctx)


@router.get("/{tune_id}/thesession-search-results")
async def thesession_search_results(
    request: Request,
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    q: str = "",
    type: str = Query(default=""),
    family: str | None = None,
) -> Response:
    ctx = await _results_context(db, tune_id, q, _parse_tune_type(type), family or None)
    return templates.TemplateResponse(request, "tunes/partials/_thesession_wizard_results_response.html", ctx)


@router.get("/{tune_id}/thesession-tune/{external_tune_id}")
async def thesession_pick_tune(
    request: Request,
    tune_id: int,
    external_tune_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    tune = await get_tune(db, tune_id)
    if tune is None:
        raise HTTPException(status_code=404, detail="Tune not found")
    aliases = await get_thesession_aliases(db, external_tune_id)
    existing_names = existing_alias_names(tune)
    return templates.TemplateResponse(
        request,
        "tunes/partials/_thesession_wizard_aliases.html",
        {
            "tune_id": tune_id,
            "external_tune_id": external_tune_id,
            "aliases": aliases,
            "existing_names": existing_names,
        },
    )


@router.post("/{tune_id}/thesession-tune/{external_tune_id}/settings")
async def thesession_pick_aliases(
    request: Request,
    tune_id: int,
    external_tune_id: int,
    db: AsyncSession = Depends(get_db),
    alias_ids: list[int] = Form(default=[]),
) -> Response:
    settings = await get_thesession_settings(db, external_tune_id)
    previews = {s.id: build_thesession_preview_abc(s) for s in settings}
    return templates.TemplateResponse(
        request,
        "tunes/partials/_thesession_wizard_settings.html",
        {
            "tune_id": tune_id,
            "external_tune_id": external_tune_id,
            "settings": settings,
            "previews": previews,
            "alias_ids": alias_ids,
        },
    )


@router.post("/{tune_id}/thesession-tune/{external_tune_id}/confirm")
async def thesession_confirm(
    request: Request,
    tune_id: int,
    external_tune_id: int,
    db: AsyncSession = Depends(get_db),
    alias_ids: list[int] = Form(default=[]),
    setting_ids: list[int] = Form(default=[]),
) -> Response:
    checked_settings = await get_thesession_settings(db, external_tune_id, setting_ids)
    return templates.TemplateResponse(
        request,
        "tunes/partials/_thesession_wizard_confirm.html",
        {
            "tune_id": tune_id,
            "external_tune_id": external_tune_id,
            "settings": checked_settings,
            "alias_ids": alias_ids,
            "setting_ids": setting_ids,
        },
    )


@router.post("/{tune_id}/thesession-link")
async def thesession_save(
    tune_id: int,
    db: AsyncSession = Depends(get_db),
    external_tune_id: int = Form(...),
    alias_ids: list[int] = Form(default=[]),
    setting_ids: list[int] = Form(default=[]),
    default_setting_id: int | None = Form(default=None),
) -> Response:
    tune = await apply_thesession_link(
        db,
        tune_id,
        external_tune_id,
        alias_ids,
        setting_ids,
        default_setting_id,
    )
    if tune is None:
        raise HTTPException(status_code=404, detail="Tune not found")
    response = Response(status_code=200)
    response.headers["HX-Redirect"] = f"/tunes/{tune_id}"
    return response
