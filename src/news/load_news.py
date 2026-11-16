"""
제공 뉴스 원본(config.NEWS_CSV)을 읽어 통합 스키마의 news 테이블에 적재한다.

흐름: CSV 읽기 → transform()으로 컬럼 변환·정리 → db.write_table(mode="replace")로 저장
- news_id: 원문 URL의 SHA-1 앞 16자리 (URL이 기사마다 고유함을 Day 1에 확인)
- published_at: 발행 시각을 버리고 'YYYY-MM-DD'만 저장 (schema.md 공통 규칙)
- content: 본문이 비었거나 공백뿐이면 NULL
- category: 수집 키워드를 가이드의 이슈 카테고리로 바꾸고, 키워드 순서와 관계없이 정해진 순서로 저장
  (키워드 순서대로 붙이면 같은 조합이 두 가지로 저장돼 GROUP BY가 갈라지는 문제가 있었다)
- is_duplicate·dup_group_id: Day 3 preprocess.py가 채운다. 적재 시점에는 0·NULL

다시 실행해도 결과가 같다(replace). 단, news_tag 등 news를 참조하는 행이 이미 있으면
news를 비울 수 없어 멈춘다. 이때는 `python -m src.common.db --rebuild` 후 실행 순서대로 다시 적재한다.

실행: python -m src.news.load_news

담당: 김한승 (이슈 분석)
일정: Day 2
"""

import hashlib
import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

from src.common import schema

# 가이드 §2-3 반도체 키워드 → 이슈 카테고리. ('시장 및 경쟁' 키워드는 반도체 묶음에 없다)
KEYWORD_CATEGORY = {
    "반도체 수출 통제": "규제 및 정책",
    "반도체 세제 혜택": "규제 및 정책",
    "반도체 R&D": "기술 및 트렌드",
    "반도체 밸류체인": "공급망 및 인프라",
    "반도체 원자재": "공급망 및 인프라",
}
# 여러 카테고리를 한 칸에 저장할 때의 순서 (가이드 카테고리 표 순서)
CATEGORY_ORDER = ("규제 및 정책", "기술 및 트렌드", "시장 및 경쟁", "공급망 및 인프라")
SEPARATOR = "; "

# 원본 CSV 컬럼 → news 테이블 컬럼
SOURCE_COLUMNS = {"제목": "title", "본문전문": "content", "원문URL": "url", "발행일": "published_at",
                  "매체명": "media", "수집키워드": "keyword"}


def make_news_id(url: str) -> str:
    """원문 URL로 기사 ID를 만든다. 같은 URL이면 언제 실행해도 같은 ID가 나온다."""
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def to_category(keyword: str) -> str:
    """수집 키워드 문자열('; ' 구분)을 정해진 순서의 카테고리 문자열로 바꾼다.

    Raises:
        ValueError: 매핑에 없는 키워드가 있을 때 (새 키워드를 조용히 버리지 않기 위해)
    """
    parts = [k.strip() for k in str(keyword).split(";") if k.strip()]
    unknown = [k for k in parts if k not in KEYWORD_CATEGORY]
    if unknown:
        raise ValueError(f"카테고리 매핑에 없는 수집 키워드: {unknown}")
    found = {KEYWORD_CATEGORY[k] for k in parts}
    return SEPARATOR.join(c for c in CATEGORY_ORDER if c in found)


def _clean_text(value) -> Optional[str]:
    """결측(None·NaN)이나 공백뿐인 문자열을 None으로 바꾼다."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def transform(raw: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """원본 DataFrame을 news 테이블 컬럼 순서의 DataFrame으로 바꾼다. 분석 기간 밖 기사는 뺀다.

    Raises:
        ValueError: URL이 중복되거나(같은 news_id) 발행일을 읽을 수 없을 때
    """
    df = raw[list(SOURCE_COLUMNS)].rename(columns=SOURCE_COLUMNS)

    published = pd.to_datetime(df["published_at"], errors="coerce")
    if published.isna().any():
        raise ValueError(f"발행일을 읽을 수 없는 행이 {int(published.isna().sum())}건 있습니다.")
    in_period = (published.dt.date >= start) & (published.dt.date <= end)
    df, published = df[in_period].copy(), published[in_period]

    if df["url"].duplicated().any():
        raise ValueError(f"원문 URL이 중복된 행이 {int(df['url'].duplicated().sum())}건 있습니다.")

    df["news_id"] = df["url"].map(make_news_id)
    df["published_at"] = published.dt.strftime("%Y-%m-%d")
    df["content"] = df["content"].map(_clean_text)
    df["category"] = df["keyword"].map(to_category)
    df["is_duplicate"] = 0
    df["dup_group_id"] = None

    columns = [c.name for c in schema.TABLES["news"].columns]
    return df[columns].reset_index(drop=True)


def load(csv_path: Path, conn: sqlite3.Connection, start: date, end: date) -> dict:
    """CSV를 읽어 news 테이블을 다시 채우고 적재 통계를 돌려준다.

    Returns:
        {"source_rows", "rows", "out_of_period", "missing_content", "by_category"}
    """
    from src.common import db  # 순환 임포트를 피하려고 함수 안에서 불러온다

    raw = pd.read_csv(csv_path, encoding="utf-8-sig")
    news = transform(raw, start, end)
    try:
        db.write_table(conn, "news", news, mode="replace")
    except sqlite3.IntegrityError as e:
        raise RuntimeError(
            "news를 참조하는 행(news_tag 등)이 있어 news를 다시 채울 수 없습니다. "
            "`python -m src.common.db --rebuild` 후 실행 순서대로 다시 적재하세요."
        ) from e

    by_category = Counter(c for value in news["category"] for c in value.split(SEPARATOR))
    return {
        "source_rows": len(raw),
        "rows": len(news),
        "out_of_period": len(raw) - len(news),
        "missing_content": int(news["content"].isna().sum()),
        "by_category": dict(by_category),
    }


def main() -> None:
    from src.common import config, db

    db.init_db()
    conn = db.connect()
    try:
        stats = load(config.NEWS_CSV, conn, config.ANALYSIS_START, config.ANALYSIS_END)
    finally:
        conn.close()
    print(f"원본 {stats['source_rows']:,}건 → news {stats['rows']:,}건 적재 (기간 밖 {stats['out_of_period']}건 제외)")
    print(f"본문 결측: {stats['missing_content']}건 ({stats['missing_content'] / max(stats['rows'], 1):.2%})")
    for name in CATEGORY_ORDER:
        if name in stats["by_category"]:
            print(f"  {name}: {stats['by_category'][name]:,}건 (복수 카테고리 기사는 각각 셈)")


if __name__ == "__main__":
    main()
