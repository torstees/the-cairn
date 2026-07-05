#!/usr/bin/env python
"""
Import markdown content pages into The Cairn database.

Usage:
    uv run python scripts/import_content.py [path/to/content/dir]
    Defaults to content/ relative to the project root.

Each *.md file must have a YAML front matter block with required keys
`slug`, `title`, `content_type`. Optional keys: `visibility`, `metadata`.

    ---
    slug: getting-started
    title: Getting Started with The Cairn
    content_type: page
    visibility: public
    ---
    Markdown body here…

Files are upserted by slug, so re-running the import updates existing
records rather than duplicating them.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio

import frontmatter

from cairn.database import AsyncSessionLocal
from cairn.models import ContentType, ContentVisibility
from cairn.services.content import upsert_content


def _parse_file(path: Path) -> dict | None:
    """Return {'slug', 'title', 'content_type', 'visibility', 'metadata', 'body'} or None if invalid."""
    post = frontmatter.load(path)
    slug = post.get("slug")
    title = post.get("title")
    content_type_raw = post.get("content_type")
    if not slug or not title or not content_type_raw:
        return None

    try:
        content_type = ContentType(content_type_raw)
    except ValueError:
        return None

    visibility_raw = post.get("visibility", ContentVisibility.public.value)
    try:
        visibility = ContentVisibility(visibility_raw)
    except ValueError:
        return None

    return {
        "slug": slug,
        "title": title,
        "content_type": content_type,
        "visibility": visibility,
        "metadata": post.get("metadata"),
        "body": post.content,
    }


async def main(content_dir: Path) -> None:
    files = sorted(content_dir.glob("*.md"))
    print(f"Found {len(files)} candidate files in {content_dir}\n")

    imported = skipped_err = 0
    warnings: list[str] = []

    async with AsyncSessionLocal() as db:
        for path in files:
            parsed = _parse_file(path)
            if parsed is None:
                warnings.append(f"SKIP (fields)   {path.name}")
                skipped_err += 1
                continue

            await upsert_content(
                db,
                slug=parsed["slug"],
                title=parsed["title"],
                content_type=parsed["content_type"],
                body=parsed["body"],
                visibility=parsed["visibility"],
                metadata=parsed["metadata"],
            )
            print(f"  OK  {parsed['slug']}  ({parsed['title']})")
            imported += 1

    print(f"\n{imported} imported   {skipped_err} errors")
    if warnings:
        print("\nWarnings / skipped:")
        for w in warnings:
            print(f"  {w}")


if __name__ == "__main__":
    content_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent / "content"
    if not content_dir.is_dir():
        print(f"Error: {content_dir} is not a directory", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(content_dir))
