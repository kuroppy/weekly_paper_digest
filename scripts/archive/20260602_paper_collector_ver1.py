#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
weekly_microbe_papers.py

目的:
  週ごとに微生物・ゲノミクス関連の注目論文を収集し、
  タイトル、Abstract、ジャーナル、年月日をCSV/JSONで保存する。

取得元:
  - PubMed (NCBI E-utilities)
  - bioRxiv API

出力:
  - papers_YYYY-MM-DD.csv
  - papers_YYYY-MM-DD.json

使い方:
  python papers.py
  python papers.py --days 7 --max-pubmed 1000 --max-biorxiv-pages 5

注意:
  - 「注目論文」はルールベースの簡易スコアです。

"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

import requests


# =========================
# 設定
# =========================

EMAIL = "email@example.com"   # NCBI/OpenAlex等に礼儀として入れておくとよい
TOOL_NAME = "paper_collector"
REQUEST_TIMEOUT = 60

PUBMED_QUERY = r'''
(
  (
    microb*[Title/Abstract]
    OR bacteri*[Title/Abstract]
    OR archae*[Title/Abstract]
    OR phage[Title/Abstract]
    OR plasmid[Title/Abstract]
  )
  AND
  (
    genom*[Title/Abstract]
    OR metagenom*[Title/Abstract]
    OR DNA[Title/Abstract]
  )
)
'''

BIORXIV_CATEGORY_HINTS = [
    "microbiology",
    "genomics",
    "bioinformatics",
    "evolutionary biology",
    "systems biology",
]

KEYWORD_GROUPS = [
    ([r"\bmicrob\w*", r"\bbacteri\w*", r"\barchae\w*"], 1.0), # 微生物系
    ([r"\bgenom\w*", r"\bgene\b", r"\bdna\b"], 2.0), # ゲノム系
    ([r"\bmetagenom\w*", r"\bcommunity\b", r"\benvironment\w*"], 1.5), # 環境微生物
    ([r"\bphage\b", r"\bplasmid\b", r"\bmobile\b", r"\brna-seq\b"], 1.5), # モバイル要素
    ([r"\btranscript\w*", r"\brna\b", r"\bexpression\b"], 1.5), # 遺伝子発現
    ([r"\bevolution\b", r"\bphylogen\w*", r"\blineage\w*"], 1.0), # 進化系
    ([r"\balgorithm\w*", r"\bmodel\w*", r"\bmachine learning\b", r"\bprediction\b"], 1.0) # バイオインフォマティクス
]

JOURNAL_WEIGHTS = {
    "nature": 9.0,
    "science": 9.0,
    "science (New York, N.Y.)": 9.0,
    "cell": 9.0,
    "nature microbiology": 8.0,
    "nature biotechnology": 5.0,
    "nature communications": 5.0,
    "cell host & microbe": 4.5,
    "cell host and microbe": 4.5,
    "the isme journal": 4.5,
    "microbiome": 4.5,
    "genome biology": 4.5,
    "genome research": 4.0,
    "Science Advance": 3.0,
    "environmental microbiome": 3.0,
    "iScience": 3.0,
    "mBio": 3.8,
    "elife": 3.0,
    "msystems": 3.8,
    "Gut microbes": 5.0,
    "environmental microbiology": 3.5,
    "applied and environmental microbiology": 3.5,
    "nucleic acids research": 5.0,
    "pnas": 6.0,
    "Proceedings of the National Academy of Sciences of the United States of America": 6.0,
    "pnas nexus": 3.0,
}


# =========================
# データ構造
# =========================

@dataclass
class Paper:
    source: str
    source_id: str
    title: str
    abstract: str
    journal: str
    pub_date: str
    doi: str
    url: str
    authors: str
    score: float
    score_reason: str


# =========================
# ユーティリティ
# =========================

def normalize_text(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()

def normalize_doi(doi: Optional[str]) -> str:
    if not doi:
        return ""
    doi = doi.strip().lower()
    doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
    doi = doi.replace("doi:", "").strip()
    return doi

def parse_pub_date(date_str: str) -> Optional[dt.date]:
    date_str = normalize_text(date_str)
    if not date_str:
        return None

    fmts = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y %b %d",
        "%Y %B %d",
        "%Y %b",
        "%Y %B",
        "%Y",
    ]
    for fmt in fmts:
        try:
            parsed = dt.datetime.strptime(date_str, fmt).date()
            return parsed
        except ValueError:
            continue

    # "2026 Mar 12" みたいなケース向け簡易補正
    tokens = date_str.replace("-", " ").replace("/", " ").split()
    if len(tokens) >= 3:
        short = " ".join(tokens[:3])
        for fmt in ("%Y %b %d", "%Y %B %d"):
            try:
                return dt.datetime.strptime(short, fmt).date()
            except ValueError:
                pass
    return None

def days_since(date_str: str) -> int:
    d = parse_pub_date(date_str)
    if d is None:
        return 999
    delta = (dt.date.today() - d).days
    return max(delta, 0)

def keyword_score(title: str, abstract: str) -> float:
    text = f"{title} {abstract}".lower()
    score = 0.0

    for patterns, weight in KEYWORD_GROUPS:
        for pattern in patterns:
            if re.search(pattern, text):
                score += weight
                break

    return score

def journal_score(journal: str) -> float:
    j = journal.lower().strip()

    for key, weight in JOURNAL_WEIGHTS.items():
        k = key.lower().strip()

        if k == j:
            return weight

    return 0.0
    
def build_score(title, abstract, journal, pub_date, doi, is_preprint):
    ks = keyword_score(title, abstract)
    js = journal_score(journal)

    total = ks + js

    reasons = []
    if ks:
        reasons.append(f"keyword+{ks:.1f}")
    if js:
        reasons.append(f"journal+{js:.1f}")

    return total, ", ".join(reasons)

def request_json(url: str, params: Optional[dict] = None) -> dict:
    headers = {"User-Agent": f"{TOOL_NAME} ({EMAIL})"}
    r = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()

def request_text(url: str, params: Optional[dict] = None, max_retries: int = 5) -> str:
    headers = {"User-Agent": f"{TOOL_NAME} ({EMAIL})"}

    last_err = None
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            return r.text
        except requests.exceptions.RequestException as e:
            last_err = e
            wait = min(2 ** attempt, 20)
            print(f"[WARN] request failed ({attempt+1}/{max_retries}): {e}; retry in {wait}s", file=sys.stderr)
            time.sleep(wait)

    raise last_err


# =========================
# PubMed
# =========================

def fetch_pubmed_ids(days: int, retmax: int) -> List[str]:
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    params = {
        "db": "pubmed",
        "term": PUBMED_QUERY,
        "retmode": "json",
        "retmax": retmax,
        "sort": "pub date",
        "reldate": days,
        "datetype": "edat",
        "tool": TOOL_NAME,
        "email": EMAIL,
    }
    payload = request_json(url, params=params)
    return payload.get("esearchresult", {}).get("idlist", [])

def fetch_pubmed_details(pmids: List[str], chunk_size: int = 50) -> List[Paper]:
    if not pmids:
        return []

    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    papers: List[Paper] = []

    for i in range(0, len(pmids), chunk_size):
        chunk = pmids[i:i + chunk_size]

        params = {
            "db": "pubmed",
            "id": ",".join(chunk),
            "retmode": "xml",
            "tool": TOOL_NAME,
            "email": EMAIL,
        }

        try:
            xml_text = request_text(url, params=params)
        except requests.exceptions.RequestException as e:
            print(f"[WARN] skipping chunk {i}-{i+len(chunk)} because efetch failed: {e}", file=sys.stderr)
            continue

        root = ET.fromstring(xml_text)

        for article in root.findall(".//PubmedArticle"):
            medline = article.find("MedlineCitation")
            if medline is None:
                continue

            pmid_el = medline.find("PMID")
            pmid = pmid_el.text if pmid_el is not None else ""

            article_el = medline.find("Article")
            if article_el is None:
                continue

            title = normalize_text("".join(article_el.find("ArticleTitle").itertext())) \
                if article_el.find("ArticleTitle") is not None else ""

            abstract_texts = []
            abstract_el = article_el.find("Abstract")
            if abstract_el is not None:
                for at in abstract_el.findall("AbstractText"):
                    txt = normalize_text("".join(at.itertext()))
                    if txt:
                        abstract_texts.append(txt)
            abstract = normalize_text(" ".join(abstract_texts))

            journal = normalize_text(article_el.findtext("Journal/Title", default=""))

            pub_date = ""
            pubdate_el = article_el.find("Journal/JournalIssue/PubDate")
            if pubdate_el is not None:
                year = pubdate_el.findtext("Year", default="")
                month = pubdate_el.findtext("Month", default="")
                day = pubdate_el.findtext("Day", default="")
                pub_date = normalize_text(" ".join(x for x in [year, month, day] if x))

            authors = []
            for author in article_el.findall("AuthorList/Author"):
                last = author.findtext("LastName", default="")
                initials = author.findtext("Initials", default="")
                if last:
                    authors.append(f"{last} {initials}".strip())
            author_str = ", ".join(authors[:8]) + (", et al." if len(authors) > 8 else "")

            doi = ""
            for aid in article.findall(".//ArticleId"):
                if aid.attrib.get("IdType") == "doi" and aid.text:
                    doi = normalize_doi(aid.text)
                    break

            url_link = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"

            score, reason = build_score(
                title=title,
                abstract=abstract,
                journal=journal,
                pub_date=pub_date,
                doi=doi,
                is_preprint=False,
            )

            papers.append(
                Paper(
                    source="PubMed",
                    source_id=pmid,
                    title=title,
                    abstract=abstract,
                    journal=journal,
                    pub_date=pub_date,
                    doi=doi,
                    url=url_link,
                    authors=author_str,
                    score=score,
                    score_reason=reason,
                )
            )

        time.sleep(0.5)

    return papers


# =========================
# bioRxiv
# =========================

def fetch_biorxiv(days: int, max_pages: int = 5) -> List[Paper]:
    today = dt.date.today()
    start = today - dt.timedelta(days=days)
    interval = f"{start.isoformat()}/{today.isoformat()}"

    papers: List[Paper] = []
    cursor = 0

    for _ in range(max_pages):
        url = f"https://api.biorxiv.org/details/biorxiv/{interval}/{cursor}"
        payload = request_json(url)

        collection = payload.get("collection", [])
        if not collection:
            break

        for item in collection:
            title = normalize_text(item.get("title", ""))
            abstract = normalize_text(item.get("abstract", ""))
            journal = "bioRxiv"
            pub_date = normalize_text(item.get("date", ""))
            doi = normalize_doi(item.get("doi", ""))
            authors = normalize_text(item.get("authors", ""))
            category = normalize_text(item.get("category", ""))

            # categoryが全然関係なければ弱く除外
            category_hit = any(h.lower() in category.lower() for h in BIORXIV_CATEGORY_HINTS)
            text_hit = keyword_score(title, abstract) > 0
            if not category_hit and not text_hit:
                continue

            url_link = f"https://www.biorxiv.org/content/{doi}v1" if doi else ""

            score, reason = build_score(
                title=title,
                abstract=abstract,
                journal=journal,
                pub_date=pub_date,
                doi=doi,   # ←追加
                is_preprint=False,
            )

            papers.append(
                Paper(
                    source="bioRxiv",
                    source_id=doi or title[:50],
                    title=title,
                    abstract=abstract,
                    journal=journal,
                    pub_date=pub_date,
                    doi=doi,
                    url=url_link,
                    authors=authors,
                    score=score,
                    score_reason=reason,
                )
            )

        messages = payload.get("messages", [])
        if not messages:
            break

        total = int(messages[0].get("total", 0))
        cursor += 50
        if cursor >= total:
            break

        time.sleep(0.4)

    return papers


# =========================
# 重複除去・保存
# =========================

def deduplicate(papers: List[Paper]) -> List[Paper]:
    """
    DOI優先で重複除去。
    DOIがないものは title の正規化文字列で除去。
    出版版(PubMed)をbioRxivより優先。
    """
    seen: Dict[str, Paper] = {}
    for p in papers:
        key = p.doi if p.doi else normalize_text(p.title).lower()
        if key not in seen:
            seen[key] = p
            continue

        old = seen[key]
        # PubMed を優先
        if old.source == "bioRxiv" and p.source == "PubMed":
            seen[key] = p
        # abstractが長い方を優先
        elif len(p.abstract) > len(old.abstract):
            seen[key] = p

    return list(seen.values())

def save_csv(papers: List[Paper], path: str) -> None:
    fields = [
        "source",
        "source_id",
        "title",
        "abstract",
        "journal",
        "pub_date",
        "doi",
        "url",
        "authors",
        "score",
        "score_reason",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for p in papers:
            writer.writerow(asdict(p))

def save_json(papers: List[Paper], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(p) for p in papers], f, ensure_ascii=False, indent=2)


# =========================
# メイン
# =========================

def main() -> int:
    parser = argparse.ArgumentParser(description="Collect weekly microbiology/genomics notable papers.")
    parser.add_argument("--days", type=int, default=7, help="Look back this many days.")
    parser.add_argument("--max-pubmed", type=int, default=3000, help="Max PubMed hits to fetch.")
    parser.add_argument("--max-biorxiv-pages", type=int, default=5, help="Max bioRxiv pages (100/page).")
    parser.add_argument("--top", type=int, default=50, help="How many scored papers to keep in output.")
    args = parser.parse_args()

    print(f"[INFO] Fetching PubMed IDs for last {args.days} days...", file=sys.stderr)
    pmids = fetch_pubmed_ids(days=args.days, retmax=args.max_pubmed)

    print(f"[INFO] Fetching PubMed details for {len(pmids)} papers...", file=sys.stderr)
    pubmed_papers = fetch_pubmed_details(pmids)

    print(f"[INFO] Fetching bioRxiv papers for last {args.days} days...", file=sys.stderr)
    try:
        biorxiv_papers = fetch_biorxiv(days=args.days, max_pages=args.max_biorxiv_pages)
    except Exception as e:
        print(f"[WARN] bioRxiv fetch failed: {e}", file=sys.stderr)
        biorxiv_papers = []

    all_papers = deduplicate(pubmed_papers + biorxiv_papers)
    all_papers.sort(key=lambda x: x.score, reverse=True)

    if args.top > 0:
        all_papers = all_papers[:args.top]

    today = dt.date.today().isoformat()
    csv_path = f"papers_{today}.csv"
    json_path = f"papers_{today}.json"

    save_csv(all_papers, csv_path)
    save_json(all_papers, json_path)

    print(f"[INFO] Saved {len(all_papers)} papers to:", file=sys.stderr)
    print(f"  - {csv_path}", file=sys.stderr)
    print(f"  - {json_path}", file=sys.stderr)

    # 先頭10件を表示
    print("\nTop papers:")
    for i, p in enumerate(all_papers[:10], start=1):
        print(f"{i:02d}. [{p.score:.1f}] {p.title}")
        print(f"    {p.journal} | {p.pub_date} | {p.source}")
        if p.doi:
            print(f"    DOI: {p.doi}")
        print(f"    Reason: {p.score_reason}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
