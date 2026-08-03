#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Build an Editorial Meeting Note HTML page.

Input:
  work/YYYY-MM-DD/editorial_meeting_notes_YYYY-MM-DD.md

Template:
  templates/editorial_meeting_note.html

Output:
  docs/editorial_notes/editorial_meeting_notes_YYYY-MM-DD.html

Usage:
  python scripts/build_editorial_note.py 2026-08-03
"""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "templates" / "editorial_meeting_note.html"


def escape(text: str) -> str:
    return html.escape(text or "", quote=True)


def inline_markdown(text: str) -> str:
    """Convert the small subset of inline Markdown used in meeting notes."""
    text = escape(text)

    # inline code
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)

    # bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)

    # italic
    text = re.sub(
        r"(?<!\*)\*([^*\n]+?)\*(?!\*)",
        r"<em>\1</em>",
        text,
    )

    # Markdown links
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2">\1</a>',
        text,
    )

    # Bare URLs
    text = re.sub(
        r'(?<!href=")(https?://[^\s<]+)',
        r'<a href="\1">\1</a>',
        text,
    )

    return text


def extract_title(md: str) -> str:
    """Use the first H1 as the page title."""
    match = re.search(r"^#\s+(.+?)\s*$", md, flags=re.MULTILINE)

    if match:
        return re.sub(
            r"\*\*(.+?)\*\*",
            r"\1",
            match.group(1).strip(),
        )

    return "Editorial Meeting Notes"


def strip_first_h1(md: str) -> str:
    """Remove the first H1 because the template renders the page title."""
    return re.sub(
        r"^\s*#\s+.+?\s*\n+",
        "",
        md,
        count=1,
        flags=re.MULTILINE,
    )


def markdown_to_html(md: str) -> str:
    """Convert the simple Markdown used in Editorial Meeting Notes to HTML."""
    md = strip_first_h1(md)
    lines = md.splitlines()

    html_parts: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    blockquote_lines: list[str] = []

    in_code = False
    code_lang = ""
    code_lines: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph

        if paragraph:
            text = " ".join(
                line.strip()
                for line in paragraph
                if line.strip()
            )
            html_parts.append(
                f"<p>{inline_markdown(text)}</p>"
            )
            paragraph = []

    def flush_list() -> None:
        nonlocal list_items

        if list_items:
            html_parts.append("<ul>")
            for item in list_items:
                html_parts.append(
                    f"<li>{inline_markdown(item)}</li>"
                )
            html_parts.append("</ul>")
            list_items = []

    def flush_blockquote() -> None:
        nonlocal blockquote_lines

        if blockquote_lines:
            inner = " ".join(
                line.strip()
                for line in blockquote_lines
                if line.strip()
            )
            html_parts.append(
                f"<blockquote><p>{inline_markdown(inner)}</p></blockquote>"
            )
            blockquote_lines = []

    for line in lines:
        # fenced code block
        code_match = re.match(r"^```(\w+)?\s*$", line)

        if code_match:
            if not in_code:
                flush_paragraph()
                flush_list()
                flush_blockquote()

                in_code = True
                code_lang = code_match.group(1) or ""
                code_lines = []
            else:
                code_html = escape("\n".join(code_lines))
                css_class = (
                    f' class="language-{escape(code_lang)}"'
                    if code_lang
                    else ""
                )
                html_parts.append(
                    f"<pre><code{css_class}>{code_html}</code></pre>"
                )

                in_code = False
                code_lang = ""
                code_lines = []

            continue

        if in_code:
            code_lines.append(line)
            continue

        # horizontal rule
        if re.match(r"^\s*---+\s*$", line):
            flush_paragraph()
            flush_list()
            flush_blockquote()
            continue

        # heading
        heading_match = re.match(
            r"^(#{1,6})\s+(.+?)\s*$",
            line,
        )

        if heading_match:
            flush_paragraph()
            flush_list()
            flush_blockquote()

            level = len(heading_match.group(1))
            heading = heading_match.group(2).strip()

            html_parts.append(
                f"<h{level}>{inline_markdown(heading)}</h{level}>"
            )
            continue

        # blockquote
        quote_match = re.match(r"^>\s?(.*)$", line)

        if quote_match:
            flush_paragraph()
            flush_list()

            blockquote_lines.append(
                quote_match.group(1).strip()
            )
            continue

        # unordered list
        list_match = re.match(
            r"^\s*[-*]\s+(.+?)\s*$",
            line,
        )

        if list_match:
            flush_paragraph()
            flush_blockquote()

            list_items.append(
                list_match.group(1).strip()
            )
            continue

        # blank line
        if not line.strip():
            flush_paragraph()
            flush_list()
            flush_blockquote()
            continue

        paragraph.append(line)

    flush_paragraph()
    flush_list()
    flush_blockquote()

    if in_code:
        code_html = escape("\n".join(code_lines))
        css_class = (
            f' class="language-{escape(code_lang)}"'
            if code_lang
            else ""
        )
        html_parts.append(
            f"<pre><code{css_class}>{code_html}</code></pre>"
        )

    return "\n".join(html_parts)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build an Editorial Meeting Note HTML page."
    )

    parser.add_argument(
        "date",
        help="Meeting date (YYYY-MM-DD)",
    )

    args = parser.parse_args()

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
        parser.error("date must be YYYY-MM-DD")

    filename = f"editorial_meeting_notes_{args.date}"

    md_path = (
        REPO_ROOT
        / "work"
        / args.date
        / f"{filename}.md"
    )

    output_path = (
        REPO_ROOT
        / "docs"
        / "editorial_notes"
        / f"{filename}.html"
    )

    if not md_path.exists():
        raise FileNotFoundError(
            f"Editorial Meeting Note not found: {md_path}"
        )

    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            f"Markdown template not found: {TEMPLATE_PATH}"
        )

    md_text = md_path.read_text(encoding="utf-8")
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    replacements = {
        "{{TITLE}}": escape(extract_title(md_text)),
        "{{DATE}}": escape(args.date),
        "{{CONTENT}}": markdown_to_html(md_text),
    }

    for placeholder, value in replacements.items():
        template = template.replace(
            placeholder,
            value,
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        template,
        encoding="utf-8",
    )

    print(
        f"input : {md_path.relative_to(REPO_ROOT)}"
    )
    print(
        f"output: {output_path.relative_to(REPO_ROOT)}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
