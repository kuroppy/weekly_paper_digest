#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compile WPD editorial_selection JSON into weekly_digest.md.

The output deliberately follows the Markdown contract expected by build_episode.py:
  ## 今週の印象
  ## 今週の注目論文
    ### 論文N
    - **Title:** ...
    - **Journal:** ...
    - **DOI:** ...
    - **一言要約:** ...
  ## 深掘り論文
  ## 今週のショートニュース（任意）
    ### ショートニュースN
    - **Title:** ...
    - **Journal:** ...
    - **DOI:** ...
    - **一言要約:** ...
  ## まとめ

The extra fields under 注目論文 and 深掘り論文 are for NotebookLM; build_episode.py
simply ignores fields it does not use.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ALLOWED = {"deep_dive", "main", "short_news"}


def text(obj: dict[str, Any], key: str) -> str:
    v = obj.get(key, "")
    return v.strip() if isinstance(v, str) else ""


def summary(item: dict[str, Any]) -> dict[str, Any]:
    review = item.get("independent_review") or {}
    s = review.get("summary") or {}
    return s if isinstance(s, dict) else {}


def paper(item: dict[str, Any]) -> dict[str, Any]:
    p = item.get("paper") or {}
    return p if isinstance(p, dict) else {}


def one_line(item: dict[str, Any]) -> str:
    s = summary(item)
    return text(s, "main_findings") or text(s, "what_they_did") or text(paper(item), "abstract")


def field(label: str, value: str) -> str:
    return f"- **{label}:** {value}" if value else ""


def paper_block(item: dict[str, Any], n: int) -> list[str]:
    p, s = paper(item), summary(item)
    placement = item["placement"]
    lines = [f"### 論文{n}", ""]
    for label, value in [
        ("Title", text(p, "title")),
        ("Journal", text(p, "journal")),
        ("DOI", text(p, "doi") or text(p, "url")),
        ("一言要約", one_line(item)),
        ("何をしたか", text(s, "what_they_did")),
        ("新規性", text(s, "novelty_claim")),
        ("なぜ面白いか", text((item.get("independent_review") or {}), "comment")),
        ("今週の中での位置づけ", text(item, "composition_note")),
        ("紹介区分", "Deep Dive" if placement == "deep_dive" else "Main"),
        ("注意点", text(s, "caveats")),
    ]:
        x = field(label, value)
        if x:
            lines.append(x)
    lines.append("")
    return lines


def deep_dive_block(item: dict[str, Any]) -> list[str]:
    p, s = paper(item), summary(item)
    title = text(p, "title")
    lines = [f"### {title}", ""]
    note = text(item, "composition_note")
    if note:
        lines += ["#### 今週の中での位置づけ", "", note, ""]
    if text(s, "what_they_did"):
        lines += ["#### 概要", "", text(s, "what_they_did"), ""]
    if text(s, "main_findings"):
        lines += ["#### Abstractから確認できる主な結果", "", text(s, "main_findings"), ""]
    if text(s, "caveats"):
        lines += ["#### 注意点", "", text(s, "caveats"), ""]
    lines += [
        "#### Deep Diveで追うポイント", "",
        "添付PDFを一次資料として、研究者がどの問いから出発し、どの実験・解析と証拠を積み重ね、どこまで結論へ到達したかを追う。具体的な実験、数値、結果、著者の主張はPDFを優先する。",
        "",
    ]
    return lines


def short_block(item: dict[str, Any], n: int) -> list[str]:
    p, s = paper(item), summary(item)
    lines = [f"### ショートニュース{n}", ""]
    for label, value in [
        ("Title", text(p, "title")),
        ("Journal", text(p, "journal")),
        ("DOI", text(p, "doi") or text(p, "url")),
        ("一言要約", one_line(item)),
    ]:
        x = field(label, value)
        if x:
            lines.append(x)
    note = text(item, "composition_note")
    if note:
        lines.append(field("ニュースとしての位置づけ", note))
    caveat = text(s, "caveats")
    if caveat:
        lines.append(field("注意点", caveat))
    lines.append("")
    return lines


def compile_digest(data: dict[str, Any]) -> str:
    episode = text(data, "episode")
    if not episode:
        raise ValueError("episode is required")
    ctx = data.get("editorial_context") or {}
    papers = data.get("papers")
    if not isinstance(papers, list):
        raise ValueError("papers must be a list")

    items: list[dict[str, Any]] = []
    for i, item in enumerate(papers, 1):
        if not isinstance(item, dict):
            raise ValueError(f"papers[{i}] must be an object")
        if item.get("placement") not in ALLOWED:
            raise ValueError(f"papers[{i}] has invalid placement")
        if not isinstance(item.get("order"), int):
            raise ValueError(f"papers[{i}] needs integer order")
        items.append(item)

    featured = sorted(
        [x for x in items if x["placement"] in {"deep_dive", "main"}],
        key=lambda x: x["order"],
    )
    deep = sorted([x for x in items if x["placement"] == "deep_dive"], key=lambda x: x["order"])
    short = sorted([x for x in items if x["placement"] == "short_news"], key=lambda x: x["order"])

    editorial_note = text(ctx, "editorial_note")
    question = text(ctx, "emergent_question")
    closing = text(ctx, "closing_direction")

    out = ["# 今週の注目論文メモ", "", "## 今週の印象", ""]
    if editorial_note:
        out.append(editorial_note)
    if question:
        out += ["", f"今週、論文を読み終えて残った問いは、**「{question}」**。"]
    out += ["", "---", "", "## 今週の注目論文", ""]

    for n, item in enumerate(featured, 1):
        out.extend(paper_block(item, n))

    if deep:
        out += ["---", "", "## 深掘り論文", ""]
        for item in deep:
            out.extend(deep_dive_block(item))

    if short:
        out += ["---", "", "## 今週のショートニュース（任意）", ""]
        for n, item in enumerate(short, 1):
            out.extend(short_block(item, n))

    out += ["---", "", "## まとめ", ""]
    if closing:
        out.append(closing)
    elif question:
        out.append(f"今週は、**「{question}」**という問いが残る論文群だった。")
    else:
        out.append("今週の論文群を読んだからこそ残った問いや視点を、編集後記として振り返る。")

    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Compile editorial_selection JSON to weekly_digest.md")
    ap.add_argument("--editorial", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    data = json.loads(Path(args.editorial).read_text(encoding="utf-8"))
    md = compile_digest(data)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
