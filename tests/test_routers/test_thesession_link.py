from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import KeyMode, KeyRoot, TuneSetting, TuneType
from cairn.models_thesession_tunes import TheSessionAlias, TheSessionSetting
from cairn.schemas import TuneCreate
from cairn.services.tunes import create_tune

_ABC = "X:1\nT:x\nK:D\n|:DEFA BAFA|DEFA BAFA|DEFA BAFA|DEFA BAFA|DEFA BAFA|DEFA BAFA:|"


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


async def _seed_external_tune(db: AsyncSession) -> TheSessionSetting:
    setting = TheSessionSetting(
        setting_id=477,
        tune_id=100,
        name="The Abbey",
        tune_type_raw="reel",
        meter="4/4",
        mode_raw="Ador",
        abc="|:B|A3B A2GE|A2GA BddB:|",
        username="Josh Kane",
    )
    db.add(setting)
    db.add(TheSessionAlias(tune_id=100, alias="Abbey Road, The", canonical_name="The Abbey"))
    await db.commit()
    await db.refresh(setting)
    return setting


async def test_search_open_renders_wizard(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    await _seed_external_tune(db)
    resp = await client.get(f"/tunes/{tune.id}/thesession-search", params={"q": "abbey"})
    assert resp.status_code == 200
    assert "The Abbey" in resp.text
    assert "Step 1 of 4" in resp.text


async def test_search_open_unknown_tune_404s(client: AsyncClient) -> None:
    resp = await client.get("/tunes/999/thesession-search")
    assert resp.status_code == 404


async def test_search_open_prefills_with_tune_title(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    resp = await client.get(f"/tunes/{tune.id}/thesession-search")
    assert resp.status_code == 200
    assert 'value="Morning Dew"' in resp.text


async def test_search_open_prefill_strips_leading_article(client: AsyncClient, db: AsyncSession) -> None:
    tune = await create_tune(
        db,
        TuneCreate(
            title="The Kesh",
            tune_type=TuneType.jig,
            key_root=KeyRoot.G,
            key_mode=KeyMode.major,
            time_signature="6/8",
        ),
        abc_notation=_ABC,
    )
    resp = await client.get(f"/tunes/{tune.id}/thesession-search")
    assert resp.status_code == 200
    assert 'value="Kesh"' in resp.text


async def test_search_open_explicit_q_overrides_prefill(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    await _seed_external_tune(db)
    resp = await client.get(f"/tunes/{tune.id}/thesession-search", params={"q": "abbey"})
    assert 'value="abbey"' in resp.text
    assert 'value="Morning Dew"' not in resp.text


async def test_search_results_filters_by_query(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    await _seed_external_tune(db)
    resp = await client.get(f"/tunes/{tune.id}/thesession-search-results", params={"q": "nonexistent"})
    assert resp.status_code == 200
    assert "No matches" in resp.text


async def test_pick_tune_renders_aliases(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    await _seed_external_tune(db)
    resp = await client.get(f"/tunes/{tune.id}/thesession-tune/100")
    assert resp.status_code == 200
    assert "Abbey Road, The" in resp.text
    assert "Step 2 of 4" in resp.text


async def test_pick_aliases_renders_settings_with_abc(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    ext = await _seed_external_tune(db)
    resp = await client.post(f"/tunes/{tune.id}/thesession-tune/100/settings", data={"alias_ids": []})
    assert resp.status_code == 200
    assert "Step 3 of 4" in resp.text
    assert f"#{ext.setting_id}" in resp.text
    assert "language-abc" in resp.text


async def test_pick_aliases_splits_settings_by_key_match(client: AsyncClient, db: AsyncSession) -> None:
    # The seeded tune is D major; give it one matching and one non-matching setting.
    tune = await _seed_tune(db)
    matching = TheSessionSetting(
        setting_id=1,
        tune_id=100,
        name="The Morning Dew",
        tune_type_raw="reel",
        meter="4/4",
        mode_raw="Dmajor",
        abc="|:DEFG ABcd:|",
        username="alice",
    )
    other = TheSessionSetting(
        setting_id=2,
        tune_id=100,
        name="The Morning Dew",
        tune_type_raw="reel",
        meter="4/4",
        mode_raw="Ador",
        abc="|:A2BA GABc:|",
        username="bob",
    )
    db.add_all([matching, other])
    await db.commit()

    resp = await client.post(f"/tunes/{tune.id}/thesession-tune/100/settings", data={"alias_ids": []})
    assert resp.status_code == 200
    # Only the matching setting is shown by default (outside the showAll-gated div).
    assert "showAll: false" in resp.text
    assert "Show all 2 settings" in resp.text
    assert "1 in a different key" in resp.text


async def test_pick_aliases_shows_everything_with_no_toggle_when_nothing_matches(
    client: AsyncClient, db: AsyncSession
) -> None:
    tune = await _seed_tune(db)
    ext = await _seed_external_tune(db)  # mode_raw="Ador", tune is D major — no match
    resp = await client.post(f"/tunes/{tune.id}/thesession-tune/100/settings", data={"alias_ids": []})
    assert resp.status_code == 200
    # No matches means nothing to narrow to — show the setting directly, no toggle.
    assert f"#{ext.setting_id}" in resp.text
    assert "showAll" not in resp.text
    assert "Show all" not in resp.text


async def test_confirm_shows_only_checked_settings(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    ext = await _seed_external_tune(db)
    other = TheSessionSetting(
        setting_id=478,
        tune_id=100,
        name="The Abbey",
        tune_type_raw="reel",
        meter="4/4",
        mode_raw="Ador",
        abc="|:B|A3B A2GE|A2GA BddB:|",
        username="Someone Else",
    )
    db.add(other)
    await db.commit()
    await db.refresh(other)

    resp = await client.post(
        f"/tunes/{tune.id}/thesession-tune/100/confirm",
        data={"alias_ids": [], "setting_ids": [ext.id]},
    )
    assert resp.status_code == 200
    assert "Step 4 of 4" in resp.text
    assert "Josh Kane" in resp.text
    assert "Someone Else" not in resp.text


async def test_save_links_tune_and_imports_setting(client: AsyncClient, db: AsyncSession) -> None:
    tune = await _seed_tune(db)
    ext = await _seed_external_tune(db)

    resp = await client.post(
        f"/tunes/{tune.id}/thesession-link",
        data={
            "external_tune_id": 100,
            "alias_ids": [],
            "setting_ids": [ext.id],
            "default_setting_id": ext.id,
        },
    )
    assert resp.status_code == 200
    assert resp.headers["hx-redirect"] == f"/tunes/{tune.id}"

    result = await db.execute(select(TuneSetting).where(TuneSetting.tune_id == tune.id))
    settings = result.scalars().all()
    core = next(s for s in settings if s.is_core)
    assert core.abc_notation == _ABC  # never overwritten
    imported = next(s for s in settings if not s.is_core)
    assert imported.thesession_setting_id == 477
    assert imported.thesession_username == "Josh Kane"


async def test_save_unknown_tune_404s(client: AsyncClient) -> None:
    resp = await client.post(
        "/tunes/999/thesession-link",
        data={"external_tune_id": 100, "alias_ids": [], "setting_ids": [], "default_setting_id": ""},
    )
    assert resp.status_code == 404
