from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import ContentType, ContentVisibility, Role, User
from cairn.services.content import upsert_content
from cairn.services.enrollments import accept_invite, create_invite


async def _other_user(db: AsyncSession, username: str, role: Role = Role.student) -> User:
    u = User(username=username, email=f"{username}@example.com", google_sub=f"google-sub-{username}", role=role)
    db.add(u)
    await db.flush()
    return u


async def test_content_page_renders(client: AsyncClient, db: AsyncSession) -> None:
    await upsert_content(
        db,
        slug="getting-started",
        title="Getting Started with The Cairn",
        content_type=ContentType.page,
        body="Welcome to **The Cairn**.",
    )
    resp = await client.get("/pages/getting-started")
    assert resp.status_code == 200
    assert "Getting Started with The Cairn" in resp.text
    assert "<strong>The Cairn</strong>" in resp.text


async def test_content_page_404_for_unknown_slug(client: AsyncClient) -> None:
    resp = await client.get("/pages/does-not-exist")
    assert resp.status_code == 404


async def test_content_page_404_for_private_visibility(client: AsyncClient, db: AsyncSession) -> None:
    await upsert_content(
        db,
        slug="teacher-notes",
        title="Teacher Notes",
        content_type=ContentType.page,
        body="Internal notes.",
        visibility=ContentVisibility.private,
    )
    resp = await client.get("/pages/teacher-notes")
    assert resp.status_code == 404


async def test_content_page_visible_for_enrolled(client: AsyncClient, db: AsyncSession, user: User) -> None:
    teacher = await _other_user(db, "teacher", role=Role.teacher)
    enrollment = await create_invite(db, teacher.id, user.email)
    await accept_invite(db, enrollment.id, user.id)
    await upsert_content(
        db,
        slug="lesson-one",
        title="Lesson One",
        content_type=ContentType.lesson,
        body="Enrolled-only content.",
        visibility=ContentVisibility.enrolled,
        created_by=teacher.id,
    )
    resp = await client.get("/pages/lesson-one")
    assert resp.status_code == 200
    assert "Enrolled-only content." in resp.text


async def test_content_page_404_for_enrolled_without_partnership(client: AsyncClient, db: AsyncSession) -> None:
    # The logged-in `user` fixture has no enrollment relationship with `teacher` at all.
    teacher = await _other_user(db, "teacher", role=Role.teacher)
    await upsert_content(
        db,
        slug="lesson-two",
        title="Lesson Two",
        content_type=ContentType.lesson,
        body="Enrolled-only content.",
        visibility=ContentVisibility.enrolled,
        created_by=teacher.id,
    )
    resp = await client.get("/pages/lesson-two")
    assert resp.status_code == 404


async def test_content_page_404_for_enrolled_guest(unauthenticated_client: AsyncClient, db: AsyncSession) -> None:
    await upsert_content(
        db,
        slug="lesson-three",
        title="Lesson Three",
        content_type=ContentType.lesson,
        body="Enrolled-only content.",
        visibility=ContentVisibility.enrolled,
    )
    resp = await unauthenticated_client.get("/pages/lesson-three")
    assert resp.status_code == 404


async def test_content_page_visible_for_guest_when_public(
    unauthenticated_client: AsyncClient, db: AsyncSession
) -> None:
    await upsert_content(
        db,
        slug="getting-started-guest",
        title="Getting Started with The Cairn",
        content_type=ContentType.page,
        body="Welcome to **The Cairn**.",
    )
    resp = await unauthenticated_client.get("/pages/getting-started-guest")
    assert resp.status_code == 200
    assert "Getting Started with The Cairn" in resp.text


async def test_content_page_applies_default_heading_classes(client: AsyncClient, db: AsyncSession) -> None:
    await upsert_content(
        db,
        slug="rolls",
        title="Rolls",
        content_type=ContentType.technique_guide,
        body="## Why Rolls Exist\n\nRolls maintain pulse on sustained notes.",
    )
    resp = await client.get("/pages/rolls")
    assert resp.status_code == 200
    assert '<h2 class="text-2xl font-bold text-stone-800 mt-6 mb-3">Why Rolls Exist</h2>' in resp.text
