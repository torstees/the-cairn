import logging
import re

import markdown
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.models import Content, ContentType, ContentVisibility

logger = logging.getLogger(__name__)

_MARKDOWN_EXTENSIONS = ["attr_list", "tables", "extra", "nl2br"]

# The Tailwind CDN build has no Typography plugin, so headings/links/tables/
# etc. rendered from markdown carry no styling by default. attr_list lets an
# author override any single element with {.class}; these are the fallback
# classes applied to every element of that tag that doesn't already have one.
_DEFAULT_CLASSES: dict[str, str] = {
    "h1": "text-3xl font-bold text-stone-800 mt-6 mb-3",
    "h2": "text-2xl font-bold text-stone-800 mt-6 mb-3",
    "h3": "text-xl font-semibold text-stone-700 mt-5 mb-2",
    "h4": "text-lg font-semibold text-stone-700 mt-4 mb-2",
    "h5": "text-lg font-semibold text-stone-700 mt-4 mb-2",
    "h6": "text-lg font-semibold text-stone-700 mt-4 mb-2",
    "a": "text-stone-700 underline hover:text-stone-900",
    "table": "w-full border-collapse text-sm",
    "th": "border border-stone-300 bg-stone-100 px-3 py-2 text-left font-semibold",
    "td": "border border-stone-300 px-3 py-2",
    "img": "max-w-full rounded-lg",
    "ul": "list-disc list-inside space-y-1",
    "ol": "list-decimal list-inside space-y-1",
    "blockquote": "border-l-4 border-stone-300 pl-4 italic text-stone-600",
    "code": "font-mono text-sm",
    "pre": "bg-stone-800 text-stone-100 p-4 rounded-lg overflow-x-auto text-sm",
}

_TAG_RE = re.compile(r"<(" + "|".join(_DEFAULT_CLASSES) + r")(\s[^>]*)?>")


def _inject_default_class(match: re.Match) -> str:
    tag = match.group(1)
    attrs = match.group(2) or ""
    default = _DEFAULT_CLASSES[tag]
    class_match = re.search(r'class="([^"]*)"', attrs)
    if class_match:
        # Author already set a class via attr_list — merge rather than clobber.
        merged = f"{class_match.group(1)} {default}".strip()
        attrs = attrs[: class_match.start()] + f'class="{merged}"' + attrs[class_match.end() :]
    else:
        attrs = f' class="{default}"{attrs}'
    return f"<{tag}{attrs}>"


def render_markdown(body: str) -> str:
    """Render markdown body to HTML, applying default Tailwind utility classes per element."""
    html = markdown.markdown(body, extensions=_MARKDOWN_EXTENSIONS)
    return _TAG_RE.sub(_inject_default_class, html)


async def upsert_content(
    db: AsyncSession,
    slug: str,
    title: str,
    content_type: ContentType,
    body: str,
    visibility: ContentVisibility = ContentVisibility.public,
    metadata: dict | None = None,
    created_by: int | None = None,
) -> Content:
    """Insert or update a Content record by slug."""
    result = await db.execute(select(Content).where(Content.slug == slug))
    content = result.scalar_one_or_none()
    if content is None:
        content = Content(slug=slug)
        db.add(content)

    content.title = title
    content.content_type = content_type
    content.body = body
    content.visibility = visibility
    content.metadata_ = metadata
    content.created_by = created_by

    await db.commit()
    await db.refresh(content)
    logger.info("content upserted", extra={"slug": slug, "content_type": content_type.value})
    return content


async def get_content(db: AsyncSession, slug: str) -> Content | None:
    result = await db.execute(select(Content).where(Content.slug == slug))
    return result.scalar_one_or_none()


async def list_content(db: AsyncSession, content_type: ContentType | None = None) -> list[Content]:
    stmt = select(Content).order_by(Content.title)
    if content_type is not None:
        stmt = stmt.where(Content.content_type == content_type)
    result = await db.execute(stmt)
    return list(result.scalars().all())
