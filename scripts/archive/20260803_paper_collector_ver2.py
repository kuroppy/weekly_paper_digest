#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
paper_collector.py

目的:
  週ごとに微生物・ゲノミクス関連の論文を収集し、
  タイトル、Abstract、ジャーナル、年月日などをCSV/JSONで保存する。

取得元:
  - PubMed (NCBI E-utilities)
  - bioRxiv API

環境変数 (.env):
  NCBI_EMAIL      必須
  NCBI_API_KEY    任意

出力:
  - papers_YYYY-MM-DD.csv
  - papers_YYYY-MM-DD.json

使い方:
  python scripts/paper_collector.py
  python scripts/paper_collector.py --days 7 --max-pubmed 3000 --max-biorxiv-pages 5
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv


# =========================
# パス・環境変数
# =========================

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

NCBI_EMAIL = os.getenv("NCBI_EMAIL", "").strip()
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "").strip()

TOOL_NAME = "paper_collector"
REQUEST_TIMEOUT = 60
MAX_RETRIES = 5


# =========================
# 検索・スコア設定
# =========================

PUBMED_QUERY = r"""
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
"""

BIORXIV_CATEGORY_HINTS = [
    "microbiology",
    "genomics",
    "bioinformatics",
    "evolutionary biology",
    "systems biology",
]

KEYWORD_GROUPS = [
    ([r"\bmicrob\w*", r"\bbacteri\w*", r"\barchae\w*"], 1.0),
    ([r"\bgenom\w*", r"\bgene\b", r"\bdna\b"], 2.0),
    ([r"\bmetagenom\w*", r"\bcommunity\b", r"\benvironment\w*"], 1.5),
    ([r"\bphage\b", r"\bplasmid\b", r"\bmobile\b", r"\brna-seq\b"], 1.5),
    ([r"\btranscript\w*", r"\brna\b", r"\bexpression\b"], 1.5),
    ([r"\bevolution\b", r"\bphylogen\w*", r"\blineage\w*"], 1.0),
    ([r"\balgorithm\w*", r"\bmodel\w*", r"\bmachine learning\b", r"\bprediction\b"], 1.0),
]

JOURNAL_WEIGHTS = {
    "nature": 9.0,
    "science": 9.0,
    "science (new york, n.y.)": 9.0,
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
    "science advances": 3.0,
    "environmental microbiome": 3.0,
    "iscience": 3.0,
    "mbio": 3.8,
    "elife": 3.0,
    "msystems": 3.8,
    "gut microbes": 5.0,
    "environmental microbiology": 3.5,
    "applied and environmental microbiology": 3.5,
    "nucleic acids research": 5.0,
    "pnas": 6.0,
    "proceedings of the national academy of sciences of the united states of america": 6.0,
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

def validate_environment() -> None:
    if not NCBI_EMAIL:
        raise RuntimeError(
            "NCBI_EMAIL is not set. Add it to the repository root .env file:\n"
            "NCBI_EMAIL=your-email@example.com"
        )


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


def keyword_score(title: str, abstract: str) -> float:
    text = f"{title} {abstract}".lower()
    score = 0.0

    for patterns, weight in KEYWORD_GROUPS:
        if any(re.search(pattern, text) for pattern in patterns):
            score += weight

    return score


def journal_score(journal: str) -> float:
    return JOURNAL_WEIGHTS.get(journal.lower().strip(), 0.0)


def build_score(title: str, abstract: str, journal: str) -> tuple[float, str]:
    ks = keyword_score(title, abstract)
    js = journal_score(journal)

    reasons = []
    if ks:
        reasons.append(f"keyword+{ks:.1f}")
    if js:
        reasons.append(f"journal+{js:.1f}")

    return ks + js, ", ".join(reasons)


def request(
    url: str,
    params: Optional[dict] = None,
    *,
    response_type: str = "json",
):
    headers = {"User-Agent": f"{TOOL_NAME} ({NCBI_EMAIL})"}

    last_err: Optional[Exception] = None

    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            r.raise_for_status()

            if response_type == "json":
                return r.json()
            if response_type == "text":
                return r.text

            raise ValueError(f"Unsupported response_type: {response_type}")

        except (requests.exceptions.RequestException, ValueError) as e:
            last_err = e

            if attempt == MAX_RETRIES - 1:
                break

            wait = min(2**attempt, 20)
            print(
                f"[WARN] request failed ({attempt + 1}/{MAX_RETRIES}): "
                f"{e}; retry in {wait}s",
                file=sys.stderr,
            )
            time.sleep(wait)

    if last_err is not None:
        raise last_err

    raise RuntimeError("Request failed for an unknown reason.")


def ncbi_common_params() -> dict:
    params = {
        "tool": TOOL_NAME,
        "email": NCBI_EMAIL,
    }
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    return params


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
        **ncbi_common_params(),
    }

    payload = request(url, params=params, response_type="json")
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
            **ncbi_common_params(),
        }

        try:
            xml_text = request(url, params=params, response_type="text")
        except Exception as e:
            print(
                f"[WARN] skipping PubMed chunk "
                f"{i}-{i + len(chunk)} because efetch failed: {e}",
                file=sys.stderr,
            )
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

            title_el = article_el.find("ArticleTitle")
            title = (
                normalize_text("".join(title_el.itertext()))
                if title_el is not None
                else ""
            )

            abstract_texts = []
            abstract_el = article_el.find("Abstract")
            if abstract_el is not None:
                for at in abstract_el.findall("AbstractText"):
                    txt = normalize_text("".join(at.itertext()))
                    if txt:
                        label = normalize_text(at.attrib.get("Label", ""))
                        abstract_texts.append(f"{label}: {txt}" if label else txt)
            abstract = normalize_text(" ".join(abstract_texts))

            journal = normalize_text(
                article_el.findtext("Journal/Title", default="")
            )

            pub_date = ""
            pubdate_el = article_el.find("Journal/JournalIssue/PubDate")
            if pubdate_el is not None:
                medline_date = pubdate_el.findtext("MedlineDate", default="")
                if medline_date:
                    pub_date = normalize_text(medline_date)
                else:
                    year = pubdate_el.findtext("Year", default="")
                    month = pubdate_el.findtext("Month", default="")
                    day = pubdate_el.findtext("Day", default="")
                    pub_date = normalize_text(
                        " ".join(x for x in [year, month, day] if x)
                    )

            authors = []
            for author in article_el.findall("AuthorList/Author"):
                collective = author.findtext("CollectiveName", default="")
                if collective:
                    authors.append(normalize_text(collective))
                    continue

                last = author.findtext("LastName", default="")
                initials = author.findtext("Initials", default="")
                if last:
                    authors.append(f"{last} {initials}".strip())

            author_str = ", ".join(authors[:8])
            if len(authors) > 8:
                author_str += ", et al."

            doi = ""
            for aid in article.findall(".//ArticleId"):
                if aid.attrib.get("IdType") == "doi" and aid.text:
                    doi = normalize_doi(aid.text)
                    break

            score, reason = build_score(
                title=title,
                abstract=abstract,
                journal=journal,
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
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    authors=author_str,
                    score=score,
                    score_reason=reason,
                )
            )

        # NCBIへの過剰アクセスを避ける
        time.sleep(0.4)

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
        payload = request(url, response_type="json")

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
            version = str(item.get("version", "1")).strip() or "1"

            category_hit = any(
                hint.lower() in category.lower()
                for hint in BIORXIV_CATEGORY_HINTS
            )
            text_hit = keyword_score(title, abstract) > 0

            if not category_hit and not text_hit:
                continue

            score, reason = build_score(
                title=title,
                abstract=abstract,
                journal=journal,
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
                    url=(
                        f"https://www.biorxiv.org/content/{doi}v{version}"
                        if doi
                        else ""
                    ),
                    authors=authors,
                    score=score,
                    score_reason=reason,
                )
            )

        messages = payload.get("messages", [])
        if not messages:
            break

        total = int(messages[0].get("total", 0))

        # APIの1ページ件数を決め打ちせず、実際に返った件数だけ進める
        cursor += len(collection)

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
    DOIがないものはタイトルの正規化文字列で除去。
    同一論文なら出版版(PubMed)をbioRxivより優先する。
    """
    seen: Dict[str, Paper] = {}

    for p in papers:
        key = p.doi if p.doi else normalize_text(p.title).lower()

        if key not in seen:
            seen[key] = p
            continue

        old = seen[key]

        if old.source == "bioRxiv" and p.source == "PubMed":
            seen[key] = p
        elif old.source == p.source and len(p.abstract) > len(old.abstract):
            seen[key] = p

    return list(seen.values())


def save_csv(papers: List[Paper], path: Path) -> None:
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

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

        for p in papers:
            writer.writerow(asdict(p))


def save_json(papers: List[Paper], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(
            [asdict(p) for p in papers],
            f,
            ensure_ascii=False,
            indent=2,
        )


# =========================
# メイン
# =========================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect weekly microbiology/genomics papers."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Look back this many days.",
    )
    parser.add_argument(
        "--max-pubmed",
        type=int,
        default=3000,
        help="Maximum number of PubMed hits to fetch.",
    )
    parser.add_argument(
        "--max-biorxiv-pages",
        type=int,
        default=5,
        help="Maximum number of bioRxiv API pages to fetch.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=50,
        help="Number of highest-scoring papers to save. Use 0 to save all.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.cwd(),
        help="Directory for CSV/JSON output. Default: current directory.",
    )
    args = parser.parse_args()

    validate_environment()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"[INFO] Fetching PubMed IDs for last {args.days} days...",
        file=sys.stderr,
    )
    pmids = fetch_pubmed_ids(
        days=args.days,
        retmax=args.max_pubmed,
    )

    print(
        f"[INFO] Fetching PubMed details for {len(pmids)} papers...",
        file=sys.stderr,
    )
    pubmed_papers = fetch_pubmed_details(pmids)

    print(
        f"[INFO] Fetching bioRxiv papers for last {args.days} days...",
        file=sys.stderr,
    )
    try:
        biorxiv_papers = fetch_biorxiv(
            days=args.days,
            max_pages=args.max_biorxiv_pages,
        )
    except Exception as e:
        print(
            f"[WARN] bioRxiv fetch failed: {e}",
            file=sys.stderr,
        )
        biorxiv_papers = []

    all_papers = deduplicate(pubmed_papers + biorxiv_papers)
    all_papers.sort(key=lambda x: x.score, reverse=True)

    if args.top > 0:
        all_papers = all_papers[:args.top]

    today = dt.date.today().isoformat()
    csv_path = args.output_dir / f"papers_{today}.csv"
    json_path = args.output_dir / f"papers_{today}.json"

    save_csv(all_papers, csv_path)
    save_json(all_papers, json_path)

    print(
        f"[INFO] Saved {len(all_papers)} papers to:",
        file=sys.stderr,
    )
    print(f"  - {csv_path}", file=sys.stderr)
    print(f"  - {json_path}", file=sys.stderr)

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
