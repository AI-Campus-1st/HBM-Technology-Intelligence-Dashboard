"""
뉴스·공시 통합 스키마 정의(테이블 이름, 컬럼, 타입, 제약). docs/schema.md와 내용을 항상 맞춘다.

- 테이블 정의를 코드(데이터)로 한 곳에 모아 두고, CREATE TABLE 문은 여기서 생성한다.
- 라벨 값(기술 태그, 감성, 관련도 등)도 여기서 상수로 정의한다.
  수집·태깅·LLM 분류·대시보드 코드는 문자열을 직접 쓰지 말고 이 상수를 가져다 쓴다.
- 문서와 코드가 어긋나면 tests/test_schema.py가 실패한다.

담당: 공동 (변경 시 PR로 합의)
일정: Day 1
"""

import sqlite3
from dataclasses import dataclass, field

# ── 라벨 값 (CHECK 제약과 분석 코드가 함께 사용) ──
TECH_TAGS = ("HBM", "패키징", "DRAM")
COMPANY_TAGS = ("SK하이닉스", "삼성전자")
TAG_TYPES = ("tech", "company")
RELEVANCE_LEVELS = ("핵심", "관련", "언급")  # 핵심: 제목 포함 / 관련: 본문 2회 이상 / 언급: 본문 1회
SENTIMENT_LABELS = ("긍정", "중립", "부정", "해당없음")  # 해당 기업의 HBM 사업 관점
MATCH_TYPES = ("기간", "키워드", "수동")

# 문서에 쓰는 논리 타입 → SQLite 타입. 날짜는 'YYYY-MM-DD' 문자열로 저장한다.
SQL_TYPES = {"TEXT": "TEXT", "DATE": "TEXT", "INTEGER": "INTEGER", "REAL": "REAL"}


@dataclass(frozen=True)
class Column:
    """테이블 컬럼 하나.

    Args:
        name: 컬럼명
        type: 논리 타입 (SQL_TYPES의 키)
        description: 설명 (docs/schema.md와 같은 의미)
        not_null: NOT NULL 여부
        allowed: 허용 값 목록. 지정하면 CHECK (col IN (...)) 제약을 만든다.
        default: 기본값 (SQL 리터럴 문자열, 예: "0")
    """

    name: str
    type: str
    description: str = ""
    not_null: bool = False
    allowed: tuple = ()
    default: str | None = None


@dataclass(frozen=True)
class Table:
    """테이블 하나. foreign_keys는 (내 컬럼, 참조 테이블, 참조 컬럼) 튜플의 목록이다."""

    name: str
    owner: str
    columns: tuple[Column, ...]
    primary_key: tuple[str, ...]
    foreign_keys: tuple[tuple[str, str, str], ...] = field(default_factory=tuple)


BOOL = (0, 1)

TABLES: dict[str, Table] = {
    t.name: t
    for t in (
        Table(
            name="news",
            owner="김한승",
            columns=(
                Column("news_id", "TEXT", "원문 URL의 SHA-1 앞 16자리", not_null=True),
                Column("published_at", "DATE", "발행일 (시각 제외)", not_null=True),
                Column("title", "TEXT", "제목", not_null=True),
                Column("content", "TEXT", "본문 (원본에 비어 있으면 NULL)"),
                Column("keyword", "TEXT", "수집 키워드 원문 ('; ' 구분)"),
                Column("media", "TEXT", "매체명"),
                Column("category", "TEXT", "가이드 이슈 카테고리 (수집 키워드에서 변환, '; ' 구분)"),
                Column("url", "TEXT", "원문 링크", not_null=True),
                Column("is_duplicate", "INTEGER", "중복 기사 여부 (대표 기사는 0)", not_null=True, allowed=BOOL, default="0"),
                Column("dup_group_id", "TEXT", "같은 기사 묶음의 대표 news_id"),
            ),
            primary_key=("news_id",),
        ),
        Table(
            name="news_tag",
            owner="김한승",
            columns=(
                Column("news_id", "TEXT", "기사", not_null=True),
                Column("tag_type", "TEXT", "태그 종류", not_null=True, allowed=TAG_TYPES),
                Column("tag", "TEXT", "기술·기업 태그", not_null=True, allowed=TECH_TAGS + COMPANY_TAGS),
                Column("relevance", "TEXT", "관련도 등급", not_null=True, allowed=RELEVANCE_LEVELS),
                Column("in_title", "INTEGER", "제목 포함 여부", not_null=True, allowed=BOOL),
                Column("body_count", "INTEGER", "본문 언급 횟수", not_null=True),
                Column("rule_version", "TEXT", "태깅 규칙 버전", not_null=True),
            ),
            primary_key=("news_id", "tag_type", "tag"),
            foreign_keys=(("news_id", "news", "news_id"),),
        ),
        Table(
            name="news_analysis",
            owner="김한승",
            columns=(
                Column("news_id", "TEXT", "기사", not_null=True),
                Column("prompt_version", "TEXT", "프롬프트 버전", not_null=True),
                Column("sentiment_skh", "TEXT", "SK하이닉스 관점 감성", not_null=True, allowed=SENTIMENT_LABELS),
                Column("sentiment_sec", "TEXT", "삼성전자 관점 감성", not_null=True, allowed=SENTIMENT_LABELS),
                Column("issue_keywords", "TEXT", "핵심 이슈 키워드 (JSON 배열 문자열)"),
                Column("model", "TEXT", "LLM 모델명", not_null=True),
            ),
            primary_key=("news_id", "prompt_version"),
            foreign_keys=(("news_id", "news", "news_id"),),
        ),
        Table(
            name="issues",
            owner="김한승",
            columns=(
                Column("issue_id", "TEXT", "급증 구간 ID (예: HBM-2024-12)", not_null=True),
                Column("tech_tag", "TEXT", "기술 태그", not_null=True, allowed=TECH_TAGS),
                Column("start_date", "DATE", "구간 첫 달의 1일", not_null=True),
                Column("end_date", "DATE", "구간 마지막 달의 말일", not_null=True),
                Column("peak_date", "DATE", "비중 최고 달의 1일", not_null=True),
                Column("peak_share", "REAL", "구간 내 최대 월별 비중 (0~1)", not_null=True),
                Column("baseline_share", "REAL", "직전 6개월 평균 비중 (0~1)"),
                Column("article_count", "INTEGER", "구간 내 관련 기사 수 (중복 제외)", not_null=True),
                Column("method", "TEXT", "탐지 기준·버전 (예: rolling6m_2sigma_v1)", not_null=True),
                Column("summary", "TEXT", "사건 요약 (검토 후 작성)"),
            ),
            primary_key=("issue_id",),
        ),
        Table(
            name="disclosure",
            owner="한도윤",
            columns=(
                Column("rcept_no", "TEXT", "접수번호", not_null=True),
                Column("corp_code", "TEXT", "DART 고유번호"),
                Column("corp_name", "TEXT", "기업명"),
                Column("report_nm", "TEXT", "공시명"),
                Column("rcept_dt", "DATE", "제출일"),
                Column("pblntf_ty", "TEXT", "공시 유형"),
                Column("url", "TEXT", "원문 링크"),
                Column("text", "TEXT", "추출 본문"),
            ),
            primary_key=("rcept_no",),
        ),
        Table(
            name="issue_evidence",
            owner="공동",
            columns=(
                Column("evidence_id", "INTEGER", "자동 증가 ID", not_null=True),
                Column("issue_id", "TEXT", "급증 구간", not_null=True),
                Column("news_id", "TEXT", "근거 기사"),
                Column("rcept_no", "TEXT", "근거 공시"),
                Column("match_type", "TEXT", "연결 방식", not_null=True, allowed=MATCH_TYPES),
                Column("verified", "INTEGER", "사람이 확인했는지 여부", not_null=True, allowed=BOOL, default="0"),
                Column("note", "TEXT", "확인 메모"),
            ),
            primary_key=("evidence_id",),
            foreign_keys=(
                ("issue_id", "issues", "issue_id"),
                ("news_id", "news", "news_id"),
                ("rcept_no", "disclosure", "rcept_no"),
            ),
        ),
    )
}


def _sql_literal(value) -> str:
    """CHECK 제약에 넣을 값을 SQL 리터럴로 바꾼다 (문자열은 작은따옴표로 감싼다)."""
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return str(value)


def create_table_sql(table: Table) -> str:
    """Table 정의 하나를 CREATE TABLE IF NOT EXISTS 문으로 만든다."""
    lines = []
    for col in table.columns:
        parts = [col.name, SQL_TYPES[col.type]]
        if col.not_null:
            parts.append("NOT NULL")
        if col.default is not None:
            parts.append(f"DEFAULT {col.default}")
        if col.allowed:
            values = ", ".join(_sql_literal(v) for v in col.allowed)
            parts.append(f"CHECK ({col.name} IN ({values}))")
        lines.append(" ".join(parts))
    lines.append(f"PRIMARY KEY ({', '.join(table.primary_key)})")
    for column, ref_table, ref_column in table.foreign_keys:
        lines.append(f"FOREIGN KEY ({column}) REFERENCES {ref_table} ({ref_column})")
    body = ",\n    ".join(lines)
    return f"CREATE TABLE IF NOT EXISTS {table.name} (\n    {body}\n)"


def ddl_statements() -> list[str]:
    """모든 테이블의 CREATE 문을 정의 순서대로 돌려준다 (참조되는 테이블이 먼저 온다)."""
    return [create_table_sql(t) for t in TABLES.values()]


def create_all(conn: sqlite3.Connection) -> None:
    """연결된 DB에 모든 테이블을 만든다. 이미 있으면 건너뛴다.

    FK 제약을 쓰려면 연결마다 PRAGMA foreign_keys = ON 이 필요하다 (db.py 연결 함수에서 켠다).
    """
    with conn:
        for statement in ddl_statements():
            conn.execute(statement)


if __name__ == "__main__":
    print(";\n\n".join(ddl_statements()) + ";")
