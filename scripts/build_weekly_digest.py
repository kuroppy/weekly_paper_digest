#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create a NotebookLM source Markdown from a WPD editorial_selection JSON.

Only the selected papers' bibliographic information and original abstracts
are included. Deep Dive PDFs are numbered in their editorial order.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def compile_digest(data: dict[str, Any]) -> str:
    papers = data.get('papers')
    if not isinstance(papers, list):
        raise ValueError('papers must be a list')

    selected: dict[str, list[dict[str, Any]]] = {'short_news': [], 'deep_dive': []}
    for i, item in enumerate(papers):
        if not isinstance(item, dict):
            raise ValueError(f'papers[{i}] must be an object')
        placement = item.get('placement', item.get('section'))
        if placement not in selected:
            continue
        if not isinstance(item.get('paper'), dict):
            raise ValueError(f'papers[{i}].paper must be an object')
        selected[placement].append(item)

    for group in selected.values():
        group.sort(key=lambda x: x.get('order', 10**9))

    lines = [
        '# Weekly Paper Digest — 論文資料（選定のみ・実験版）',
        '',
        'この資料は論文の選定結果と書誌情報・原文Abstractのみを収録しています。編集者による解釈・評価・紹介順の指定は含みません。',
        '', '---', '', '# ShortNews',
    ]

    def add_paper(item: dict[str, Any], section: str, n: int) -> None:
        p = item['paper']
        title = str(p.get('title') or '').strip()
        journal = str(p.get('journal') or '').strip()
        doi = str(p.get('doi') or '').strip()
        abstract = str(p.get('abstract') or '').strip()
        if not title or not abstract:
            raise ValueError(f'Missing title or original abstract for {section} {n}')
        lines.extend(['', f'## {section}{n}', f'### {title}', '',
                      f'- **Journal:** {journal}', f'- **DOI:** {doi}'])
        if section == 'DeepDive':
            lines.append(f'- **PDF file:** paper{n}.pdf')
        lines.extend(['', '**Abstract (original)**', '', abstract, ''])

    for n, item in enumerate(selected['short_news'], 1):
        add_paper(item, 'ShortNews', n)
    lines.extend(['---', '', '# DeepDive'])
    for n, item in enumerate(selected['deep_dive'], 1):
        add_paper(item, 'DeepDive', n)
    return '\n'.join(lines).rstrip() + '\n'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--editorial', required=True, type=Path)
    parser.add_argument('--output', default='weekly_digest.md', type=Path)
    args = parser.parse_args()
    data = json.loads(args.editorial.read_text(encoding='utf-8'))
    result = compile_digest(data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result, encoding='utf-8')
    print(f'Wrote {args.output}')


if __name__ == '__main__':
    main()
