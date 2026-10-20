#!/usr/bin/env python3

"""Update Weekly Paper Digest frontend pages from published files in docs/.

Updates:
- docs/index.html: latest issue date and date-dependent asset/content links
- docs/episodes/index.html: published episode list
- docs/editorial_notes/index.html: Editorial Meeting Notes list

Usage:
    python scripts/update_frontend.py
    python scripts/update_frontend.py --audio https://example.org/audio.mp3
"""

from __future__ import annotations

import argparse
import html
import json
import re
from urllib.parse import urlparse
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

DOCS_DIR = REPO_ROOT / "docs"
EPISODES_DIR = DOCS_DIR / "episodes"
EDITORIAL_NOTES_DIR = DOCS_DIR / "editorial_notes"

HOME_PATH = DOCS_DIR / "index.html"
EPISODES_INDEX_PATH = EPISODES_DIR / "index.html"
EDITORIAL_NOTES_INDEX_PATH = EDITORIAL_NOTES_DIR / "index.html"


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

NOTE_RE = re.compile(
    r"^editorial_meeting_notes_(\d{4}-\d{2}-\d{2})\.html$"
)


def escape(text: str) -> str:
    """HTMLへ安全に文字列を埋め込むためのエスケープ処理。"""
    return html.escape(text or "", quote=True)


def get_episode_dates() -> list[str]:
    """
    公開済みepisodeの日付を、新しい順で返す。

    公開済みとみなす条件:

        docs/episodes/YYYY-MM-DD/index.html

    が存在すること。

    例:

        [
            "2026-08-03",
            "2026-07-27",
            "2026-07-21",
        ]
    """

    dates: list[str] = []

    for path in EPISODES_DIR.iterdir():

        if (
            path.is_dir()
            and DATE_RE.fullmatch(path.name)
            and (path / "index.html").exists()
        ):
            dates.append(path.name)

    return sorted(dates, reverse=True)


def get_editorial_notes() -> list[tuple[str, str]]:
    """
    Editorial Meeting Notes を、新しい順で返す。

    標準ファイル名:

        editorial_meeting_notes_2026-08-03.html

    戻り値:

        [
            (
                "2026-08-03",
                "editorial_meeting_notes_2026-08-03.html"
            ),
            ...
        ]

    日付は表示用、
    ファイル名はリンク作成用に使う。
    """

    notes: list[tuple[str, str]] = []

    for path in EDITORIAL_NOTES_DIR.glob("*.html"):

        match = NOTE_RE.fullmatch(path.name)

        if not match:
            continue

        date = match.group(1)

        notes.append(
            (date, path.name)
        )

    notes.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    return notes


def load_papers(episode_date: str) -> list[dict]:
    """Read published paper metadata from the episode's editorial selection JSON."""
    source = REPO_ROOT / "work" / episode_date / f"editorial_selection_{episode_date}.json"
    with source.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if data.get("episode") != episode_date or not isinstance(data.get("papers"), list):
        raise ValueError(f"Invalid editorial selection JSON: {source}")
    papers = []
    for index, entry in enumerate(data["papers"], 1):
        section = entry.get("section")
        if section not in ("deep_dive", "main_papers", "short_news"):
            raise ValueError(f"papers[{index}]: unsupported section {section!r}")
        paper = entry.get("paper", {})
        title, doi, journal = paper.get("title"), paper.get("doi"), paper.get("journal")
        authors = paper.get("authors", "")
        if not isinstance(authors, str):
            raise ValueError(f"papers[{index}]: authors must be a string")
        order = entry.get("order")
        if (not isinstance(title, str) or not title.strip() or not isinstance(doi, str) or not doi.strip()
                or not isinstance(journal, str) or not journal.strip()):
            raise ValueError(f"papers[{index}]: missing title or DOI")
        if type(order) is not int or order < 1:
            raise ValueError(f"papers[{index}]: invalid order")
        papers.append({"section": "deep_dive" if section == "main_papers" else section,
                       "order": order, "title": title.strip(), "journal": journal.strip(),
                       "authors": authors.strip(),
                       "doi": re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi.strip(), flags=re.I)})
    return sorted(papers, key=lambda p: (0 if p["section"] == "deep_dive" else 1, p["order"]))


def paper_summary_html(papers: list[dict]) -> str:
    """Render only Deep Dive on the homepage, using existing site CSS classes."""
    selected = [p for p in papers if p["section"] == "deep_dive"]
    if not selected:
        raise ValueError("No Deep Dive papers found for homepage")
    items = "\n".join(
        '                <li>\n'
        f'                  <a class="paper-title" href="https://doi.org/{escape(p["doi"])}">\n'
        f'                    {escape(p["title"])}\n'
        '                  </a>\n'
        + (f'                  <span class="authors">{escape(p["authors"])}</span>\n' if p["authors"] else "")
        + f'                  <span class="journal">{escape(p["journal"])}</span>\n'
        '                </li>'
        for p in selected
    )
    return ('            <div class="deep-dive">\n'
            '              <div class="section-label">Deep Dive</div>\n'
            '              <ul class="paper-list">\n'
            + items + '\n'
            '              </ul>\n'
            '            </div>')


def get_episode_audio(episode_date: str) -> str:
    """Use the audio source already embedded by build_episode.py."""
    page = (EPISODES_DIR / episode_date / "index.html").read_text(encoding="utf-8")
    match = re.search(r'<audio\b[^>]*>\s*<source\b[^>]*\bsrc=[\"\']([^\"\']+)', page, re.I | re.S)
    if not match:
        raise ValueError(f"Audio <source> not found in episode HTML for {episode_date}")
    source = html.unescape(match.group(1))
    parsed = urlparse(source)
    if parsed.scheme:
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("Episode audio URL must be HTTPS")
        return source
    if Path(source).name != source:
        raise ValueError(f"Unexpected episode audio path: {source}")
    return f"./episodes/{episode_date}/{source}"


def update_home(latest_date: str, audio_override: str | None = None) -> None:
    """Update date, audio, links, and the marked paper list on the homepage.

    The paper list is replaced only between these explicit markers:
      <!-- WPD_PAPERS_START -->
      <!-- WPD_PAPERS_END -->
    This avoids overwriting editorial prose or unrelated HTML.
    """
    text = HOME_PATH.read_text(encoding="utf-8")
    audio_source = audio_override or get_episode_audio(latest_date)
    parsed = urlparse(audio_source)
    if parsed.scheme and (parsed.scheme != "https" or not parsed.netloc):
        raise ValueError("--audio URL must be HTTPS")
    audio_source = escape(audio_source)
    display_date = latest_date.replace("-", ".")

    new_text, count_date = re.subn(
        r'(<div class="issue-date">)\d{4}\.\d{2}\.\d{2}(</div>)',
        lambda m: m.group(1) + display_date + m.group(2), text, count=1)
    # Replace only the source of the first audio player, not arbitrary media assets.
    new_text, count_audio = re.subn(
        r'(<audio\b[^>]*>\s*<source\b[^>]*\bsrc=[\"\'])([^\"\']+)([\"\'])',
        lambda m: m.group(1) + audio_source + m.group(3), new_text,
        count=1, flags=re.I | re.S)
    new_text, count_review = re.subn(
        r'href="(?:\./paper_review/\d{4}-\d{2}-\d{2}\.html|'
        r'\./episodes/\d{4}-\d{2}-\d{2}/wpd_review\.html)"',
        lambda _: f'href="./episodes/{latest_date}/wpd_review.html"',
        new_text, count=1)
    new_text, count_note = re.subn(
        r'(href="\./editorial_notes/editorial_meeting_notes_)'
        r'\d{4}-\d{2}-\d{2}(\.html")',
        lambda m: m.group(1) + latest_date + m.group(2), new_text, count=1)

    start_marker, end_marker = "<!-- WPD_PAPERS_START -->", "<!-- WPD_PAPERS_END -->"
    if new_text.count(start_marker) != 1 or new_text.count(end_marker) != 1:
        raise RuntimeError("docs/index.html needs exactly one WPD_PAPERS_START / WPD_PAPERS_END marker pair around its paper list")
    start = new_text.index(start_marker) + len(start_marker)
    end = new_text.index(end_marker)
    if start >= end:
        raise RuntimeError("Homepage paper markers are reversed")
    papers_html = paper_summary_html(load_papers(latest_date))
    new_text = new_text[:start] + "\n" + papers_html + "\n" + new_text[end:]

    checks = {"issue date": count_date, "audio source": count_audio,
              "Paper Review link": count_review, "Editorial Note link": count_note}
    failed = [name for name, count in checks.items() if count != 1]
    if failed:
        raise RuntimeError("Could not uniquely update docs/index.html: " + ", ".join(failed))
    HOME_PATH.write_text(new_text, encoding="utf-8")


def analytics_html() -> str:
    """一覧ページ共通のGoogle Analytics。"""

    return """<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-N22XGSKTFW"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());

  gtag('config', 'G-N22XGSKTFW');
</script>"""


def build_episodes_index(dates: list[str]) -> str:
    """
    episode一覧ページのHTML全文を作る。

    例:

        2026-08-03
        2026-07-27
        2026-07-21

    をリンク付き一覧にする。
    """

    items = "\n".join(
        f"""      <li>
        <a href="{escape(date)}/">{escape(date)}</a>
      </li>"""
        for date in dates
    )

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>過去の配信 | Weekly Paper Digest</title>
  <link rel="stylesheet" href="../assets/style.css">

  {analytics_html()}
</head>

<body>

<div class="container">

  <nav class="site-nav" aria-label="Site navigation">
    <a
      class="site-home-link"
      href="https://kuroppy.github.io/weekly_paper_digest/"
    >
      ← Weekly Paper Digest Home
    </a>
  </nav>

  <header class="page-header">
    <h1>過去の配信</h1>
  </header>

  <ul class="episode-list">
{items}
  </ul>

  <footer>
    <p>Created by Masaomi Kurokawa</p>
  </footer>

</div>

</body>
</html>
"""


def build_editorial_notes_index(
    notes: list[tuple[str, str]],
) -> str:
    """
    Editorial Meeting Notes一覧ページのHTML全文を作る。

    表示名:

        Editorial Meeting Notes — 2026-08-03

    リンク先:

        editorial_meeting_notes_2026-08-03.html
    """

    items = "\n".join(
        f"""      <li>
        <a href="{escape(filename)}">
          Editorial Meeting Notes — {escape(date)}
        </a>
      </li>"""
        for date, filename in notes
    )

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>編集会議議事録 | Weekly Paper Digest</title>
  <link rel="stylesheet" href="../assets/style.css">

  {analytics_html()}
</head>

<body>

<div class="container">

  <nav class="site-nav" aria-label="Site navigation">
    <a
      class="site-home-link"
      href="https://kuroppy.github.io/weekly_paper_digest/"
    >
      ← Weekly Paper Digest Home
    </a>
  </nav>

  <header class="page-header">
    <h1>編集会議議事録</h1>
  </header>

  <p>
    Weekly Paper Digest は、完成したコンテンツだけでなく、
    その制作過程も公開しています。
  </p>

  <p>
    論文の選び方、番組構成、プロンプトの改善などについて、
    人間とAIが対話しながら試行錯誤した記録を
    「編集会議議事録」として残しています。
  </p>

  <p>
    このプロジェクトでは、完成した結果だけでなく、
    編集上の意思決定やその背景も記録することを大切にしています。
  </p>

  <ul class="episode-list">
{items}
  </ul>

  <footer>
    <p>Created by Masaomi Kurokawa</p>
  </footer>

</div>

</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", help="Optional HTTPS audio URL or local homepage audio path; default: read episode HTML")
    args = parser.parse_args()

    if not HOME_PATH.exists():
        raise FileNotFoundError(
            f"Home page not found: {HOME_PATH}"
        )

    episode_dates = get_episode_dates()

    if not episode_dates:
        raise RuntimeError(
            "No published episodes found."
        )

    latest_date = episode_dates[0]

    editorial_notes = get_editorial_notes()

    update_home(latest_date, args.audio)

    EPISODES_INDEX_PATH.write_text(
        build_episodes_index(
            episode_dates
        ),
        encoding="utf-8",
    )

    EDITORIAL_NOTES_INDEX_PATH.write_text(
        build_editorial_notes_index(
            editorial_notes
        ),
        encoding="utf-8",
    )

    print()
    print("Frontend update completed")
    print("-------------------------")
    print(f"Latest episode : {latest_date}")
    print(f"Episodes       : {len(episode_dates)}")
    print(f"Editorial notes: {len(editorial_notes)}")
    print()

    print(
        f"Updated: {HOME_PATH.relative_to(REPO_ROOT)}"
    )
    print(
        f"Updated: {EPISODES_INDEX_PATH.relative_to(REPO_ROOT)}"
    )
    print(
        f"Updated: {EDITORIAL_NOTES_INDEX_PATH.relative_to(REPO_ROOT)}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
