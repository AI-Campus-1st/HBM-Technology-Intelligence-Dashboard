"""
뉴스 SQL 집계 쿼리(sql/01~03_*.sql, src/eda/news_sql_report.py) 테스트.
작은 임시 DB에 기사·태그·급증 구간을 넣고, 같은 정의의 Python 집계(news_trend)와 결과를 대조한다.

담당: 김한승 (이슈 분석)
일정: Day 3
"""

import pandas as pd
import pytest

from src.common import config, db
from src.eda import news_sql_report as nsr
from src.eda import news_trend as nt
from src.llm import prompts

Q1 = nsr.SQL_DIR / "01_news_monthly_dedup.sql"
Q2 = nsr.SQL_DIR / "02_hbm_monthly_share.sql"
Q3 = nsr.SQL_DIR / "03_issue_company_coverage.sql"
Q4 = nsr.SQL_DIR / "04_company_sentiment_monthly.sql"

# (news_id, published_at, is_duplicate, HBM 관련도, SK 관련도, 삼성 관련도)
ROWS = [
    ("a", "2024-01-05", 0, "핵심", "핵심", None),
    ("b", "2024-01-06", 1, "핵심", "핵심", None),      # 중복 → 모든 집계에서 제외
    ("c", "2024-01-20", 0, "언급", None, "언급"),      # HBM '언급' → HBM 기사 아님
    ("d", "2024-01-25", 0, None, None, None),
    ("e", "2024-03-02", 0, "관련", "언급", "관련"),    # SK '언급'은 기업 집계 제외
    ("f", "2024-03-15", 0, "핵심", "관련", "핵심"),    # 두 기업 모두
    ("g", "2024-03-20", 0, None, None, None),
    ("h", "2024-05-10", 0, "관련", None, None),        # 기업 태그 없음
]
ISSUES = [("HBM-2024-03", "2024-03-01", "2024-03-31", 2)]


@pytest.fixture
def conn(tmp_path):
    conn = db.connect(db.init_db(tmp_path / "t.db"))
    news = pd.DataFrame([{"news_id": i, "published_at": d, "title": i, "url": i, "is_duplicate": dup,
                          "dup_group_id": None} for i, d, dup, *_ in ROWS])
    db.write_table(conn, "news", news, mode="append")
    tags = []
    for i, _, _, hbm, skh, sec in ROWS:
        for tag_type, tag, rel in (("tech", "HBM", hbm), ("company", "SK하이닉스", skh), ("company", "삼성전자", sec)):
            if rel:
                tags.append({"news_id": i, "tag_type": tag_type, "tag": tag, "relevance": rel,
                             "in_title": int(rel == "핵심"), "body_count": 1, "rule_version": "test"})
    db.write_table(conn, "news_tag", pd.DataFrame(tags), mode="append")
    db.write_table(conn, "issues", pd.DataFrame([
        {"issue_id": iid, "tech_tag": "HBM", "start_date": s, "end_date": e, "peak_date": s,
         "peak_share": 0.5, "baseline_share": 0.1, "article_count": n, "method": "test", "summary": None}
        for iid, s, e, n in ISSUES]), mode="append")
    yield conn
    conn.close()


def python_articles():
    """SQL과 같은 입력을 news_trend 형식(중복 제외, 기사 1행)으로."""
    rows = [(i, d, None, hbm, skh, sec) for i, d, dup, hbm, skh, sec in ROWS if dup == 0]
    return nt.prepare(pd.DataFrame(rows, columns=["news_id", "published_at", "category", "hbm", "skh", "sec"]))


def test_query_files_are_news_queries_only():
    names = [p.name for p in nsr.query_files()]
    assert names == [Q1.name, Q2.name, Q3.name, Q4.name]


@pytest.mark.parametrize("path", [Q1, Q2, Q4])
def test_sql_period_matches_config(path):
    text = path.read_text(encoding="utf-8")
    assert f"'{config.ANALYSIS_START.isoformat()}', '{config.ANALYSIS_END.isoformat()}'" in text


def test_01_monthly_dedup(conn):
    out = nsr.run_query(conn, Q1).set_index("month")
    assert out.index[0] == "2023-10" and out.index[-1] == "2026-10"  # 분석 기간 전체 월 축
    assert out.loc["2024-01", "raw_articles"] == 4 and out.loc["2024-01", "duplicates"] == 1
    assert out.loc["2024-01", "articles"] == 3 and out.loc["2024-01", "dup_rate"] == pytest.approx(0.25)
    assert out.loc["2024-02", "raw_articles"] == 0 and pd.isna(out.loc["2024-02", "dup_rate"])  # 0건 달
    assert out.loc["2023-10", "partial"] == 1 and out.loc["2026-10", "partial"] == 1
    assert out.loc["2024-01", "partial"] == 0
    assert out["articles"].sum() == 7


def test_02_matches_python_monthly_hbm(conn):
    out = nsr.run_query(conn, Q2).set_index("month")
    py = nt.monthly_hbm(python_articles()).set_index("month")
    assert list(out.index) == list(py.index)
    for col in ("total", "hbm", "hbm_core"):
        assert out[col].tolist() == py[col].tolist(), col
    assert out["share"].tolist() == pytest.approx(py["share"].tolist())
    assert out["share_core"].tolist() == pytest.approx(py["share_core"].tolist())
    assert out["partial"].astype(bool).tolist() == py["partial"].tolist()


def test_02_window_columns(conn):
    out = nsr.run_query(conn, Q2).set_index("month")
    assert out.loc["2024-01", "share"] == pytest.approx(1 / 3)
    assert out.loc["2024-02", "share_change"] == pytest.approx(-1 / 3)   # LAG
    assert out.loc["2024-03", "share_ma3"] == pytest.approx((1 / 3 + 0 + 2 / 3) / 3)
    assert out.loc["2024-05", "share_rank"] == 1  # h 1건뿐인 달 = 비중 1.0
    assert out.loc["2024-03", "share_rank"] == 2
    assert pd.isna(out.loc["2023-10", "share_rank"])  # 부분 월은 순위에서 제외


def test_03_issue_company_coverage(conn):
    out = nsr.run_query(conn, Q3).set_index("period")
    issue = out.loc["HBM-2024-03"]
    assert issue["is_issue"] == 1 and issue["hbm_articles"] == ISSUES[0][3]  # issues.article_count와 일치
    assert issue["skh_articles"] == 1 and issue["sec_articles"] == 2 and issue["both_articles"] == 1
    assert issue["skh_share"] == pytest.approx(0.5) and issue["sec_share"] == pytest.approx(1.0)
    outside = out.loc[nsr.OUTSIDE_LABEL]
    assert outside["is_issue"] == 0 and outside["hbm_articles"] == 2  # a, h
    assert outside["neither_articles"] == 1
    # 전체 합계가 Python 기업 집계와 같다
    py = nt.company_monthly(python_articles())
    assert out["hbm_articles"].sum() == py["hbm"].sum()
    assert out["skh_articles"].sum() == py["skh"].sum() and out["sec_articles"].sum() == py["sec"].sum()


def test_main_writes_csv(conn, tmp_path):
    db_path = tmp_path / "t.db"
    results = nsr.main(db_path=db_path, reports_dir=tmp_path / "reports")
    assert set(results) == {Q1.stem, Q2.stem, Q3.stem, Q4.stem}
    assert (tmp_path / "reports" / f"sql{Q2.stem}.csv").exists()


def add_analysis(conn, rows, version=prompts.PROMPT_VERSION):
    db.write_table(conn, "news_analysis", pd.DataFrame([
        {"news_id": i, "prompt_version": version, "sentiment_skh": skh, "sentiment_sec": sec,
         "issue_keywords": "[]", "model": "m"} for i, skh, sec in rows]), mode="append")


def test_04_prompt_version_matches_code():
    assert f"'{prompts.PROMPT_VERSION}'" in Q4.read_text(encoding="utf-8")


def test_04_company_sentiment_monthly(conn):
    add_analysis(conn, [("a", "긍정", "해당없음"), ("b", "부정", "부정"),   # b는 중복 기사 → 제외
                        ("e", "부정", "긍정"), ("f", "긍정", "부정"), ("h", "해당없음", "해당없음")])
    add_analysis(conn, [("a", "부정", "부정")], version="other")             # 다른 버전 → 제외
    out = nsr.run_query(conn, Q4).set_index(["month", "company"])
    assert len(out) == 37 * 2  # 분석 기간 전체 월 × 두 기업 (0건 달 포함)
    jan_skh, jan_sec = out.loc[("2024-01", "SK하이닉스")], out.loc[("2024-01", "삼성전자")]
    assert (jan_skh["articles"], jan_skh["positive"], jan_skh["negative"]) == (1, 1, 0)
    assert jan_skh["net_sentiment"] == pytest.approx(1.0)
    assert jan_sec["articles"] == 0 and pd.isna(jan_sec["net_sentiment"])  # 해당없음은 등장 기사에서 뺀다
    mar_skh = out.loc[("2024-03", "SK하이닉스")]
    assert (mar_skh["articles"], mar_skh["positive"], mar_skh["negative"], mar_skh["neutral"]) == (2, 1, 1, 0)
    assert mar_skh["net_sentiment"] == pytest.approx(0.0)
    assert mar_skh["net_ma3"] == pytest.approx((2 - 1) / 3)  # 2024-01~03 합계 기준 (긍정 2, 부정 1, 기사 3)
    assert mar_skh["is_issue_month"] == 1 and jan_skh["is_issue_month"] == 0
    assert out.loc[("2024-05", "SK하이닉스"), "articles"] == 0  # h는 두 기업 모두 해당없음
