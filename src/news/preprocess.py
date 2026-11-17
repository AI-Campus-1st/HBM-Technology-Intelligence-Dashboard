"""
뉴스 전처리: 본문 정제 함수, 제목 중복(재배포) 표시, 기술·기업 태그(news_tag) 적재.

흐름 (python -m src.news.preprocess, load_news 다음에 실행):
    1) news 읽기
    2) mark_duplicates(): 정규화한 제목이 같고 발행일이 DUP_WINDOW_DAYS일 안이면 같은 기사(재배포)로 보고
       가장 이른 기사를 대표(is_duplicate=0)로, 나머지를 is_duplicate=1로 표시한다. dup_group_id = 대표 news_id
    3) news의 is_duplicate·dup_group_id만 UPDATE (원문 컬럼은 건드리지 않는다)
    4) clean_text()한 본문으로 tagging.tag_article()을 돌려 news_tag를 다시 채운다 (replace)

설계 판단:
- 정제한 본문은 저장하지 않는다 (2026-11-17 결정). 원문은 news.content에 그대로 두고,
  태깅·LLM 입력처럼 필요한 곳에서 clean_text()를 부른다. 스키마 변경 없이 원문을 보존하기 위해서다.
- 중복 판단에 시간 창을 둔다. '[연합뉴스 이 시각 헤드라인] - 18:00'처럼 같은 제목이 수백 일에 걸쳐
  반복되는 정기 기사가 있어, 제목만으로 묶으면 서로 다른 기사가 중복으로 처리된다.
- 중복 기사도 news_tag에는 태그를 남긴다. 분석에서 is_duplicate=0만 고르면 되고,
  나중에 중복 기준을 바꿔도 태그를 다시 만들 필요가 없다.

다시 실행해도 결과가 같다. news_analysis 등 news_tag와 무관한 테이블은 건드리지 않는다.

담당: 김한승 (이슈 분석)
일정: Day 3
"""

import re
import sqlite3
from datetime import timedelta
from typing import Optional

import pandas as pd

from src.news import tagging

DUP_WINDOW_DAYS = 7  # 대표 기사 발행일로부터 이 기간 안의 같은 제목만 중복으로 본다

# 제목 비교 시 무시할 문자: 공백, 따옴표류, 가운뎃점·말줄임표
_TITLE_IGNORE = re.compile(r"[\s\"'“”‘’`´·ㆍ…]+")
# 본문 끝의 저작권 안내 문장 (예: '무단 전재, 재배포 및 AI학습 이용 금지')
_COPYRIGHT = re.compile(r"[^.。!?]*무단\s*전재[^.。!?]*[.。]?")
_SPACES = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    """중복 비교용 제목. 띄어쓰기·따옴표·가운뎃점 차이를 없앤다 (언론사마다 표기만 다른 재배포 기사 대응)."""
    return _TITLE_IGNORE.sub("", str(title))


def clean_text(text) -> Optional[str]:
    """본문 정제: 저작권 안내 문장 제거, 줄바꿈·연속 공백을 한 칸으로. 비어 있으면 None."""
    if not isinstance(text, str):
        return None
    cleaned = _SPACES.sub(" ", _COPYRIGHT.sub(" ", text)).strip()
    return cleaned or None


def mark_duplicates(news: pd.DataFrame, window_days: int = DUP_WINDOW_DAYS) -> pd.DataFrame:
    """제목 중복(재배포) 표시.

    Args:
        news: news_id, published_at('YYYY-MM-DD'), title 컬럼을 가진 DataFrame
        window_days: 대표 기사 발행일로부터 며칠 안의 같은 제목을 중복으로 볼지

    Returns:
        news_id, is_duplicate(0/1), dup_group_id(대표 news_id, 묶음이 없으면 None) DataFrame.
        묶음 안에서는 발행일이 가장 이르고(같으면 news_id가 작은) 기사가 대표다.
    """
    df = news[["news_id", "published_at", "title"]].copy()
    df["key"] = df["title"].map(normalize_title)
    df["date"] = pd.to_datetime(df["published_at"])
    df = df.sort_values(["key", "date", "news_id"])

    rep_of = {}
    for _, group in df.groupby("key", sort=False):
        rep_id, rep_date = None, None
        for row in group.itertuples(index=False):
            if rep_id is None or row.date - rep_date > timedelta(days=window_days):
                rep_id, rep_date = row.news_id, row.date  # 새 묶음 시작
            rep_of[row.news_id] = rep_id

    out = pd.DataFrame({"news_id": list(rep_of), "rep": list(rep_of.values())})
    size = out["rep"].map(out["rep"].value_counts())
    out["is_duplicate"] = (out["news_id"] != out["rep"]).astype(int)
    out["dup_group_id"] = out["rep"].where(size > 1, None)
    return out[["news_id", "is_duplicate", "dup_group_id"]]


def build_tags(news: pd.DataFrame) -> pd.DataFrame:
    """정제한 본문으로 news_tag 행을 만든다."""
    rows = [
        row
        for n in news.itertuples(index=False)
        for row in tagging.tag_article(n.news_id, n.title, clean_text(n.content))
    ]
    columns = ["news_id", "tag_type", "tag", "relevance", "in_title", "body_count", "rule_version"]
    return pd.DataFrame(rows, columns=columns)


def run(conn: sqlite3.Connection) -> dict:
    """중복 표시와 news_tag 적재를 실행하고 통계를 돌려준다.

    Returns:
        {"news", "dup_groups", "duplicates", "tag_rows", "tagged_news", "hbm"(중복 제외 HBM 등급별 건수), "rule_version"}
    """
    from src.common import db

    news = db.read_table(conn, "news", columns=["news_id", "published_at", "title", "content"])
    dups = mark_duplicates(news)

    with conn:  # news 중복 표시: 전부 초기화 후 다시 표시 (한 트랜잭션)
        conn.execute("UPDATE news SET is_duplicate = 0, dup_group_id = NULL")
        marked = dups[dups["dup_group_id"].notna()]
        conn.executemany(
            "UPDATE news SET is_duplicate = ?, dup_group_id = ? WHERE news_id = ?",
            marked[["is_duplicate", "dup_group_id", "news_id"]].itertuples(index=False, name=None),
        )

    tags = build_tags(news)
    db.write_table(conn, "news_tag", tags, mode="replace")

    unique_ids = set(dups.loc[dups["is_duplicate"] == 0, "news_id"])
    hbm = tags[(tags["tag"] == "HBM") & tags["news_id"].isin(unique_ids)]["relevance"].value_counts()
    return {
        "news": len(news),
        "dup_groups": int(dups["dup_group_id"].dropna().nunique()),
        "duplicates": int(dups["is_duplicate"].sum()),
        "tag_rows": len(tags),
        "tagged_news": int(tags["news_id"].nunique()),
        "hbm": {level: int(hbm.get(level, 0)) for level in ("핵심", "관련", "언급")},
        "rule_version": tagging.RULE_VERSION,
    }


def main() -> None:
    from src.common import db

    conn = db.connect()
    try:
        stats = run(conn)
    finally:
        conn.close()
    print(f"news {stats['news']:,}건 — 중복 묶음 {stats['dup_groups']}개, 중복 표시 {stats['duplicates']}건 "
          f"(같은 제목·{DUP_WINDOW_DAYS}일 이내)")
    print(f"news_tag {stats['tag_rows']:,}행 ({stats['tagged_news']:,}건, {stats['rule_version']})")
    print("HBM (중복 제외): " + " / ".join(f"{k} {v}" for k, v in stats["hbm"].items()))


if __name__ == "__main__":
    main()
