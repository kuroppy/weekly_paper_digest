#!/usr/bin/env python3
"""
Build two WPD HTML files from the same paper/review inputs:

1) Public review HTML
   - Chappy review, scores, structured summary, Abstract/source metadata
   - no Human selection controls
   - no editor comments
   - no Editorial Composition workspace

2) Editorial workspace HTML
   - everything in the review
   - Human Curation controls + editor comments
   - Editorial Composition view
   - exports human_curation_YYYY-MM-DD.json
   - exports editorial_selection_YYYY-MM-DD.json

Usage:
    python build_curation_review.py \
        --papers papers_2026-09-07.json \
        --reviews llm_review_2026-09-07.json \
        --template wpd_curation_template.html \
        --episode 2026-09-07 \
        --public-output wpd_review_2026-09-07.html \
        --editor-output wpd_curation_2026-09-07.html

Optional: preload an existing Human Curation JSON:
    --human human_curation_2026-09-07.json
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


CONF_JA = {"low": "低", "medium": "中", "high": "高"}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def stars(score: int) -> str:
    return "★" * score + "☆" * (5 - score)


def validate_score_block(name: str, block: dict) -> None:
    score = block.get("score")
    confidence = block.get("confidence")
    reason = block.get("reason")
    if not isinstance(score, int) or not 1 <= score <= 5:
        raise ValueError(f"{name}.score must be an integer from 1 to 5: {score!r}")
    if confidence not in CONF_JA:
        raise ValueError(f"{name}.confidence must be one of {list(CONF_JA)}: {confidence!r}")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError(f"{name}.reason must be a non-empty string")


def validate_review(review: dict) -> None:
    if not review.get("source_id"):
        raise ValueError("Review is missing source_id")

    chappy = review.get("chappy_review")
    summary = review.get("summary")
    if not isinstance(chappy, dict) or not isinstance(summary, dict):
        raise ValueError(f"{review.get('source_id')}: missing chappy_review or summary")

    if not isinstance(chappy.get("comment"), str) or not chappy["comment"].strip():
        raise ValueError(f"{review['source_id']}: chappy_review.comment is required")

    for key in ("novelty", "general_interest", "evidence"):
        if key not in chappy:
            raise ValueError(f"{review['source_id']}: missing chappy_review.{key}")
        validate_score_block(f"{review['source_id']}.{key}", chappy[key])

    for key in ("what_they_did", "main_findings", "novelty_claim", "methods_data", "caveats"):
        if not isinstance(summary.get(key), str):
            raise ValueError(f"{review['source_id']}: summary.{key} must be a string")


def human_index(human_data: dict | None) -> dict[str, dict]:
    if not human_data:
        return {}
    return {
        str(row["source_id"]): row
        for row in human_data.get("human_review", [])
        if row.get("source_id") is not None
    }


def editorial_state(editorial_data: dict | None, humans: dict[str, dict]) -> dict:
    """Build initial composition; accept legacy Main data as Deep Dive."""
    if editorial_data:
        ctx = editorial_data.get("editorial_context") or {}
        deep, short = [], []
        for row in editorial_data.get("papers", []):
            sid = str(row.get("source_id", ""))
            if not sid:
                continue
            placement = "short_news" if row.get("section") == "short_news" or row.get("placement") == "short_news" else "deep_dive"
            item = {"source_id": sid, "placement": placement,
                    "composition_note": row.get("composition_note", row.get("human_comment", ""))}
            target = short if placement == "short_news" else deep
            target.append((int(row.get("order", 10**9)), item))
        return {"editorial_note": ctx.get("editorial_note", ""),
                "main": [x[1] for x in sorted(deep, key=lambda x: x[0])],
                "short": [x[1] for x in sorted(short, key=lambda x: x[0])]}

    deep, short = [], []
    for sid, h in humans.items():
        if h.get("deep_dive") or h.get("main"):
            deep.append({"source_id": sid, "placement": "deep_dive", "composition_note": h.get("comment", "")})
        elif h.get("short_news"):
            short.append({"source_id": sid, "placement": "short_news", "composition_note": h.get("comment", "")})
    return {"editorial_note": "", "main": deep, "short": short}


def checkbox(css_class: str, label: str, checked: bool) -> str:
    checked_attr = " checked" if checked else ""
    return (
        f'<label class="choice">'
        f'<input class="sel {css_class}" type="checkbox"{checked_attr}> {esc(label)}'
        f"</label>"
    )


def score_row(label: str, block: dict) -> str:
    score = int(block["score"])
    conf = CONF_JA[block["confidence"]]
    return f"""
<div class="score-row">
  <div class="score-name">{esc(label)}</div>
  <div class="stars score-{score}">{stars(score)} <span class="score-num">{score}/5</span></div>
  <div><span class="confidence">確信度: {conf}</span></div>
  <div class="score-reason">{esc(block["reason"])}</div>
</div>"""


def source_and_title(paper: dict) -> tuple[str, str, str, str]:
    source_meta = []
    if paper.get("doi"):
        source_meta.append(f"<b>DOI:</b> {esc(paper['doi'])}")
    if paper.get("source"):
        source_meta.append(f"<b>Source:</b> {esc(paper['source'])}")
    if paper.get("score") is not None:
        machine = f"<b>Machine score:</b> {esc(paper['score'])}"
        if paper.get("score_reason"):
            machine += f" ({esc(paper['score_reason'])})"
        source_meta.append(machine)

    meta_bits = [paper.get("journal", ""), paper.get("pub_date", "")]
    meta = " · ".join(esc(x) for x in meta_bits if x)
    if paper.get("score") is not None:
        meta += f" · score {esc(paper['score'])}"

    title = esc(paper.get("title", ""))
    url = esc(paper.get("url", ""))
    title_html = (
        f'<a href="{url}" target="_blank" rel="noopener">{title}</a>'
        if url else title
    )
    search_text = (
        f"{paper.get('title','')} {paper.get('journal','')} {paper.get('authors','')}"
    ).lower()
    return title_html, meta, " &nbsp; ".join(source_meta), search_text


def core_card(index: int, paper: dict, review: dict) -> str:
    c = review["chappy_review"]
    s = review["summary"]
    title_html, meta, source_meta, search_text = source_and_title(paper)
    authors = str(paper.get("authors") or review.get("authors") or "").strip()
    authors_html = f'<div class="authors">{esc(authors)}</div>' if authors else ""

    return f"""
  <div class="paper-head">
    <div class="paper-num">{index}</div>
    <div>
      <div class="paper-title">{title_html}</div>
      {authors_html}
      <div class="meta">{meta}</div>
    </div>
  </div>

  <div class="chappy">
    <span class="field-label">Chappy評価</span>
    <span>{esc(c['comment'])}</span>
  </div>

  <div class="chappy-scores">
    {score_row("Novelty", c["novelty"])}
    {score_row("General Interest", c["general_interest"])}
    {score_row("Evidence", c["evidence"])}
  </div>

  <div class="summary-grid">
    <div class="summary-row"><span class="field-label">やったこと</span><span>{esc(s["what_they_did"])}</span></div>
    <div class="summary-row"><span class="field-label">主な結果</span><span>{esc(s["main_findings"])}</span></div>
    <div class="summary-row"><span class="field-label">新規性</span><span>{esc(s["novelty_claim"])}</span></div>
    <div class="summary-row"><span class="field-label">方法・データ</span><span>{esc(s["methods_data"])}</span></div>
    <div class="summary-row caution"><span class="field-label">注意点</span><span>{esc(s["caveats"])}</span></div>
  </div>

  <details>
    <summary>Abstract / source metadata</summary>
    <div class="abstract">{esc(paper.get("abstract", ""))}</div>
    <div class="source-meta">{source_meta}</div>
  </details>
"""


def render_public_card(index: int, paper: dict, review: dict) -> str:
    _, _, _, search_text = source_and_title(paper)
    return f"""
<article class="paper" data-index="{index}" data-search="{esc(search_text)}">
{core_card(index, paper, review)}
</article>"""


def render_editor_card(index: int, paper: dict, review: dict, human: dict | None) -> str:
    human = human or {
        "consider": True,
        "deep_dive": False,
        "short_news": False,
        "pass": False,
        "comment": "",
    }
    _, _, _, search_text = source_and_title(paper)
    return f"""
<article class="paper" data-index="{index}" data-search="{esc(search_text)}">
{core_card(index, paper, review)}
  <div class="human" data-id="{esc(paper["source_id"])}">
    <div class="decision-row">
      <span class="decision-label">Human selection</span>
      {checkbox("consider-sel", "検討", bool(human.get("consider", False)))}
      {checkbox("deep-sel", "Deep Dive", bool(human.get("deep_dive", False) or human.get("main", False)))}
      {checkbox("short-sel", "Short News", bool(human.get("short_news", False)))}
      {checkbox("pass-sel", "Pass", bool(human.get("pass", False)))}
    </div>
    <label class="comment-label">
      Editor comment
      <textarea class="comment" rows="2"
        placeholder="この論文を紹介したい／見送りたい理由、気になった点、本文で確認したい点など">{esc(human.get("comment", ""))}</textarea>
    </label>
  </div>
</article>"""


PUBLIC_INTRO = """
<section class="rubric-box">
<strong>Chappy 5段階評価</strong><br>
3 = 標準的に十分な水準、4 = 明確に高い、5 = 例外的に高い。1〜2も積極的に使います。<br>
Novelty = 既存研究に対する問い・発見・方法・概念の新しさ／
General Interest = 専門外の微生物研究者にも問い・発見・方法の意味を持ち出せるか／
Evidence = 主張を研究設計とデータがどの程度直接支えているか。<br>
<strong>点数の合計や掲載可否の自動判定には使いません。</strong>
</section>

<section class="note">
<b>このレビューについて：</b>
各論文をできるだけ単独で読み、今週の他論文との比較や番組全体のバランス、テーマは評価に含めていません。
</section>
"""


EDITOR_INTRO = """
<section class="rubric-box">
<strong>Chappy 5段階評価</strong><br>
3 = 標準的に十分な水準、4 = 明確に高い、5 = 例外的に高い。1〜2も積極的に使います。<br>
Novelty = 既存研究に対する問い・発見・方法・概念の新しさ／
General Interest = 専門外の微生物研究者にも問い・発見・方法の意味を持ち出せるか／
Evidence = 主張を研究設計とデータがどの程度直接支えているか。<br>
<strong>点数の合計やDeep Dive/Passの自動判定には使いません。</strong>
</section>

<section class="note">
<b>この段階の方針：</b>
各論文をできるだけ単独で評価します。今週の他論文との比較、番組全体のバランス、テーマや「まとまり」はここでは考えません。
<div class="counts">
<span>① 論文単体を読む</span>
<span>② Human selection</span>
<span>③ Editorial Composition</span>
</div>
</section>
"""


COMPOSITION_HTML = """
<section id="compositionView" class="composition-view hidden">
  <div class="composition-topbar">
    <div>
      <h2>Editorial Composition</h2>
      <p>Human Curationで選んだ論文だけを並べ、番組の順序と編集メモを確定します。</p>
    </div>
    <div class="composition-actions">
      <button id="backToCuration">← Curationに戻る</button>
      <button id="refreshComposition">選択を反映</button>
      <button id="exportEditorial" class="primary-action">Editorial Selection JSON</button>
    </div>
  </div>

  <section class="editorial-context">
    <label>
      <span>Editorial note</span>
      <textarea id="editorialNote" rows="4" placeholder="論文群を並べて見えた景色、接続の考え方、無理に回収しない点など"></textarea>
    </label>
  </section>

  <div class="composition-grid">
    <section class="composition-section">
      <div class="section-head">
        <h3>Deep Dive</h3>
        <span id="mainCount" class="section-count"></span>
      </div>
      <p class="section-help">↑↓でDeep Diveの紹介順を決めます。</p>
      <div id="mainCompositionList" class="composition-list"></div>
    </section>

    <section class="composition-section">
      <div class="section-head">
        <h3>Short News</h3>
        <span id="shortCount" class="section-count"></span>
      </div>
      <p class="section-help">Short News内での紹介順を決めます。</p>
      <div id="shortCompositionList" class="composition-list"></div>
    </section>
  </div>

  <section class="export-preview">
    <div class="section-head">
      <h3>出力内容</h3>
      <span class="section-count">Program Plot Promptへの入力用</span>
    </div>
    <p>JSONには順序・placement・編集メモに加え、選出論文のAbstractとIndependent Reviewも含めます。</p>
  </section>
</section>
"""


PUBLIC_SCRIPT = r"""
<script>
function apply(){
  const q=document.getElementById('search').value.toLowerCase().trim();
  document.querySelectorAll('.paper').forEach(p=>{
    const ok=!q || p.dataset.search.toLowerCase().includes(q);
    p.classList.toggle('hidden',!ok);
  });
}
document.getElementById('search').addEventListener('input',apply);
</script>
"""



def make_paper_data(papers: list[dict], review_by_id: dict[str, dict]) -> dict[str, dict]:
    data = {}
    for paper in papers:
        sid = str(paper.get("source_id", ""))
        review = review_by_id[sid]
        data[sid] = {
            "source_id": sid,
            "title": paper.get("title", ""),
            "journal": paper.get("journal", ""),
            "pub_date": paper.get("pub_date", ""),
            "doi": paper.get("doi", ""),
            "url": paper.get("url", ""),
            "authors": paper.get("authors", ""),
            "abstract": paper.get("abstract", ""),
            "independent_review": {
                "comment": review["chappy_review"]["comment"],
                "scores": {
                    "novelty": review["chappy_review"]["novelty"],
                    "general_interest": review["chappy_review"]["general_interest"],
                    "evidence": review["chappy_review"]["evidence"],
                },
                "summary": review["summary"],
            },
        }
    return data



EDITOR_SCRIPT_V2 = r"""
<script>
const EPISODE = %%EPISODE_JSON%%;
const KEY = %%STORAGE_KEY_JSON%%;
const COMPOSITION_KEY = KEY + '-composition';
const PAPER_DATA = %%PAPER_DATA_JSON%%;
const PUBLISHED_COMPOSITION = %%PUBLISHED_COMPOSITION_JSON%%;
const EDIT_MODE = new URLSearchParams(location.search).get('edit') === '1';
const saveState = document.getElementById('saveState');
function stateFor(h){
  return {consider:h.querySelector('.consider-sel').checked,
    deep_dive:h.querySelector('.deep-sel').checked,
    short_news:h.querySelector('.short-sel').checked,
    pass:h.querySelector('.pass-sel').checked,
    comment:h.querySelector('.comment').value};
}
function save(){
  if(!EDIT_MODE)return;
  const data={};
  document.querySelectorAll('.human').forEach(h=>data[h.dataset.id]=stateFor(h));
  localStorage.setItem(KEY,JSON.stringify(data));
  if(saveState){saveState.textContent='保存済み';setTimeout(()=>saveState.textContent='自動保存',800);}
}
function normalize(h,changed){
  const boxes=[...h.querySelectorAll('input.sel')];
  if(changed.checked)boxes.forEach(x=>{if(x!==changed)x.checked=false;});
  if(!boxes.some(x=>x.checked))h.querySelector('.consider-sel').checked=true;
}
function applyLocalHumanState(){
  if(!EDIT_MODE)return;
  let saved={};try{saved=JSON.parse(localStorage.getItem(KEY)||'{}');}catch(e){}
  document.querySelectorAll('.human').forEach(h=>{
    const x=saved[h.dataset.id];if(!x)return;
    h.querySelector('.consider-sel').checked=!!x.consider;
    h.querySelector('.deep-sel').checked=!!(x.deep_dive||x.main);
    h.querySelector('.short-sel').checked=!!x.short_news;
    h.querySelector('.pass-sel').checked=!!x.pass;
    if(x.comment!==undefined)h.querySelector('.comment').value=x.comment;
  });
}
applyLocalHumanState();
document.querySelectorAll('.human').forEach(h=>{
  h.querySelectorAll('input.sel').forEach(el=>{
    el.disabled=!EDIT_MODE;
    if(EDIT_MODE)el.addEventListener('change',()=>{normalize(h,el);save();});
  });
  const t=h.querySelector('.comment');t.readOnly=!EDIT_MODE;
  if(EDIT_MODE)t.addEventListener('input',save);
});
function apply(){
  const q=document.getElementById('search').value.toLowerCase().trim();
  document.querySelectorAll('.paper').forEach(p=>p.classList.toggle('hidden',!!q&&!p.dataset.search.toLowerCase().includes(q)));
}
document.getElementById('search').addEventListener('input',apply);
function downloadJson(filename,payload){
  const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json'});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=filename;a.click();URL.revokeObjectURL(a.href);
}
document.getElementById('export').addEventListener('click',()=>{
  const reviews=[...document.querySelectorAll('.human')].map(h=>({source_id:h.dataset.id,...stateFor(h)}));
  downloadJson(`human_curation_${EPISODE}.json`,{episode:EPISODE,stage:'human_curation',human_review:reviews});
});
function selectedFromHuman(){
  const main=[],short=[];
  document.querySelectorAll('.human').forEach(h=>{
    const st=stateFor(h),sid=h.dataset.id;
    const row={source_id:sid,placement:st.deep_dive?'deep_dive':'short_news',composition_note:st.comment};
    if(st.deep_dive)main.push(row);
    else if(st.short_news)short.push(row);
  });
  return {main,short};
}
function defaultComposition(){return JSON.parse(JSON.stringify(PUBLISHED_COMPOSITION||{editorial_note:'',main:[],short:[]}));}
function loadComposition(){
  const base=defaultComposition();if(!EDIT_MODE)return base;
  const raw=localStorage.getItem(COMPOSITION_KEY);
  if(raw){try{return {...base,...JSON.parse(raw)};}catch(e){}}
  return base;
}
let composition=loadComposition();
function reconcileComposition(){
  if(!EDIT_MODE)return;
  const selected=selectedFromHuman();
  const reconcile=(oldRows,newRows)=>{
    const oldMap=Object.fromEntries((oldRows||[]).map(x=>[x.source_id,x]));
    return newRows.map(n=>oldMap[n.source_id]
      ? {...n,...oldMap[n.source_id],placement:n.placement} : n);
  };
  composition.main=reconcile(composition.main,selected.main);
  composition.short=reconcile(composition.short,selected.short);
  saveComposition();
}
function saveComposition(){
  if(!EDIT_MODE)return;
  composition.editorial_note=document.getElementById('editorialNote').value;
  localStorage.setItem(COMPOSITION_KEY,JSON.stringify(composition));
}
function moveRow(section,index,delta){
  if(!EDIT_MODE)return;
  const rows=composition[section],j=index+delta;
  if(j<0||j>=rows.length)return;
  [rows[index],rows[j]]=[rows[j],rows[index]];saveComposition();renderComposition();
}
function escJS(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function cardHtml(row,index,section){
  const p=PAPER_DATA[row.source_id]||{title:row.source_id,journal:''};
  const placement=section==='main'?'Deep Dive':'Short News';
  const orderButtons=EDIT_MODE?`<div class="order-buttons">
    <button type="button" data-move="-1" data-index="${index}" title="上へ">↑</button>
    <button type="button" data-move="1" data-index="${index}" title="下へ">↓</button></div>`
    :`<div class="published-order">${index+1}</div>`;
  const note=row.composition_note||'';
  const noteHtml=EDIT_MODE?`<textarea class="composition-note" data-index="${index}"
    placeholder="Editor commentを引き継ぎます。構成メモを追記できます。">${escJS(note)}</textarea>`
    :(note?`<div class="composition-note-read"><span>Editorial note</span>${escJS(note)}</div>`:'');
  return `<div class="composition-card">${orderButtons}<div>
    <div class="composition-title">${escJS(p.title)}</div>
    <div class="composition-meta">${escJS(p.journal)}${p.pub_date?' · '+escJS(p.pub_date):''}</div>
    <div class="composition-controls"><span class="badge">${placement}</span></div>${noteHtml}</div></div>`;
}
function bindList(listId,section){
  if(!EDIT_MODE)return;
  const el=document.getElementById(listId);
  el.querySelectorAll('[data-move]').forEach(btn=>btn.addEventListener('click',()=>moveRow(section,Number(btn.dataset.index),Number(btn.dataset.move))));
  el.querySelectorAll('.composition-note').forEach(t=>t.addEventListener('input',()=>{
    composition[section][Number(t.dataset.index)].composition_note=t.value;saveComposition();
  }));
}
function renderComposition(){
  const mainEl=document.getElementById('mainCompositionList');
  const shortEl=document.getElementById('shortCompositionList');
  mainEl.innerHTML=composition.main.length?composition.main.map((r,i)=>cardHtml(r,i,'main')).join('')
    :'<div class="empty-composition">Deep Dive はまだ選択されていません。</div>';
  shortEl.innerHTML=composition.short.length?composition.short.map((r,i)=>cardHtml(r,i,'short')).join('')
    :'<div class="empty-composition">Short News はまだ選択されていません。</div>';
  document.getElementById('mainCount').textContent=`${composition.main.length}本`;
  document.getElementById('shortCount').textContent=`${composition.short.length}本`;
  bindList('mainCompositionList','main');bindList('shortCompositionList','short');
}
const editorialNote=document.getElementById('editorialNote');
editorialNote.readOnly=!EDIT_MODE;
if(EDIT_MODE)editorialNote.addEventListener('input',saveComposition);
function openComposition(){
  if(EDIT_MODE)reconcileComposition();
  document.getElementById('curationView').classList.add('hidden');
  document.getElementById('compositionView').classList.remove('hidden');
  editorialNote.value=composition.editorial_note||'';
  renderComposition();setStageUI('composition');window.scrollTo(0,0);
}
function openReview(){
  if(EDIT_MODE)saveComposition();
  document.getElementById('compositionView').classList.add('hidden');
  document.getElementById('curationView').classList.remove('hidden');
  setStageUI('curation');window.scrollTo(0,0);
}
document.getElementById('openComposition').addEventListener('click',openComposition);
document.getElementById('openReview').addEventListener('click',openReview);
document.getElementById('backToCuration').addEventListener('click',openReview);
document.getElementById('refreshComposition').addEventListener('click',()=>{reconcileComposition();renderComposition();});
document.getElementById('exportEditorial').addEventListener('click',()=>{
  saveComposition();
  const pack=(rows,section)=>rows.map((row,i)=>{
    const p=PAPER_DATA[row.source_id]||{};
    const h=document.querySelector(`.human[data-id="${row.source_id}"]`);
    return {source_id:row.source_id,section,placement:row.placement,order:i+1,
      composition_note:row.composition_note||'',
      human_comment:h?h.querySelector('.comment').value:'',
      paper:{title:p.title||'',journal:p.journal||'',pub_date:p.pub_date||'',doi:p.doi||'',url:p.url||'',authors:p.authors||'',abstract:p.abstract||''},
      independent_review:p.independent_review||{}};
  });
  downloadJson(`editorial_selection_${EPISODE}.json`,{
    episode:EPISODE,stage:'editorial_composition',
    editorial_context:{editorial_note:composition.editorial_note},
    papers:[...pack(composition.main,'deep_dive'),...pack(composition.short,'short_news')]
  });
});
function setStageUI(stage){
  document.getElementById('openReview').classList.toggle('active',stage==='curation');
  document.getElementById('openComposition').classList.toggle('active',stage==='composition');
}
function configureMode(){
  document.body.classList.toggle('edit-mode',EDIT_MODE);
  document.body.classList.toggle('read-mode',!EDIT_MODE);
  document.querySelectorAll('.edit-only').forEach(el=>el.classList.toggle('hidden',!EDIT_MODE));
  document.getElementById('refreshComposition').classList.toggle('hidden',!EDIT_MODE);
  document.getElementById('exportEditorial').classList.toggle('hidden',!EDIT_MODE);
  const read=document.getElementById('readModeLink'),edit=document.getElementById('editModeLink');
  read.href=location.pathname;edit.href='?edit=1';
  read.classList.toggle('active',!EDIT_MODE);edit.classList.toggle('active',EDIT_MODE);
  setStageUI(document.getElementById('compositionView').classList.contains('hidden')?'curation':'composition');
}
document.getElementById('toolbarExportEditorial').addEventListener('click',()=>document.getElementById('exportEditorial').click());
configureMode();
</script>
"""


def fill_template(
    template: str,
    *,
    episode: str,
    cards: list[str],
    paper_data: dict[str, dict],
    published_composition: dict,
) -> str:
    title = f"WPD Editorial Record — {episode}"
    subtitle = "Independent Paper Review → Human Curation → Editorial Composition"

    toolbar = """
<div class="tool-group search-group">
  <span class="tool-label">Search</span>
  <input id="search" placeholder="タイトル / journal検索" type="search">
</div>

<div class="tool-group">
  <span class="tool-label">Stage</span>
  <div class="segmented">
    <button id="openReview" class="stage-control active" type="button">Curation</button>
    <button id="openComposition" class="stage-control" type="button">Composition</button>
  </div>
</div>

<div class="tool-group">
  <span class="tool-label">Mode</span>
  <div class="segmented">
    <a id="readModeLink" class="mode-control" href="">Read</a>
    <a id="editModeLink" class="mode-control" href="?edit=1">Edit</a>
  </div>
</div>

<div class="tool-group edit-only">
  <span class="tool-label">Data</span>
  <details class="export-menu">
    <summary>Export ▾</summary>
    <div class="export-popover">
      <button id="export" type="button">Human Curation JSON</button>
      <button id="toolbarExportEditorial" type="button">Editorial Selection JSON</button>
    </div>
  </details>
</div>

<span class="save-state edit-only" id="saveState">自動保存</span>
"""

    intro = """
<section class="rubric-box">
<strong>Chappy 5段階評価</strong><br>
3 = 標準的に十分な水準、4 = 明確に高い、5 = 例外的に高い。1〜2も積極的に使います。<br>
Novelty = 既存研究に対する問い・発見・方法・概念の新しさ／
General Interest = 専門外の微生物研究者にも問い・発見・方法の意味を持ち出せるか／
Evidence = 主張を研究設計とデータがどの程度直接支えているか。<br>
<strong>点数の合計やDeep Dive/Passの自動判定には使いません。</strong>
</section>

<section class="note">
<b>Editorial Record：</b>
このページでは、論文単体のレビューだけでなく、Human Curationと、その後に行ったEditorial Compositionまで公開します。
論文選定時には他論文との比較やテーマをできるだけ持ち込まず、選定後に初めて論文同士を並べています。
<div class="counts">
<span>① Independent Paper Review</span>
<span>② Human Curation</span>
<span>③ Editorial Composition</span>
</div>
</section>
"""

    script = EDITOR_SCRIPT_V2
    script = (
        script
        .replace("%%EPISODE_JSON%%", json.dumps(episode, ensure_ascii=False))
        .replace("%%STORAGE_KEY_JSON%%", json.dumps(f"wpd-editorial-record-{episode}", ensure_ascii=False))
        .replace("%%PAPER_DATA_JSON%%", json.dumps(paper_data, ensure_ascii=False).replace("</", "<\\/"))
        .replace("%%PUBLISHED_COMPOSITION_JSON%%", json.dumps(published_composition, ensure_ascii=False).replace("</", "<\\/"))
    )

    return (
        template
        .replace("%%PAGE_TITLE%%", esc(title))
        .replace("%%HEADER_TITLE%%", esc(title))
        .replace("%%SUBTITLE%%", esc(subtitle))
        .replace("%%TOOLBAR%%", toolbar)
        .replace("%%MAIN_ID%%", ' id="curationView"')
        .replace("%%INTRO%%", intro)
        .replace("%%PAPER_CARDS%%", "\n".join(cards))
        .replace("%%EXTRA_BODY%%", COMPOSITION_HTML)
        .replace("%%SCRIPT%%", script)
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--papers", required=True, type=Path)
    parser.add_argument("--reviews", required=True, type=Path)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--episode", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--human", type=Path, default=None)
    parser.add_argument("--editorial", type=Path, default=None)
    args = parser.parse_args()

    papers = load_json(args.papers)
    review_data = load_json(args.reviews)
    human_data = load_json(args.human) if args.human else None
    editorial_data = load_json(args.editorial) if args.editorial else None
    template = args.template.read_text(encoding="utf-8")

    if not isinstance(papers, list):
        raise ValueError("papers JSON must be a top-level list")

    reviews = review_data.get("papers")
    if not isinstance(reviews, list):
        raise ValueError("llm_review JSON must contain a top-level 'papers' list")

    review_by_id: dict[str, dict] = {}
    for review in reviews:
        validate_review(review)
        sid = str(review["source_id"])
        if sid in review_by_id:
            raise ValueError(f"Duplicate review source_id: {sid}")
        review_by_id[sid] = review

    paper_ids = {str(p.get("source_id", "")) for p in papers}
    missing = [sid for sid in paper_ids if sid not in review_by_id]
    extra = sorted(set(review_by_id) - paper_ids)
    if missing:
        raise ValueError(f"Reviews missing for source_id(s): {', '.join(sorted(missing))}")
    if extra:
        raise ValueError(f"Review JSON contains unknown source_id(s): {', '.join(extra)}")

    humans = human_index(human_data)
    cards = []
    for i, paper in enumerate(papers, 1):
        sid = str(paper.get("source_id", ""))
        cards.append(render_editor_card(i, paper, review_by_id[sid], humans.get(sid)))

    paper_data = make_paper_data(papers, review_by_id)
    published_composition = editorial_state(editorial_data, humans)

    html_text = fill_template(
        template,
        episode=args.episode,
        cards=cards,
        paper_data=paper_data,
        published_composition=published_composition,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html_text, encoding="utf-8")
    print(f"Built: {args.output}")
    print("Default: Read mode")
    print(f"Edit locally: {args.output.name}?edit=1")


if __name__ == "__main__":
    main()
