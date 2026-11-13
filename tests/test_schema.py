"""
통합 스키마(src/common/schema.py) 테스트.

- docs/schema.md와 schema.py의 테이블·컬럼·타입이 일치하는지 확인한다 (둘을 같은 PR에서 고친다는 규칙을 자동 점검).
- 생성한 DDL이 SQLite에서 실행되고, PK·FK·CHECK 제약이 실제로 동작하는지 확인한다.

담당: 공동 (변경 시 PR로 합의)
일정: Day 1
"""

import re
import sqlite3
from pathlib import Path

import pytest

from src.common import schema

SCHEMA_MD = Path(__file__).resolve().parents[1] / "docs" / "schema.md"


def parse_schema_md(path: Path) -> dict[str, list[tuple[str, str]]]:
    """schema.md에서 '## 테이블명' 아래 '| 컬럼 | 타입 | ...' 표를 읽어 {테이블: [(컬럼, 타입)]}을 만든다."""
    tables: dict[str, list[tuple[str, str]]] = {}
    current = None
    in_column_table = False
    for line in path.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"^##\s+(\w+)", line)
        if heading:
            current = heading.group(1)
            in_column_table = False
            continue
        if not line.startswith("|") or current is None:
            in_column_table = False
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells[:2] == ["컬럼", "타입"]:
            in_column_table = True
            tables[current] = []
            continue
        if in_column_table and not set(cells[0]) <= set("-: "):
            tables[current].append((cells[0].strip("`"), cells[1]))
    return tables


@pytest.fixture
def conn():
    """스키마를 만든 메모리 DB. FK 검사를 켠다."""
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    schema.create_all(connection)
    yield connection
    connection.close()


def insert_news(conn, news_id="n1"):
    conn.execute(
        "INSERT INTO news (news_id, published_at, title, url) VALUES (?, ?, ?, ?)",
        (news_id, "2024-04-01", "제목", f"https://example.com/{news_id}"),
    )


# ── 문서와 코드 일치 ──

def test_schema_md_matches_code():
    documented = parse_schema_md(SCHEMA_MD)
    in_code = {t.name: [(c.name, c.type) for c in t.columns] for t in schema.TABLES.values()}
    assert documented == in_code


def test_column_types_are_known():
    for table in schema.TABLES.values():
        for column in table.columns:
            assert column.type in schema.SQL_TYPES, f"{table.name}.{column.name}: {column.type}"


# ── DDL 실행 ──

def test_create_all_creates_every_table(conn):
    created = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert set(schema.TABLES) <= created


def test_create_all_is_idempotent(conn):
    schema.create_all(conn)  # 두 번 실행해도 오류가 없어야 한다


# ── 제약 조건 ──

def test_news_defaults_mark_not_duplicate(conn):
    insert_news(conn)
    assert conn.execute("SELECT is_duplicate FROM news").fetchone()[0] == 0


def test_news_requires_title(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO news (news_id, published_at, url) VALUES ('n1', '2024-04-01', 'u')"
        )


def test_news_tag_rejects_unknown_relevance(conn):
    insert_news(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO news_tag VALUES ('n1', 'tech', 'HBM', '매우중요', 1, 3, 'v1')"
        )


def test_news_tag_primary_key_blocks_duplicate_tag(conn):
    insert_news(conn)
    row = ("n1", "tech", "HBM", "핵심", 1, 3, "v1")
    conn.execute("INSERT INTO news_tag VALUES (?, ?, ?, ?, ?, ?, ?)", row)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO news_tag VALUES (?, ?, ?, ?, ?, ?, ?)", row)


def test_news_analysis_requires_existing_news(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO news_analysis (news_id, prompt_version, sentiment_skh, sentiment_sec, model) "
            "VALUES ('없는기사', 'v1', '긍정', '해당없음', 'm')"
        )


def test_news_analysis_rejects_unknown_sentiment(conn):
    insert_news(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO news_analysis (news_id, prompt_version, sentiment_skh, sentiment_sec, model) "
            "VALUES ('n1', 'v1', 'positive', '중립', 'm')"
        )


def test_news_analysis_keeps_results_per_prompt_version(conn):
    insert_news(conn)
    sql = (
        "INSERT INTO news_analysis (news_id, prompt_version, sentiment_skh, sentiment_sec, model) "
        "VALUES ('n1', ?, '긍정', '중립', 'm')"
    )
    conn.execute(sql, ("v1",))
    conn.execute(sql, ("v2",))  # 프롬프트 버전이 다르면 같은 기사도 함께 저장
    assert conn.execute("SELECT COUNT(*) FROM news_analysis").fetchone()[0] == 2


def test_issue_evidence_requires_existing_issue(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO issue_evidence (issue_id, match_type) VALUES ('없는이슈', '수동')"
        )


def test_issue_evidence_assigns_id_automatically(conn):
    conn.execute(
        "INSERT INTO issues (issue_id, tech_tag, start_date, end_date, peak_date, peak_share, article_count, method) "
        "VALUES ('HBM-2024-04-08', 'HBM', '2024-04-08', '2024-04-21', '2024-04-15', 0.08, 120, 'v1')"
    )
    conn.execute("INSERT INTO issue_evidence (issue_id, match_type) VALUES ('HBM-2024-04-08', '기간')")
    evidence_id, verified = conn.execute("SELECT evidence_id, verified FROM issue_evidence").fetchone()
    assert evidence_id == 1 and verified == 0
