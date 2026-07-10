from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import (
    Instrument,
    KeyMode,
    KeyRoot,
    OrnamentationLevel,
    Role,
    TuneSet,
    TuneSetMember,
    TuneType,
    User,
)
from cairn.schemas import TuneCreate
from cairn.services.abc_utils import build_set_abc
from cairn.services.boxes import create_box
from cairn.services.tune_sets import (
    add_box_set,
    create_set,
    delete_set,
    get_set,
    list_sets,
    remove_box_set,
    set_members,
    update_set,
)
from cairn.services.tunes import create_tune

_ABC = "|:DEFA BAFA|DEFA BAFA:|\n"
_ABC2 = "|:GBdB GBAG|FAdA FAdf:|\n"


# ── helpers ────────────────────────────────────────────────────────────────────


async def _user(db: AsyncSession) -> User:
    u = User(username="alice", email="alice@example.com", hashed_password="x", role=Role.student)
    db.add(u)
    await db.flush()
    return u


async def _tune(db: AsyncSession, title: str = "The Morning Dew", abc: str = _ABC):
    return await create_tune(
        db,
        TuneCreate(
            title=title,
            tune_type=TuneType.reel,
            key_root=KeyRoot.D,
            key_mode=KeyMode.major,
            time_signature="4/4",
        ),
        abc_notation=abc,
    )


async def _set(db: AsyncSession, **kwargs) -> TuneSet:
    return await create_set(db, title=kwargs.pop("title", "Morning Set"), **kwargs)


# ── create_set / get_set ──────────────────────────────────────────────────────


async def test_create_and_get_set(db: AsyncSession) -> None:
    s = await _set(db, title="My Set", source="Catskills 2023", flow_difficulty=3)
    fetched = await get_set(db, s.id)
    assert fetched is not None
    assert fetched.title == "My Set"
    assert fetched.source == "Catskills 2023"
    assert fetched.flow_difficulty == 3
    assert fetched.abc_header is None


async def test_get_set_not_found(db: AsyncSession) -> None:
    assert await get_set(db, 9999) is None


async def test_create_set_abc_header_stored(db: AsyncSession) -> None:
    s = await _set(db, abc_header="P:AABB\nQ:1/4=100")
    fetched = await get_set(db, s.id)
    assert fetched is not None
    assert fetched.abc_header == "P:AABB\nQ:1/4=100"


# ── list_sets ─────────────────────────────────────────────────────────────────


async def test_list_sets_ordered_by_title(db: AsyncSession) -> None:
    await _set(db, title="Zephyr Set")
    await _set(db, title="Alpha Set")
    sets = await list_sets(db)
    assert [s.title for s in sets] == ["Alpha Set", "Zephyr Set"]


async def test_list_sets_empty(db: AsyncSession) -> None:
    assert await list_sets(db) == []


# ── update_set ────────────────────────────────────────────────────────────────


async def test_update_set(db: AsyncSession) -> None:
    s = await _set(db, title="Old Title", source="Old Source")
    updated = await update_set(db, s.id, title="New Title", source=None, flow_difficulty=2)
    assert updated is not None
    assert updated.title == "New Title"
    assert updated.source is None
    assert updated.flow_difficulty == 2


async def test_update_set_not_found(db: AsyncSession) -> None:
    assert await update_set(db, 9999, title="X") is None


# ── delete_set ────────────────────────────────────────────────────────────────


async def test_delete_set(db: AsyncSession) -> None:
    s = await _set(db)
    assert await delete_set(db, s.id) is True
    assert await get_set(db, s.id) is None


async def test_delete_set_not_found(db: AsyncSession) -> None:
    assert await delete_set(db, 9999) is False


# ── set_members ───────────────────────────────────────────────────────────────


async def test_set_members_assigns_order(db: AsyncSession) -> None:
    t1 = await _tune(db, "Tune A")
    t2 = await _tune(db, "Tune B")
    t3 = await _tune(db, "Tune C")
    s = await _set(db)

    result = await set_members(
        db,
        s.id,
        [
            {"tune_id": t1.id},
            {"tune_id": t2.id},
            {"tune_id": t3.id},
        ],
    )
    assert result is not None
    orders = [(m.tune_id, m.order) for m in result.members]
    assert orders == [(t1.id, 0), (t2.id, 1), (t3.id, 2)]


async def test_set_members_reorder(db: AsyncSession) -> None:
    t1 = await _tune(db, "Tune A")
    t2 = await _tune(db, "Tune B")
    s = await _set(db)
    await set_members(db, s.id, [{"tune_id": t1.id}, {"tune_id": t2.id}])

    result = await set_members(db, s.id, [{"tune_id": t2.id}, {"tune_id": t1.id}])
    assert result is not None
    assert result.members[0].tune_id == t2.id
    assert result.members[1].tune_id == t1.id


async def test_set_members_removes_dropped_members(db: AsyncSession) -> None:
    t1 = await _tune(db, "Tune A")
    t2 = await _tune(db, "Tune B")
    s = await _set(db)
    await set_members(db, s.id, [{"tune_id": t1.id}, {"tune_id": t2.id}])

    result = await set_members(db, s.id, [{"tune_id": t1.id}])
    assert result is not None
    assert len(result.members) == 1
    assert result.members[0].tune_id == t1.id


async def test_set_members_stores_setting_id(db: AsyncSession) -> None:
    from sqlalchemy import select as sa_select

    from cairn.models import TuneSetting

    tune = await _tune(db)
    s = await _set(db)
    core_setting = (
        await db.execute(sa_select(TuneSetting).where(TuneSetting.tune_id == tune.id, TuneSetting.is_core.is_(True)))
    ).scalar_one()

    result = await set_members(db, s.id, [{"tune_id": tune.id, "setting_id": core_setting.id}])
    assert result is not None
    assert result.members[0].setting_id == core_setting.id


async def test_set_members_empty_clears_list(db: AsyncSession) -> None:
    t1 = await _tune(db)
    s = await _set(db)
    await set_members(db, s.id, [{"tune_id": t1.id}])
    result = await set_members(db, s.id, [])
    assert result is not None
    assert result.members == []


async def test_set_members_not_found(db: AsyncSession) -> None:
    assert await set_members(db, 9999, []) is None


# ── add_box_set / remove_box_set ──────────────────────────────────────────────


async def test_add_and_remove_box_set(db: AsyncSession) -> None:
    u = await _user(db)
    box = await create_box(db, user_id=u.id, name="My Box", instruments=[Instrument.flute])
    s = await _set(db)

    entry = await add_box_set(db, box_id=box.id, set_id=s.id)
    assert entry.box_id == box.id
    assert entry.set_id == s.id

    assert await remove_box_set(db, box_id=box.id, set_id=s.id) is True
    assert await remove_box_set(db, box_id=box.id, set_id=s.id) is False


# ── build_set_abc ─────────────────────────────────────────────────────────────
# These tests use plain model instances (no DB) like test_abc_utils.py.


def _make_tune(title="The Morning Dew", tune_type=TuneType.reel):
    from cairn.models import Tune

    return Tune(
        title=title,
        tune_type=tune_type,
        key_root=KeyRoot.D,
        key_mode=KeyMode.major,
        time_signature="4/4",
        composer=None,
        origin=None,
        region=None,
        notes=None,
    )


def _make_setting(tune_id=1, abc=_ABC):
    from cairn.models import TuneSetting

    return TuneSetting(
        tune_id=tune_id,
        label="Standard",
        abc_notation=abc,
        is_core=True,
        instrument=None,
        source=None,
        source_notes=None,
        ornamentation_level=OrnamentationLevel.none,
    )


def _make_member(tune, setting=None, order=0):
    member = TuneSetMember(set_id=1, tune_id=tune.id or 1, order=order)
    member.tune = tune
    member.setting = setting
    tune.settings = [_make_setting()] if not hasattr(tune, "settings") or not tune.settings else tune.settings
    tune.settings[0].is_core = True
    return member


def _make_set(title="Morning Set", source=None, abc_header=None):
    s = TuneSet(title=title, source=source, abc_header=abc_header)
    s.members = []
    return s


def _file_headers(abc: str) -> list[str]:
    """Return header lines before the first X: block."""
    lines = []
    for line in abc.splitlines():
        if line.startswith("X:"):
            break
        if len(line) >= 2 and line[1] == ":" and line[0].isalpha():
            lines.append(line)
    return lines


def test_build_set_abc_file_header_title(db=None) -> None:
    s = _make_set(title="Morning Set")
    result = build_set_abc(s)
    headers = _file_headers(result)
    assert headers[0] == "T:Morning Set"


def test_build_set_abc_no_source_no_g_by_default() -> None:
    s = _make_set()
    result = build_set_abc(s)
    headers = _file_headers(result)
    letters = [h[0] for h in headers]
    assert "S" not in letters
    assert "G" not in letters


def test_build_set_abc_with_source() -> None:
    s = _make_set(source="Catskills 2023")
    result = build_set_abc(s)
    headers = _file_headers(result)
    assert any(h == "S:Catskills 2023" for h in headers)


def test_build_set_abc_with_box() -> None:
    from cairn.models import TuneBox

    s = _make_set()
    box = TuneBox(name="Flute Tunes", user_id=1)
    result = build_set_abc(s, box=box)
    headers = _file_headers(result)
    assert any(h == "G:Flute Tunes" for h in headers)


def test_build_set_abc_without_box_no_g_header() -> None:
    s = _make_set()
    result = build_set_abc(s, box=None)
    headers = _file_headers(result)
    assert not any(h.startswith("G:") for h in headers)


def test_build_set_abc_user_header_appended() -> None:
    s = _make_set(abc_header="P:AABB")
    result = build_set_abc(s)
    headers = _file_headers(result)
    assert any(h == "P:AABB" for h in headers)


def test_build_set_abc_user_header_overrides_auto() -> None:
    s = _make_set(title="Original Title", abc_header="T:Custom Title")
    result = build_set_abc(s)
    headers = _file_headers(result)
    t_headers = [h for h in headers if h.startswith("T:")]
    assert len(t_headers) == 1
    assert t_headers[0] == "T:Custom Title"


def test_build_set_abc_set_title_leads_x1_block() -> None:
    tune = _make_tune("The Morning Dew")
    setting = _make_setting()
    setting.is_core = True
    tune.settings = [setting]
    member = TuneSetMember(set_id=1, tune_id=1, order=0)
    member.tune = tune
    member.setting = None

    s = _make_set(title="Morning Set")
    s.members = [member]
    result = build_set_abc(s)

    # Inside X:1, the set title must appear before the tune title.
    x1_pos = result.index("X:1")
    set_t_pos = result.index("T:Morning Set", x1_pos)
    tune_t_pos = result.index("T:The Morning Dew", x1_pos)
    assert set_t_pos < tune_t_pos


def test_build_set_abc_member_produces_x_block() -> None:
    tune = _make_tune("The Morning Dew")
    setting = _make_setting()
    setting.is_core = True
    tune.settings = [setting]
    member = TuneSetMember(set_id=1, tune_id=1, order=0)
    member.tune = tune
    member.setting = None

    s = _make_set()
    s.members = [member]
    result = build_set_abc(s)
    assert "X:1" in result
    assert "T:The Morning Dew" in result


def test_build_set_abc_two_members_compact() -> None:
    tune1 = _make_tune("Tune A")
    tune2 = _make_tune("Tune B")
    s1 = _make_setting()
    s1.is_core = True
    tune1.settings = [s1]
    s2 = _make_setting()
    s2.is_core = True
    tune2.settings = [s2]

    m1 = TuneSetMember(set_id=1, tune_id=1, order=0)
    m1.tune = tune1
    m1.setting = None
    m2 = TuneSetMember(set_id=1, tune_id=2, order=1)
    m2.tune = tune2
    m2.setting = None

    s = _make_set(title="Double Set")
    s.members = [m1, m2]
    result = build_set_abc(s)
    assert "X:1" in result
    assert "X:2" not in result
    assert "T:Tune A" in result
    assert "T:Tune B" in result


def test_build_set_abc_member_uses_pinned_setting() -> None:
    tune = _make_tune()
    core = _make_setting()
    core.is_core = True
    core.source = "core source"
    pinned = _make_setting(abc=_ABC2)
    pinned.is_core = False
    pinned.source = "pinned source"
    tune.settings = [core]

    member = TuneSetMember(set_id=1, tune_id=1, order=0)
    member.tune = tune
    member.setting = pinned

    s = _make_set()
    s.members = [member]
    result = build_set_abc(s)
    assert "pinned source" in result
    assert "core source" not in result


def test_build_set_abc_no_members_returns_header_only() -> None:
    s = _make_set(title="Empty Set")
    result = build_set_abc(s)
    assert "T:Empty Set" in result
    assert "X:" not in result
