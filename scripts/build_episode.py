#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Build a Weekly Paper Digest episode page from work/YYYY-MM-DD/weekly_digest.md.

Input:
  work/YYYY-MM-DD/weekly_digest.md

Template:
  templates/episode.html

Output:
  docs/episodes/YYYY-MM-DD/index.html

Usage:
  python scripts/build_episode.py 2026-08-03
  python scripts/build_episode.py 2026-08-03 --audio audio.m4a
"""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "templates" / "episode.html"


def escape(text: str) -> str:
    return html.escape(text or "", quote=True)


def inline_markdown(text: str) -> str:
    """Convert the small subset of inline Markdown used in weekly_digest.md."""
    text = escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    return re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', text)


def get_section(md_text: str, heading: str) -> str:
    """Return a ## section, allowing a parenthetical suffix such as （任意）."""
    pattern = rf"^##\s+{re.escape(heading)}(?:（[^）]*）|\([^)]*\))?\s*$"
    match = re.search(pattern, md_text, flags=re.MULTILINE)

    if not match:
        return ""

    start = match.end()
    next_heading = re.search(r"^##\s+", md_text[start:], flags=re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(md_text)

    return md_text[start:end].strip()


def paragraphs_to_html(text: str) -> str:
    """Convert simple Markdown paragraphs/lists; ignore horizontal separators."""
    text = re.sub(r"^\s*---\s*$", "", text, flags=re.MULTILINE)
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    output: list[str] = []

    for part in parts:
        lines = [line.strip() for line in part.splitlines() if line.strip()]

        if lines and all(line.startswith("- ") for line in lines):
            items = "".join(
                f"<li>{inline_markdown(line[2:].strip())}</li>"
                for line in lines
            )
            output.append(f"<ul>{items}</ul>")
        else:
            output.append(
                f"<p>{inline_markdown(' '.join(lines))}</p>"
            )

    return "\n".join(output)


def parse_field(block: str, label: str) -> str:
    pattern = rf"^\s*[-*]\s+\*\*{re.escape(label)}:\*\*\s*(.+?)\s*$"
    match = re.search(pattern, block, flags=re.MULTILINE)

    return match.group(1).strip() if match else ""


def parse_papers(
    section_text: str,
    heading_pattern: str,
) -> list[dict[str, str]]:
    papers: list[dict[str, str]] = []

    blocks = re.split(
        heading_pattern,
        section_text,
        flags=re.MULTILINE,
    )[1:]

    for block in blocks:
        paper = {
            "title": parse_field(block, "Title"),
            "journal": parse_field(block, "Journal"),
            "doi": parse_field(block, "DOI"),
            "summary": parse_field(block, "一言要約"),
        }

        if paper["title"]:
            papers.append(paper)

    return papers


def doi_url(doi: str) -> str:
    doi = doi.strip()

    if not doi:
        return ""

    if doi.startswith(("http://", "https://")):
        return doi

    return f"https://doi.org/{doi.removeprefix('doi:').strip()}"


def render_paper_card(paper: dict[str, str]) -> str:
    journal_html = (
        f'<p class="journal">{escape(paper["journal"])}</p>'
        if paper["journal"]
        else ""
    )

    url = doi_url(paper["doi"])
    doi_html = (
        f'<p><a href="{escape(url)}">{escape(paper["doi"])}</a></p>'
        if url
        else ""
    )

    summary_html = (
        f'<p>{inline_markdown(paper["summary"])}</p>'
        if paper["summary"]
        else ""
    )

    return f"""<article class="paper-card">
  <h3>{escape(paper["title"])}</h3>
  {journal_html}
  {doi_html}
  {summary_html}
</article>"""


def render_paper_section(
    title: str,
    papers: list[dict[str, str]],
) -> str:
    cards = "\n".join(
        render_paper_card(paper)
        for paper in papers
    )

    return f"""<section class="paper-list">
  <h2>{escape(title)}</h2>
  {cards}
</section>"""


def render_text_section(title: str, text: str) -> str:
    return f"""<section>
  <h2>{escape(title)}</h2>
  {paragraphs_to_html(text)}
</section>"""


def build_content(md_text: str) -> tuple[list[str], str]:
    impression = get_section(md_text, "今週の印象")

    notable = parse_papers(
        get_section(md_text, "今週の注目論文"),
        r"^###\s+論文\d+.*$",
    )

    short_news = parse_papers(
        get_section(md_text, "今週のショートニュース"),
        r"^###\s+ショートニュース\d+.*$",
    )

    summary = get_section(md_text, "まとめ")

    sections: list[str] = []

    if impression:
        sections.append(
            render_text_section(
                "今週の印象",
                impression,
            )
        )

    sections.append(
        render_paper_section(
            "今週の注目論文",
            notable,
        )
    )

    if short_news:
        sections.append(
            render_paper_section(
                "今週のショートニュース",
                short_news,
            )
        )

    if summary:
        sections.append(
            render_text_section(
                "まとめ",
                summary,
            )
        )

    topics = [
        paper["title"]
        for paper in notable
    ]

    return topics, "\n".join(sections)


def build_topics(topics: list[str]) -> str:
    items = "".join(
        f"<li>{escape(title)}</li>"
        for title in topics
    )

    return f"<h2>今週の注目論文</h2><ol>{items}</ol>"


def build_audio(date: str, audio_file: str) -> str:
    suffix = Path(audio_file).suffix.lower()
    mime_type = "audio/mpeg" if suffix == ".mp3" else "audio/mp4"

    return f"""<audio
            id="podcast-player"
            data-episode="{escape(date)}"
            controls
            preload="metadata">
            <source src="{escape(audio_file)}" type="{mime_type}">
            </audio>"""


def build_editorial_note(date: str) -> str:
    """Build the link even if the Editorial Meeting Note does not exist yet."""
    note_name = f"editorial_meeting_notes_{date}.html"

    return f"""<p>
  <a href="../../editorial_notes/{escape(note_name)}">
    📝 Read the Editorial Note of this episode
  </a>
</p>"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a Weekly Paper Digest episode."
    )

    parser.add_argument(
        "date",
        help="Episode date (YYYY-MM-DD)",
    )

    parser.add_argument(
        "--audio",
        default="audio.mp3",
        help="Audio filename in the episode directory (default: audio.mp3)",
    )

    args = parser.parse_args()

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
        parser.error("date must be YYYY-MM-DD")

    md_path = (
        REPO_ROOT
        / "work"
        / args.date
        / "weekly_digest.md"
    )

    output_dir = (
        REPO_ROOT
        / "docs"
        / "episodes"
        / args.date
    )

    output_path = output_dir / "index.html"

    if not md_path.exists():
        raise FileNotFoundError(
            f"weekly_digest.md not found: {md_path}"
        )

    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            f"template not found: {TEMPLATE_PATH}"
        )

    md_text = md_path.read_text(encoding="utf-8")
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    topics, content = build_content(md_text)

    replacements = {
        "{{DATE}}": args.date,
        "{{AUDIO}}": build_audio(args.date, args.audio),
        "{{TOPICS}}": build_topics(topics),
        "{{CONTENT}}": content,
        "{{EDITORIAL_NOTE}}": build_editorial_note(args.date),
    }

    for placeholder, value in replacements.items():
        template = template.replace(
            placeholder,
            value,
        )

    output_dir.mkdir(
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