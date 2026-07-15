from urllib.parse import unquote

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import ContentVisibility, EnrollmentStatus, KeyMode, KeyRoot, Role, TuneType, User
from cairn.schemas import TuneCreate
from cairn.services.enrollments import accept_invite, create_invite
from cairn.services.tunes import create_tune

_ABC = "X:1\nT:x\nK:D\n|:DEFA BAFA|DEFA BAFA:|"


async def _other_user(db: AsyncSession, username: str, role: Role = Role.student) -> User:
    u = User(username=username, email=f"{username}@example.com", google_sub=f"google-sub-{username}", role=role)
    db.add(u)
    await db.flush()
    return u


async def _make_teacher(db: AsyncSession, user: User) -> None:
    user.role = Role.teacher
    await db.flush()


# ── enrollment_index ──────────────────────────────────────────────────────────


async def test_enrollment_index_shows_invite_form_for_teacher(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    await _make_teacher(db, user)
    resp = await client.get("/enrollments")
    assert resp.status_code == 200
    assert "Invite a Student" in resp.text


async def test_enrollment_index_hides_invite_form_for_student(client: AsyncClient) -> None:
    resp = await client.get("/enrollments")
    assert resp.status_code == 200
    assert "Invite a Student" not in resp.text


async def test_enrollment_index_shows_pending_invite_for_student(
    client: AsyncClient, db: AsyncSession, user: User
) -> None:
    teacher = await _other_user(db, "teacher", role=Role.teacher)
    await create_invite(db, teacher.id, user.email)
    resp = await client.get("/enrollments")
    assert resp.status_code == 200
    assert "teacher invited you" in resp.text


async def test_enrollment_index_shows_error_message(client: AsyncClient) -> None:
    resp = await client.get("/enrollments", params={"error": "Something went wrong"})
    assert resp.status_code == 200
    assert "Something went wrong" in resp.text


# ── enrollment_invite ──────────────────────────────────────────────────────────


async def test_invite_forbidden_for_non_teacher(client: AsyncClient) -> None:
    resp = await client.post("/enrollments/invite", data={"student_email": "student@example.com"})
    assert resp.status_code == 403


async def test_invite_success_creates_pending_enrollment(client: AsyncClient, db: AsyncSession, user: User) -> None:
    await _make_teacher(db, user)
    student = await _other_user(db, "student")
    resp = await client.post("/enrollments/invite", data={"student_email": student.email}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/enrollments"

    resp = await client.get("/enrollments")
    assert "student" in resp.text


async def test_invite_unknown_email_redirects_with_error(client: AsyncClient, db: AsyncSession, user: User) -> None:
    await _make_teacher(db, user)
    resp = await client.post(
        "/enrollments/invite", data={"student_email": "nobody@example.com"}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert unquote(resp.headers["location"]) == "/enrollments?error=No account found for nobody@example.com"


async def test_invite_duplicate_redirects_with_error(client: AsyncClient, db: AsyncSession, user: User) -> None:
    await _make_teacher(db, user)
    student = await _other_user(db, "student")
    await client.post("/enrollments/invite", data={"student_email": student.email})
    resp = await client.post("/enrollments/invite", data={"student_email": student.email}, follow_redirects=False)
    assert resp.status_code == 303
    assert "already" in resp.headers["location"]


# ── enrollment_accept ──────────────────────────────────────────────────────────


async def test_accept_invite_success(client: AsyncClient, db: AsyncSession, user: User) -> None:
    teacher = await _other_user(db, "teacher", role=Role.teacher)
    enrollment = await create_invite(db, teacher.id, user.email)
    resp = await client.post(f"/enrollments/{enrollment.id}/accept", follow_redirects=False)
    assert resp.status_code == 303
    await db.refresh(enrollment)
    assert enrollment.status == EnrollmentStatus.active


async def test_accept_invite_404_for_another_users_invite(client: AsyncClient, db: AsyncSession) -> None:
    teacher = await _other_user(db, "teacher", role=Role.teacher)
    other_student = await _other_user(db, "other-student")
    enrollment = await create_invite(db, teacher.id, other_student.email)
    resp = await client.post(f"/enrollments/{enrollment.id}/accept")
    assert resp.status_code == 404


# ── enrollment_delete ──────────────────────────────────────────────────────────


async def test_delete_enrollment_by_teacher(client: AsyncClient, db: AsyncSession, user: User) -> None:
    await _make_teacher(db, user)
    student = await _other_user(db, "student")
    enrollment = await create_invite(db, user.id, student.email)
    resp = await client.delete(f"/enrollments/{enrollment.id}")
    assert resp.status_code == 200


async def test_delete_enrollment_404_for_non_party(client: AsyncClient, db: AsyncSession) -> None:
    teacher = await _other_user(db, "teacher", role=Role.teacher)
    other_student = await _other_user(db, "other-student")
    enrollment = await create_invite(db, teacher.id, other_student.email)
    resp = await client.delete(f"/enrollments/{enrollment.id}")
    assert resp.status_code == 404


# ── enrolled-visibility tune filtering ─────────────────────────────────────────


async def _seed_enrolled_tune(db: AsyncSession, creator_id: int, title: str = "Enrolled Tune"):
    return await create_tune(
        db,
        TuneCreate(
            title=title,
            tune_type=TuneType.reel,
            key_root=KeyRoot.D,
            key_mode=KeyMode.major,
            time_signature="4/4",
            created_by=creator_id,
            visibility=ContentVisibility.enrolled,
        ),
        abc_notation=_ABC,
    )


async def test_enrolled_tune_visible_to_active_partner(client: AsyncClient, db: AsyncSession, user: User) -> None:
    teacher = await _other_user(db, "teacher", role=Role.teacher)
    enrollment = await create_invite(db, teacher.id, user.email)
    await accept_invite(db, enrollment.id, user.id)
    tune = await _seed_enrolled_tune(db, teacher.id)

    resp = await client.get(f"/tunes/{tune.id}")
    assert resp.status_code == 200
    resp = await client.get("/tunes/")
    assert tune.title in resp.text


async def test_enrolled_tune_hidden_from_pending_invite(client: AsyncClient, db: AsyncSession, user: User) -> None:
    teacher = await _other_user(db, "teacher", role=Role.teacher)
    await create_invite(db, teacher.id, user.email)  # never accepted
    tune = await _seed_enrolled_tune(db, teacher.id)

    resp = await client.get(f"/tunes/{tune.id}")
    assert resp.status_code == 404
    resp = await client.get("/tunes/")
    assert tune.title not in resp.text


async def test_enrolled_tune_hidden_from_unrelated_user(client: AsyncClient, db: AsyncSession) -> None:
    # The logged-in `user` fixture has no enrollment relationship with `teacher` at all.
    teacher = await _other_user(db, "teacher", role=Role.teacher)
    tune = await _seed_enrolled_tune(db, teacher.id)

    resp = await client.get(f"/tunes/{tune.id}")
    assert resp.status_code == 404
    resp = await client.get("/tunes/")
    assert tune.title not in resp.text
