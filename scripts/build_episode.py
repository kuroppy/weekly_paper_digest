#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a WPD episode HTML page from editorial_selection_YYYY-MM-DD.json.

Run from any directory:
    python scripts/build_episode.py 2026-10-12
    python scripts/build_episode.py 2026-10-12 --audio audio.m4a
    python scripts/build_episode.py 2026-10-12 --json /path/to/selection.json

Default input:  work/YYYY-MM-DD/editorial_selection_YYYY-MM-DD.json
Template:       templates/episode.html
Output:         docs/episodes/YYYY-MM-DD/index.html

The selection JSON is the source of truth. Abstracts, editorial comments and
review scores are deliberately not included on the public episode page.
"""
from __future__ import annotations

import argparse
import html
import json
import re
from datetime import date as Date
from pathlib import Path
from urllib.parse import quote, urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "templates" / "episode.html"
REQUIRED_PLACEHOLDERS = (
    "{{DATE}}", "{{AUDIO}}", "{{TOPICS}}", "{{CONTENT}}",
    "{{CURATION_NOTE}}", "{{EDITORIAL_NOTE}}",
)


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def load_selection(path: Path, episode_date: str) -> dict:
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or data.get("episode") != episode_date:
        raise ValueError(f"JSON episode must match requested date {episode_date}")
    if not isinstance(data.get("papers"), list) or not data["papers"]:
        raise ValueError("JSON must contain a nonempty 'papers' list")
    return data


def extract_papers(data: dict) -> tuple[list[dict], list[dict]]:
    sections: dict[str, list[dict]] = {"main_papers": [], "short_news": []}
    seen: set[str] = set()
    for i, entry in enumerate(data["papers"], 1):
        if not isinstance(entry, dict):
            raise ValueError(f"papers[{i}] must be an object")
        section = entry.get("section")
        if section not in sections:
            raise ValueError(f"papers[{i}] has unsupported section: {section!r}")
        order = entry.get("order")
        if type(order) is not int or order < 1:
            raise ValueError(f"papers[{i}].order must be a positive integer")
        paper = entry.get("paper")
        if not isinstance(paper, dict):
            raise ValueError(f"papers[{i}].paper must be an object")
        for key in ("title", "journal", "doi"):
            if not isinstance(paper.get(key), str) or not paper[key].strip():
                raise ValueError(f"papers[{i}].paper.{key} is required")
        doi = paper["doi"].strip()
        doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.I)
        doi_key = doi.casefold()
        if doi_key in seen:
            raise ValueError(f"Duplicate DOI: {doi}")
        seen.add(doi_key)
        sections[section].append({"order": order, "title": paper["title"].strip(),
                                  "journal": paper["journal"].strip(), "doi": doi})
    for name, items in sections.items():
        orders = [p["order"] for p in items]
        if len(orders) != len(set(orders)):
            raise ValueError(f"Duplicate order within {name}")
        items.sort(key=lambda p: p["order"])
    if not any(sections.values()):
        raise ValueError("No papers to render")
    return sections["main_papers"], sections["short_news"]


def paper_card(p: dict) -> str:
    doi_url = "https://doi.org/" + quote(p["doi"], safe="/-._;():")
    return (f'<article class="paper-card">\n'
            f'  <h3>{esc(p["title"])}</h3>\n'
            f'  <p class="journal">{esc(p["journal"])}</p>\n'
            f'  <p><a href="{esc(doi_url)}">{esc(doi_url)}</a></p>\n'
            f'</article>')


def render_section(heading: str, papers: list[dict]) -> str:
    if not papers:
        return ""
    return (f'<section class="paper-list">\n'
            f'  <h2>{esc(heading)}</h2>\n'
            + "\n".join(paper_card(p) for p in papers)
            + '\n</section>')


def build_topics(main: list[dict], short: list[dict]) -> str:
    # The top summary mirrors the page content, without duplicating a section heading.
    parts = []
    for label, papers in (("Deep Dive", main), ("ShortNews", short)):
        if papers:
            items = "".join(f'<li>{esc(p["title"])}</li>' for p in papers)
            parts.append(f'<h2>{esc(label)}</h2><ol>{items}</ol>')
    return "\n".join(parts)


def build_audio(episode_date: str, filename: str) -> str:
    if Path(filename).name != filename or filename in ("", ".", ".."):
        raise ValueError("--audio must be a filename, not a path")
    ext = Path(filename).suffix.lower()
    mime = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".mp4": "audio/mp4"}.get(ext)
    if mime is None:
        raise ValueError("--audio must end in .mp3, .m4a or .mp4")
    return (f'<audio id="podcast-player" data-episode="{esc(episode_date)}" '
            f'controls preload="metadata">\n'
            f'  <source src="{esc(filename)}" type="{mime}">\n'
            f'</audio>')


def build_html(template: str, episode_date: str, main: list[dict],
               short: list[dict], audio: str) -> str:
    for token in REQUIRED_PLACEHOLDERS:
        if token not in template:
            raise ValueError(f"Template missing placeholder: {token}")
    # TOPICS is the concise list; CONTENT contains the linked paper cards.
    content = "\n".join(filter(None, [render_section("Deep Dive", main),
                                         render_section("ShortNews", short)]))
    values = {
        "{{DATE}}": esc(episode_date),
        "{{AUDIO}}": build_audio(episode_date, audio),
        "{{TOPICS}}": build_topics(main, short),
        "{{CONTENT}}": content,
        "{{CURATION_NOTE}}": '<p><a href="curation.html">📝 How this episode was curated</a></p>',
        "{{EDITORIAL_NOTE}}": (
            '<p><a href="../../editorial_notes/'
            f'editorial_meeting_notes_{esc(episode_date)}.html">'
            '📝 Read the Editorial Note of this episode</a></p>'
        ),
    }
    for token, value in values.items():
        template = template.replace(token, value)
    return template


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("date", help="Episode date, YYYY-MM-DD")
    parser.add_argument("--audio", default="audio.mp3", help="Audio filename (default: audio.mp3)")
    parser.add_argument("--json", type=Path, help="Selection JSON path (overrides default)")
    parser.add_argument("--template", type=Path, default=TEMPLATE_PATH,
                        help="HTML template path")
    parser.add_argument("--output", type=Path, help="Output HTML path (overrides default)")
    args = parser.parse_args()
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
            raise ValueError("date must be YYYY-MM-DD")
        Date.fromisoformat(args.date)
        source = args.json or (REPO_ROOT / "work" / args.date /
                                 f"editorial_selection_{args.date}.json")
        target = args.output or (REPO_ROOT / "docs" / "episodes" / args.date / "index.html")
        data = load_selection(source, args.date)
        main_papers, short_news = extract_papers(data)
        template = args.template.read_text(encoding="utf-8")
        rendered = build_html(template, args.date, main_papers, short_news, args.audio)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    print(f"Input : {source}")
    print(f"Output: {target}")
    print(f"Papers: Deep Dive {len(main_papers)}, ShortNews {len(short_news)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
