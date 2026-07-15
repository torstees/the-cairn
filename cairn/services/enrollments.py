from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cairn.models import Enrollment, EnrollmentStatus, User


async def create_invite(db: AsyncSession, teacher_id: int, student_email: str) -> Enrollment | None:
    """Invite a student by email. Returns None if no account exists with that
    email, or if the teacher tries to invite themselves.

    No email is actually sent (no email-sending infrastructure exists) — the
    invite just becomes visible to the student the next time they view their
    own pending invitations.
    """
    result = await db.execute(select(User).where(User.email == student_email.strip().lower()))
    student = result.scalar_one_or_none()
    if student is None or student.id == teacher_id:
        return None

    enrollment = Enrollment(teacher_id=teacher_id, student_id=student.id, status=EnrollmentStatus.pending)
    db.add(enrollment)
    await db.commit()
    await db.refresh(enrollment)
    return enrollment


async def accept_invite(db: AsyncSession, enrollment_id: int, student_id: int) -> Enrollment | None:
    enrollment = await db.get(Enrollment, enrollment_id)
    if enrollment is None or enrollment.student_id != student_id:
        return None
    enrollment.status = EnrollmentStatus.active
    await db.commit()
    await db.refresh(enrollment)
    return enrollment


async def delete_enrollment(db: AsyncSession, enrollment_id: int, user_id: int) -> bool:
    """Remove an enrollment — a teacher rescinding/ending it, or a student
    declining/leaving it. Either party on the row may do this."""
    enrollment = await db.get(Enrollment, enrollment_id)
    if enrollment is None or user_id not in (enrollment.teacher_id, enrollment.student_id):
        return False
    await db.delete(enrollment)
    await db.commit()
    return True


async def list_enrollments_for_teacher(db: AsyncSession, teacher_id: int) -> list[Enrollment]:
    result = await db.execute(
        select(Enrollment)
        .where(Enrollment.teacher_id == teacher_id)
        .options(selectinload(Enrollment.student))
        .order_by(Enrollment.created_at)
    )
    return list(result.scalars().all())


async def list_enrollments_for_student(db: AsyncSession, student_id: int) -> list[Enrollment]:
    result = await db.execute(
        select(Enrollment)
        .where(Enrollment.student_id == student_id)
        .options(selectinload(Enrollment.teacher))
        .order_by(Enrollment.created_at)
    )
    return list(result.scalars().all())


async def get_active_enrollment_partner_ids(db: AsyncSession, user_id: int) -> set[int]:
    """Every user_id actively enrolled with user_id, teacher or student side —
    used to decide visibility for ContentVisibility.enrolled tunes/settings."""
    result = await db.execute(
        select(Enrollment.teacher_id, Enrollment.student_id).where(
            Enrollment.status == EnrollmentStatus.active,
            or_(Enrollment.teacher_id == user_id, Enrollment.student_id == user_id),
        )
    )
    partner_ids: set[int] = set()
    for teacher_id, student_id in result.all():
        partner_ids.add(student_id if teacher_id == user_id else teacher_id)
    return partner_ids
