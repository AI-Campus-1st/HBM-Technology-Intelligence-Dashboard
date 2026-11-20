"""
리포트 통합본 만들기(src.common.build_report) 테스트. 임시 폴더의 장 파일로 확인한다.

담당: 공동
일정: Day 7
"""

from src.common import build_report as br


def write(d, name, text):
    (d / name).write_text(text, encoding="utf-8")


def test_chapter_files_in_order_and_skip_merged(tmp_path):
    for name in ["02_b.md", "00_a.md", br.OUTPUT_NAME, "notes.md"]:
        write(tmp_path, name, "# x\n")
    assert [p.name for p in br.chapter_files(tmp_path)] == ["00_a.md", "02_b.md"]


def test_slug_matches_github_style():
    assert br.slug("1.1 기획 배경") == "11-기획-배경"
    assert br.slug("6.5 첫 화면 '요약' — 결론") == "65-첫-화면-요약--결론"
    assert br.slug("`sent_v2` 결과") == "sent_v2-결과"


def test_demote_skips_code_blocks():
    body, heads = br.demote("# 1. 장\n## 1.1 절\n```\n# 주석\n```\n###### 깊은 제목\n")
    assert heads == [(1, "1. 장"), (2, "1.1 절"), (6, "깊은 제목")]
    assert body.splitlines()[:2] == ["## 1. 장", "### 1.1 절"] and "# 주석" in body
    assert "###### 깊은 제목" in body  # 6단계는 더 내리지 않는다


def test_build_has_title_toc_and_all_chapters(tmp_path):
    write(tmp_path, "01_a.md", "# 1. 목적\n## 1.1 배경\n본문 A\n### 세부\n")
    write(tmp_path, "02_b.md", "# 2. 데이터\n## 한계\n본문 B\n")
    write(tmp_path, "03_c.md", "# 3. EDA\n## 한계\n")
    out = br.build(tmp_path)
    assert out.startswith(f"# {br.TITLE}") and "## 목차" in out
    assert "- [1. 목적](#1-목적)" in out and "  - [1.1 배경](#11-배경)" in out
    assert "세부](#" not in out  # 목차는 절(##)까지
    assert "(#한계)" in out and "(#한계-1)" in out  # 같은 제목은 -1
    assert out.index("본문 A") < out.index("본문 B") and "## 2. 데이터" in out


def test_merged_report_is_up_to_date():
    """docs/report/의 통합본이 장 파일과 같다. 다르면 python -m src.common.build_report"""
    out = br.REPORT_DIR / br.OUTPUT_NAME
    assert out.exists() and out.read_text(encoding="utf-8") == br.build(), \
        "통합본이 장 파일과 다릅니다: python -m src.common.build_report"
