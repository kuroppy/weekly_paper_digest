#!/usr/bin/env python3
"""Build the public WPD Paper Review HTML.

Reader-facing design:
- the index shows only paper number, title, journal/date, and a one-line comment
- clicking a paper opens a modal with the structured review
- Abstract text is not embedded in the public HTML
- no scores, Human Curation, editor comments, composition tools, or machine scores

Usage:
    python build_public_review.py \
        --papers papers_2026-09-07.json \
        --reviews papers_2026-09-07_independent_review_ja.json \
        --template wpd_public_review_template.html \
        --episode 2026-09-07 \
        --output wpd_review_2026-09-07.html
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def validate_review(review: dict) -> None:
    if not review.get("source_id"):
        raise ValueError("Review is missing source_id")

    chappy = review.get("chappy_review")
    summary = review.get("summary")
    if not isinstance(chappy, dict) or not isinstance(summary, dict):
        raise ValueError(f"{review.get('source_id')}: missing chappy_review or summary")

    comment = chappy.get("comment")
    if not isinstance(comment, str) or not comment.strip():
        raise ValueError(f"{review['source_id']}: chappy_review.comment is required")

    for key in ("what_they_did", "main_findings", "novelty_claim", "methods_data", "caveats"):
        if not isinstance(summary.get(key), str):
            raise ValueError(f"{review['source_id']}: summary.{key} must be a string")


def journal_date(paper: dict) -> str:
    return " · ".join(esc(x) for x in (paper.get("journal", ""), paper.get("pub_date", "")) if x)


def original_link(paper: dict) -> str:
    url = str(paper.get("url") or "").strip()
    if not url and paper.get("doi"):
        url = f"https://doi.org/{paper['doi']}"
    if not url:
        return ""
    return f'<a class="original-link" href="{esc(url)}" target="_blank" rel="noopener">Original paper ↗</a>'


def render_index_item(index: int, paper: dict, review: dict) -> str:
    c = review["chappy_review"]
    s = review["summary"]
    modal_id = f"paper-modal-{index}"

    # Search can use the hidden review text too, while the visible index stays compact.
    search_text = " ".join(
        str(x or "")
        for x in (
            paper.get("title"),
            paper.get("journal"),
            c.get("comment"),
            s.get("what_they_did"),
            s.get("main_findings"),
            s.get("novelty_claim"),
            s.get("methods_data"),
            s.get("caveats"),
        )
    ).lower()

    return f"""
<article class="paper" data-search="{esc(search_text)}" data-modal-id="{modal_id}" tabindex="0" role="button" aria-haspopup="dialog" aria-controls="{modal_id}">
  <div class="paper-num">{index:02d}</div>
  <div class="paper-main">
    <h2 class="paper-title">{esc(paper.get('title', ''))}</h2>
    <div class="paper-meta">{journal_date(paper)}</div>
    <p class="one-line">{esc(c['comment'])}</p>
  </div>
  <div class="paper-open" aria-hidden="true">＋</div>
</article>"""


def render_modal(index: int, paper: dict, review: dict) -> str:
    s = review["summary"]
    modal_id = f"paper-modal-{index}"
    caveat = str(s.get("caveats") or "").strip()
    caveat_html = (
        f'<div class="detail-row caution"><div class="detail-label">注意点</div><div>{esc(caveat)}</div></div>'
        if caveat else ""
    )

    doi_html = ""
    if paper.get("doi"):
        doi_html = f'<span class="doi">DOI: {esc(paper["doi"])}</span>'

    return f"""
<div class="modal" id="{modal_id}" hidden>
  <div class="modal-backdrop" data-close-modal></div>
  <section class="modal-panel" role="dialog" aria-modal="true" aria-labelledby="{modal_id}-title">
    <button class="modal-close" type="button" data-close-modal aria-label="閉じる">×</button>
    <div class="modal-number">{index:02d}</div>
    <h2 class="modal-title" id="{modal_id}-title">{esc(paper.get('title', ''))}</h2>
    <div class="modal-meta">{journal_date(paper)}</div>

    <div class="detail-list">
      <div class="detail-row"><div class="detail-label">やったこと</div><div>{esc(s['what_they_did'])}</div></div>
      <div class="detail-row"><div class="detail-label">主な結果</div><div>{esc(s['main_findings'])}</div></div>
      <div class="detail-row"><div class="detail-label">新規性</div><div>{esc(s['novelty_claim'])}</div></div>
      <div class="detail-row"><div class="detail-label">方法・データ</div><div>{esc(s['methods_data'])}</div></div>
      {caveat_html}
    </div>

    <div class="modal-footer">
      {original_link(paper)}
      {doi_html}
    </div>
  </section>
</div>"""


def fill_template(
    template: str,
    *,
    episode: str,
    items: list[str],
    modals: list[str],
    count: int,
) -> str:
    display_date = episode.replace("-", ".")
    title = f"Paper Review — {display_date}"
    subtitle = f"This week in Genome Microbiology · {count} papers"

    intro = f"""
<section class="intro-card">
  <p>今週収集した{count}報を、ひとことずつ眺められる形にまとめています。気になった論文を選ぶと、要点をもう少し詳しく読めます。</p>
  <p class="disclaimer">要約・整理には生成AIを使用しており、主に論文Abstractに基づいています。内容には誤りや過度な単純化が含まれる可能性があります。詳細は原論文をご確認ください。</p>
</section>
"""

    script = r"""
<script>
const search = document.getElementById('search');
const count = document.getElementById('visibleCount');
const papers = [...document.querySelectorAll('.paper')];
const modals = [...document.querySelectorAll('.modal')];
let lastTrigger = null;

function applySearch(){
  const q = search.value.toLowerCase().trim();
  let visible = 0;
  papers.forEach(p => {
    const show = !q || p.dataset.search.includes(q);
    p.classList.toggle('hidden', !show);
    if(show) visible += 1;
  });
  count.textContent = `${visible} / ${papers.length}`;
}

function openModal(trigger){
  const modal = document.getElementById(trigger.dataset.modalId);
  if(!modal) return;
  lastTrigger = trigger;
  modal.hidden = false;
  document.body.classList.add('modal-open');
  const close = modal.querySelector('.modal-close');
  if(close) close.focus();
}

function closeModal(modal){
  if(!modal || modal.hidden) return;
  modal.hidden = true;
  document.body.classList.remove('modal-open');
  if(lastTrigger){
    lastTrigger.focus();
    lastTrigger = null;
  }
}

papers.forEach(p => {
  p.addEventListener('click', () => openModal(p));
  p.addEventListener('keydown', e => {
    if(e.key === 'Enter' || e.key === ' '){
      e.preventDefault();
      openModal(p);
    }
  });
});

modals.forEach(modal => {
  modal.querySelectorAll('[data-close-modal]').forEach(el => {
    el.addEventListener('click', () => closeModal(modal));
  });
});

document.addEventListener('keydown', e => {
  if(e.key === 'Escape'){
    const open = modals.find(m => !m.hidden);
    if(open) closeModal(open);
  }
});

search.addEventListener('input', applySearch);
applySearch();
</script>
"""

    return (
        template
        .replace("%%PAGE_TITLE%%", esc(title))
        .replace("%%HEADER_TITLE%%", esc(title))
        .replace("%%SUBTITLE%%", esc(subtitle))
        .replace("%%INTRO%%", intro)
        .replace("%%PAPER_ITEMS%%", "\n".join(items))
        .replace("%%MODALS%%", "\n".join(modals))
        .replace("%%SCRIPT%%", script)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build public WPD Paper Review HTML")
    parser.add_argument("--papers", required=True, type=Path)
    parser.add_argument("--reviews", required=True, type=Path)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--episode", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    papers = load_json(args.papers)
    review_data = load_json(args.reviews)
    template = args.template.read_text(encoding="utf-8")

    if not isinstance(papers, list):
        raise ValueError("papers JSON must be a top-level list")

    reviews = review_data.get("papers") if isinstance(review_data, dict) else None
    if not isinstance(reviews, list):
        raise ValueError("review JSON must contain a top-level 'papers' list")

    review_by_id: dict[str, dict] = {}
    for review in reviews:
        validate_review(review)
        sid = str(review["source_id"])
        if sid in review_by_id:
            raise ValueError(f"Duplicate review source_id: {sid}")
        review_by_id[sid] = review

    paper_ids = [str(p.get("source_id", "")) for p in papers]
    missing = [sid for sid in paper_ids if sid not in review_by_id]
    extra = sorted(set(review_by_id) - set(paper_ids))
    if missing:
        raise ValueError(f"Reviews missing for source_id(s): {', '.join(missing)}")
    if extra:
        raise ValueError(f"Review JSON contains unknown source_id(s): {', '.join(extra)}")

    items: list[str] = []
    modals: list[str] = []
    for i, paper in enumerate(papers, 1):
        review = review_by_id[str(paper.get("source_id", ""))]
        items.append(render_index_item(i, paper, review))
        modals.append(render_modal(i, paper, review))

    html_text = fill_template(
        template,
        episode=args.episode,
        items=items,
        modals=modals,
        count=len(items),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html_text, encoding="utf-8")
    print(f"Built public review: {args.output}")


if __name__ == "__main__":
    main()
