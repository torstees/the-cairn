from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.dependencies import get_current_user, get_db
from cairn.models import Enrollment, EnrollmentStatus, Role, User
from cairn.services.enrollments import (
    accept_invite,
    create_invite,
    delete_enrollment,
    list_enrollments_for_student,
    list_enrollments_for_teacher,
)
from cairn.templating import templates

router = APIRouter(prefix="/enrollments", tags=["enrollments"])


async def _get_owned_enrollment(db: AsyncSession, user_id: int, enrollment_id: int) -> Enrollment:
    """Fetch an enrollment the user is a party to (teacher or student side),
    or 404 — a missing row and a non-party look identical to the caller."""
    enrollment = await db.get(Enrollment, enrollment_id)
    if enrollment is None or user_id not in (enrollment.teacher_id, enrollment.student_id):
        raise HTTPException(status_code=404, detail="Enrollment not found")
    return enrollment


@router.get("")
async def enrollment_index(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    error: str | None = None,
) -> Response:
    as_teacher = await list_enrollments_for_teacher(db, user.id)
    as_student = await list_enrollments_for_student(db, user.id)
    return templates.TemplateResponse(
        request,
        "enrollments/index.html",
        {
            "is_teacher": user.role == Role.teacher,
            "students": [e for e in as_teacher if e.status == EnrollmentStatus.active],
            "sent_invites": [e for e in as_teacher if e.status == EnrollmentStatus.pending],
            "teachers": [e for e in as_student if e.status == EnrollmentStatus.active],
            "pending_invites": [e for e in as_student if e.status == EnrollmentStatus.pending],
            "error": error,
        },
    )


@router.post("/invite")
async def enrollment_invite(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    student_email: str = Form(...),
) -> Response:
    if user.role != Role.teacher:
        raise HTTPException(status_code=403, detail="Only teachers can invite students")
    try:
        enrollment = await create_invite(db, user.id, student_email)
    except IntegrityError:
        message = quote(f"{student_email} is already on your roster or has a pending invite")
        return RedirectResponse(f"/enrollments?error={message}", status_code=303)
    if enrollment is None:
        message = quote(f"No account found for {student_email}")
        return RedirectResponse(f"/enrollments?error={message}", status_code=303)
    return RedirectResponse("/enrollments", status_code=303)


@router.post("/{enrollment_id}/accept")
async def enrollment_accept(
    enrollment_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    await _get_owned_enrollment(db, user.id, enrollment_id)
    result = await accept_invite(db, enrollment_id, user.id)
    if result is None:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    return RedirectResponse("/enrollments", status_code=303)


@router.delete("/{enrollment_id}")
async def enrollment_delete(
    enrollment_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    await _get_owned_enrollment(db, user.id, enrollment_id)
    await delete_enrollment(db, enrollment_id, user.id)
    return Response(status_code=200, headers={"HX-Redirect": "/enrollments"})
