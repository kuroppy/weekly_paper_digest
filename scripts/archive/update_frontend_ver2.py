#!/usr/bin/env python3

"""Update Weekly Paper Digest frontend pages from published files in docs/.

Updates:
- docs/index.html: latest issue date and date-dependent asset/content links
- docs/episodes/index.html: published episode list
- docs/editorial_notes/index.html: Editorial Meeting Notes list

Usage:
    python scripts/update_frontend.py
"""

from __future__ import annotations

import html
import re
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


def update_home(latest_date: str) -> None:
    """
    docs/index.html の最新号に紐づく「日付依存部分」だけを書き換える。

    現在のトップページでは最新号そのものを直接掲載しているため、
    以下を latest_date に揃える。

    - 表示日付: YYYY.MM.DD
    - 音声: ./episodes/YYYY-MM-DD/audio.mp3
    - Paper Review: ./episodes/YYYY-MM-DD/wpd_review.html
    - Editorial Meeting Note:
      ./editorial_notes/editorial_meeting_notes_YYYY-MM-DD.html

    issue-note や Deep Dive の本文は編集内容なので自動生成しない。
    トップページ全体も再生成しない。
    """

    text = HOME_PATH.read_text(
        encoding="utf-8"
    )

    display_date = latest_date.replace("-", ".")

    new_text, count_issue_date = re.subn(
        r'(<div class="issue-date">)\d{4}\.\d{2}\.\d{2}(</div>)',
        rf"\g<1>{display_date}\g<2>",
        text,
        count=1,
    )

    new_text, count_audio = re.subn(
        r'src="(?:\./assets/audio/[^"]+|'
        r'\./episodes/\d{4}-\d{2}-\d{2}/audio\.mp3)"',
        f'src="./episodes/{latest_date}/audio.mp3"',
        new_text,
        count=1,
    )

    new_text, count_review = re.subn(
        r'href="(?:\./paper_review/\d{4}-\d{2}-\d{2}\.html|'
        r'\./episodes/\d{4}-\d{2}-\d{2}/wpd_review\.html)"',
        f'href="./episodes/{latest_date}/wpd_review.html"',
        new_text,
        count=1,
    )

    new_text, count_note = re.subn(
        r'(href="\./editorial_notes/editorial_meeting_notes_)'
        r'\d{4}-\d{2}-\d{2}(\.html")',
        rf"\g<1>{latest_date}\g<2>",
        new_text,
        count=1,
    )

    checks = {
        "latest issue date": count_issue_date,
        "latest audio path": count_audio,
        "Paper Review link": count_review,
        "Editorial Meeting Note link": count_note,
    }

    failed = [
        name
        for name, count in checks.items()
        if count != 1
    ]

    if failed:
        raise RuntimeError(
            "Could not uniquely update docs/index.html: "
            + ", ".join(failed)
        )

    HOME_PATH.write_text(
        new_text,
        encoding="utf-8",
    )


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

    update_home(latest_date)

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
