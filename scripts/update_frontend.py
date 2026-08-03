#!/usr/bin/env python3

"""Update Weekly Paper Digest frontend pages from published files in docs/.

Updates:
- docs/index.html: latest episode date and link
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
    docs/index.html の

        Latestの日付
        Latest episodeへのリンク

    の2か所だけを書き換える。

    トップページ全体は人間が編集する内容も多いので、
    HTML全体を再生成しない。
    """

    text = HOME_PATH.read_text(
        encoding="utf-8"
    )

    new_text, count_date = re.subn(
        r"(<strong>Latest:</strong>\s*)\d{4}-\d{2}-\d{2}",
        rf"\g<1>{latest_date}",
        text,
        count=1,
    )

    new_text, count_link = re.subn(
        r'href="episodes/\d{4}-\d{2}-\d{2}/"',
        f'href="episodes/{latest_date}/"',
        new_text,
        count=1,
    )

    if count_date != 1:
        raise RuntimeError(
            "Could not uniquely update Latest date in docs/index.html"
        )

    if count_link != 1:
        raise RuntimeError(
            "Could not uniquely update Latest episode link in docs/index.html"
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
