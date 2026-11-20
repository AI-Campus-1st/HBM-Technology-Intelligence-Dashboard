"""
리포트 장별 파일(docs/report/00~07_*.md)을 한 문서로 묶는다 → docs/report/리포트_통합본.md

- 장 파일이 원본이고 통합본은 만들어지는 파일이다. 고칠 때는 장 파일을 고친 뒤 다시 실행한다.
- 장 제목(#)은 한 단계 내려(##) 문서 제목 아래에 둔다. 맨 앞에 목차(장·절 제목, 링크)를 만든다.
- 코드 블록(```) 안의 # 줄은 제목으로 보지 않는다.

실행: python -m src.common.build_report          (통합본 저장)
      python -m src.common.build_report --check  (통합본이 장 파일과 같은지 확인만, 다르면 종료 코드 1)

담당: 공동
일정: Day 7
"""

import argparse
import re
import sys
from pathlib import Path

from src.common import config

REPORT_DIR = config.ROOT_DIR / "docs" / "report"
OUTPUT_NAME = "리포트_통합본.md"
TITLE = "HBM 기술 인텔리전스 대시보드 — 최종 리포트"
SUBTITLE = "SK하이닉스·삼성전자 HBM 이슈와 공시 근거 (뉴스·DART 공시, 2023-10-19 ~ 2026-10-19) · 김한승 · 한도윤"
CHAPTER_PATTERN = re.compile(r"^\d{2}_.+\.md$")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def chapter_files(report_dir: Path = REPORT_DIR) -> list[Path]:
    """번호로 시작하는 장 파일(00_ ~ 07_)을 번호 순으로. 통합본 자신은 뺀다."""
    return sorted(p for p in report_dir.glob("*.md") if CHAPTER_PATTERN.match(p.name))


def slug(text: str) -> str:
    """GitHub 방식 제목 앵커: 소문자, 글자·숫자·공백·하이픈·밑줄만 남기고 공백을 하이픈으로."""
    text = re.sub(r"[`*]", "", text.strip().lower())
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def demote(markdown: str) -> tuple[str, list[tuple[int, str]]]:
    """제목을 한 단계 내리고, 코드 블록 밖의 제목 목록 [(원래 단계, 제목)]을 돌려준다."""
    lines, headings, in_code = [], [], False
    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
        m = None if in_code else HEADING.match(line)
        if m:
            level, text = len(m.group(1)), m.group(2).strip()
            headings.append((level, text))
            line = "#" * min(level + 1, 6) + " " + text
        lines.append(line)
    return "\n".join(lines).strip() + "\n", headings


def build(report_dir: Path = REPORT_DIR) -> str:
    """통합본 문자열. 목차는 장(#)과 절(##)까지 만든다."""
    bodies, toc, seen = [], [], {}
    for path in chapter_files(report_dir):
        body, headings = demote(path.read_text(encoding="utf-8"))
        bodies.append(body)
        for level, text in headings:
            base = slug(text)
            n = seen.get(base, 0)
            seen[base] = n + 1
            anchor = base if n == 0 else f"{base}-{n}"  # 같은 제목이 또 나오면 GitHub처럼 -1, -2
            if level <= 2:
                toc.append(f"{'  ' * (level - 1)}- [{text}](#{anchor})")
    head = (f"# {TITLE}\n\n{SUBTITLE}\n\n"
            f"> 이 파일은 `python -m src.common.build_report`로 만든다. 고칠 때는 `docs/report/`의 장 파일"
            f"({len(bodies)}개)을 고친 뒤 다시 실행한다.\n\n## 목차\n\n" + "\n".join(toc) + "\n")
    return "\n---\n\n".join([head, *bodies])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--check", action="store_true", help="통합본이 장 파일과 같은지 확인만 한다")
    args = parser.parse_args(argv)
    out = REPORT_DIR / OUTPUT_NAME
    text = build()
    if args.check:
        same = out.exists() and out.read_text(encoding="utf-8") == text
        print("통합본이 최신입니다." if same else f"통합본이 장 파일과 다릅니다. 다시 실행하세요: python -m src.common.build_report")
        return 0 if same else 1
    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"{out.relative_to(config.ROOT_DIR)} 저장: 장 {len(chapter_files())}개, {len(text.splitlines())}줄")
    return 0


if __name__ == "__main__":
    sys.exit(main())
