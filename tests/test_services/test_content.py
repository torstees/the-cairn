from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import ContentType, ContentVisibility
from cairn.services.content import get_content, list_content, upsert_content


async def test_upsert_content_creates(db: AsyncSession) -> None:
    content = await upsert_content(
        db,
        slug="getting-started",
        title="Getting Started with The Cairn",
        content_type=ContentType.page,
        body="Welcome to The Cairn.",
    )
    assert content.id is not None
    assert content.slug == "getting-started"
    assert content.title == "Getting Started with The Cairn"
    assert content.content_type == ContentType.page
    assert content.visibility == ContentVisibility.public
    assert content.body == "Welcome to The Cairn."


async def test_upsert_content_updates_by_slug(db: AsyncSession) -> None:
    original = await upsert_content(
        db,
        slug="getting-started",
        title="Getting Started",
        content_type=ContentType.page,
        body="Draft body.",
    )
    updated = await upsert_content(
        db,
        slug="getting-started",
        title="Getting Started with The Cairn",
        content_type=ContentType.page,
        body="Final body.",
        visibility=ContentVisibility.enrolled,
        metadata={"reading_minutes": 3},
    )
    assert updated.id == original.id
    assert updated.title == "Getting Started with The Cairn"
    assert updated.body == "Final body."
    assert updated.visibility == ContentVisibility.enrolled
    assert updated.metadata_ == {"reading_minutes": 3}

    all_rows = await list_content(db)
    assert len(all_rows) == 1


async def test_get_content_hit(db: AsyncSession) -> None:
    await upsert_content(
        db, slug="rolls-explained", title="Rolls Explained", content_type=ContentType.lesson, body="A roll is..."
    )
    found = await get_content(db, "rolls-explained")
    assert found is not None
    assert found.title == "Rolls Explained"


async def test_get_content_miss(db: AsyncSession) -> None:
    found = await get_content(db, "does-not-exist")
    assert found is None


async def test_list_content_without_type_filter(db: AsyncSession) -> None:
    await upsert_content(db, slug="a-page", title="A Page", content_type=ContentType.page, body="...")
    await upsert_content(db, slug="a-lesson", title="A Lesson", content_type=ContentType.lesson, body="...")

    all_rows = await list_content(db)
    assert {c.slug for c in all_rows} == {"a-page", "a-lesson"}


async def test_list_content_with_type_filter(db: AsyncSession) -> None:
    await upsert_content(db, slug="a-page", title="A Page", content_type=ContentType.page, body="...")
    await upsert_content(db, slug="a-lesson", title="A Lesson", content_type=ContentType.lesson, body="...")
    await upsert_content(db, slug="another-lesson", title="Another Lesson", content_type=ContentType.lesson, body="...")

    lessons = await list_content(db, content_type=ContentType.lesson)
    assert {c.slug for c in lessons} == {"a-lesson", "another-lesson"}


async def test_list_content_ordered_by_title(db: AsyncSession) -> None:
    await upsert_content(db, slug="zebra", title="Zebra Rolls", content_type=ContentType.page, body="...")
    await upsert_content(db, slug="apple", title="Apple Basics", content_type=ContentType.page, body="...")

    rows = await list_content(db)
    assert [c.slug for c in rows] == ["apple", "zebra"]
