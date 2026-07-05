from cairn.services.content import render_markdown


def test_render_markdown_basic_paragraph() -> None:
    assert "<p>Hello world.</p>" in render_markdown("Hello world.")


def test_render_markdown_applies_default_h1_classes() -> None:
    html = render_markdown("# Title")
    assert '<h1 class="text-3xl font-bold text-stone-800 mt-6 mb-3">Title</h1>' in html


def test_render_markdown_nl2br_extension() -> None:
    # nl2br turns a single newline within a paragraph into <br>, unlike bare python-markdown.
    html = render_markdown("Line one\nLine two")
    assert "<br" in html


def test_render_markdown_tables_extension() -> None:
    body = "| A | B |\n|---|---|\n| 1 | 2 |\n"
    html = render_markdown(body)
    assert "<table" in html
    assert "<th" in html


def test_render_markdown_attr_list_extension() -> None:
    html = render_markdown("# Title {.text-5xl}")
    # attr_list's author class is merged with, not replaced by, the default classes.
    assert 'class="text-5xl text-3xl font-bold text-stone-800 mt-6 mb-3"' in html


def test_render_markdown_link_gets_default_class() -> None:
    html = render_markdown("[The Cairn](https://example.com)")
    assert '<a class="text-stone-700 underline hover:text-stone-900" href="https://example.com">' in html
