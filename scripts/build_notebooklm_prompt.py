#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate a NotebookLM audio prompt from editorial_selection JSON and a Markdown template.

Requires only the Python standard library.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from string import Template


def load_items(path: Path) -> tuple[list[dict], list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    papers = data.get("papers")
    if not isinstance(papers, list):
        raise ValueError("JSON must contain a 'papers' list")

    sections = {"short_news": [], "deep_dive": []}
    for index, item in enumerate(papers):
        placement = item.get("placement", item.get("section"))
        if placement not in sections:
            continue
        title = (item.get("paper") or {}).get("title", "").strip()
        if not title:
            raise ValueError(f"papers[{index}] has no title")
        order = item.get("order")
        if not isinstance(order, int) or isinstance(order, bool):
            raise ValueError(f"papers[{index}] has no valid integer order")
        sections[placement].append(item)

    for placement in sections:
        orders = [x["order"] for x in sections[placement]]
        if len(orders) != len(set(orders)):
            raise ValueError(f"Duplicate order in {placement}")
        sections[placement].sort(key=lambda x: x["order"])

    return sections["short_news"], sections["deep_dive"]


def format_list(items: list[dict], prefix: str, include_journal: bool) -> str:
    lines = []
    for number, item in enumerate(items, 1):
        paper = item["paper"]
        title = paper["title"].strip()
        journal = (paper.get("journal") or "").strip()
        suffix = f" ({journal})" if include_journal and journal else ""
        lines.append(f"- {prefix}{number}: {title}{suffix}")
    return "\n".join(lines) if lines else "（該当論文なし）"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a NotebookLM prompt.")
    parser.add_argument("--editorial", type=Path, required=True,
                        help="editorial_selection_YYYY-MM-DD.json")
    parser.add_argument("--template", type=Path,
                        default=Path(__file__).with_name("notebooklm_prompt_template.md"))
    parser.add_argument("--digest", default="weekly_digest.md",
                        help="Filename of the Markdown uploaded to NotebookLM")
    parser.add_argument("--output", type=Path, default=Path("notebooklm_prompt.md"))
    args = parser.parse_args()

    short, deep = load_items(args.editorial)
    template = Template(args.template.read_text(encoding="utf-8"))
    result = template.substitute(
        DIGEST_FILENAME=Path(args.digest).name,
        SHORT_NEWS_LIST=format_list(short, "ShortNews", include_journal=False),
        DEEP_DIVE_LIST=format_list(deep, "DeepDive", include_journal=True),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result.rstrip() + "\n", encoding="utf-8")
    print(f"Wrote {args.output} ({len(short)} ShortNews, {len(deep)} DeepDive)")


if __name__ == "__main__":
    main()
