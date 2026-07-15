import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import EnrollmentStatus, Role, User
from cairn.services.enrollments import (
    accept_invite,
    create_invite,
    delete_enrollment,
    get_active_enrollment_partner_ids,
    list_enrollments_for_student,
    list_enrollments_for_teacher,
)

# ── helpers ────────────────────────────────────────────────────────────────────


async def _user(db: AsyncSession, username: str, role: Role = Role.student) -> User:
    u = User(username=username, email=f"{username}@example.com", google_sub=f"google-sub-{username}", role=role)
    db.add(u)
    await db.flush()
    return u


# ── create_invite ─────────────────────────────────────────────────────────────


async def test_create_invite_success(db: AsyncSession) -> None:
    teacher = await _user(db, "teacher", role=Role.teacher)
    student = await _user(db, "student")
    enrollment = await create_invite(db, teacher.id, student.email)
    assert enrollment is not None
    assert enrollment.teacher_id == teacher.id
    assert enrollment.student_id == student.id
    assert enrollment.status == EnrollmentStatus.pending


async def test_create_invite_returns_none_for_unknown_email(db: AsyncSession) -> None:
    teacher = await _user(db, "teacher", role=Role.teacher)
    result = await create_invite(db, teacher.id, "nobody@example.com")
    assert result is None


async def test_create_invite_returns_none_for_self_invite(db: AsyncSession) -> None:
    teacher = await _user(db, "teacher", role=Role.teacher)
    result = await create_invite(db, teacher.id, teacher.email)
    assert result is None


async def test_create_invite_email_lookup_is_case_insensitive(db: AsyncSession) -> None:
    teacher = await _user(db, "teacher", role=Role.teacher)
    student = await _user(db, "student")
    enrollment = await create_invite(db, teacher.id, student.email.upper())
    assert enrollment is not None
    assert enrollment.student_id == student.id


async def test_create_invite_duplicate_raises_integrity_error(db: AsyncSession) -> None:
    teacher = await _user(db, "teacher", role=Role.teacher)
    student = await _user(db, "student")
    await create_invite(db, teacher.id, student.email)
    with pytest.raises(IntegrityError):
        await create_invite(db, teacher.id, student.email)


# ── accept_invite ──────────────────────────────────────────────────────────────


async def test_accept_invite_success(db: AsyncSession) -> None:
    teacher = await _user(db, "teacher", role=Role.teacher)
    student = await _user(db, "student")
    enrollment = await create_invite(db, teacher.id, student.email)
    accepted = await accept_invite(db, enrollment.id, student.id)
    assert accepted is not None
    assert accepted.status == EnrollmentStatus.active


async def test_accept_invite_wrong_student_returns_none(db: AsyncSession) -> None:
    teacher = await _user(db, "teacher", role=Role.teacher)
    student = await _user(db, "student")
    other = await _user(db, "other")
    enrollment = await create_invite(db, teacher.id, student.email)
    result = await accept_invite(db, enrollment.id, other.id)
    assert result is None


async def test_accept_invite_unknown_id_returns_none(db: AsyncSession) -> None:
    student = await _user(db, "student")
    result = await accept_invite(db, 9999, student.id)
    assert result is None


# ── delete_enrollment ──────────────────────────────────────────────────────────


async def test_delete_enrollment_by_teacher(db: AsyncSession) -> None:
    teacher = await _user(db, "teacher", role=Role.teacher)
    student = await _user(db, "student")
    enrollment = await create_invite(db, teacher.id, student.email)
    assert await delete_enrollment(db, enrollment.id, teacher.id) is True


async def test_delete_enrollment_by_student(db: AsyncSession) -> None:
    teacher = await _user(db, "teacher", role=Role.teacher)
    student = await _user(db, "student")
    enrollment = await create_invite(db, teacher.id, student.email)
    assert await delete_enrollment(db, enrollment.id, student.id) is True


async def test_delete_enrollment_by_non_party_returns_false(db: AsyncSession) -> None:
    teacher = await _user(db, "teacher", role=Role.teacher)
    student = await _user(db, "student")
    other = await _user(db, "other")
    enrollment = await create_invite(db, teacher.id, student.email)
    assert await delete_enrollment(db, enrollment.id, other.id) is False


# ── list_enrollments_for_teacher / list_enrollments_for_student ───────────────


async def test_list_enrollments_for_teacher(db: AsyncSession) -> None:
    teacher = await _user(db, "teacher", role=Role.teacher)
    student = await _user(db, "student")
    await create_invite(db, teacher.id, student.email)
    result = await list_enrollments_for_teacher(db, teacher.id)
    assert len(result) == 1
    assert result[0].student.username == "student"


async def test_list_enrollments_for_student(db: AsyncSession) -> None:
    teacher = await _user(db, "teacher", role=Role.teacher)
    student = await _user(db, "student")
    await create_invite(db, teacher.id, student.email)
    result = await list_enrollments_for_student(db, student.id)
    assert len(result) == 1
    assert result[0].teacher.username == "teacher"


# ── get_active_enrollment_partner_ids ──────────────────────────────────────────


async def test_partner_ids_excludes_pending_invites(db: AsyncSession) -> None:
    teacher = await _user(db, "teacher", role=Role.teacher)
    student = await _user(db, "student")
    await create_invite(db, teacher.id, student.email)
    assert await get_active_enrollment_partner_ids(db, teacher.id) == set()
    assert await get_active_enrollment_partner_ids(db, student.id) == set()


async def test_partner_ids_includes_active_enrollment_both_directions(db: AsyncSession) -> None:
    teacher = await _user(db, "teacher", role=Role.teacher)
    student = await _user(db, "student")
    enrollment = await create_invite(db, teacher.id, student.email)
    await accept_invite(db, enrollment.id, student.id)

    assert await get_active_enrollment_partner_ids(db, teacher.id) == {student.id}
    assert await get_active_enrollment_partner_ids(db, student.id) == {teacher.id}


async def test_partner_ids_empty_for_unenrolled_user(db: AsyncSession) -> None:
    lone = await _user(db, "lone")
    assert await get_active_enrollment_partner_ids(db, lone.id) == set()
