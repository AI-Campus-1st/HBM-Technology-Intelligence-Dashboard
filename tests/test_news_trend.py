"""
뉴스 추이 집계(src/eda/news_trend.py) 테스트. 작은 표로 확인한다.

담당: 김한승 (이슈 분석)
일정: Day 3
"""

from datetime import date

import pandas as pd
import pytest

from src.eda import news_trend as nt

START, END = date(2024, 1, 15), date(2024, 3, 10)  # 첫 달·마지막 달이 일부 기간


def articles(rows):
    cols = ["news_id", "published_at", "category", "hbm", "skh", "sec"]
    return nt.prepare(pd.DataFrame(rows, columns=cols))


@pytest.fixture
def arts():
    return articles([
        ("a", "2024-01-20", "기술 및 트렌드", "핵심", "핵심", None),
        ("b", "2024-01-25", "규제 및 정책; 공급망 및 인프라", "언급", None, "언급"),
        ("c", "2024-03-01", "기술 및 트렌드", "관련", "언급", "관련"),
        ("d", "2024-03-02", "규제 및 정책", None, None, None),
    ])


def test_monthly_hbm_includes_zero_months_and_partial_flags(arts):
    m = nt.monthly_hbm(arts, START, END).set_index("month")
    assert list(m.index) == ["2024-01", "2024-02", "2024-03"]
    assert m.loc["2024-02", "total"] == 0 and m.loc["2024-02", "share"] == 0  # 0건 달도 0으로
    assert m.loc["2024-01", "hbm"] == 1 and m.loc["2024-01", "share"] == pytest.approx(0.5)  # '언급'은 제외
    assert m.loc["2024-03", "hbm_core"] == 0 and m.loc["2024-03", "share_core"] == 0
    assert m["partial"].tolist() == [True, False, True]


def test_monthly_volume_counts_each_category(arts):
    v = nt.monthly_volume(arts, START, END).set_index("month")
    assert v.loc["2024-01", "total"] == 2
    assert v.loc["2024-01", "규제 및 정책"] == 1 and v.loc["2024-01", "공급망 및 인프라"] == 1


def test_company_monthly_counts_only_core_related_inside_hbm_articles(arts):
    c = nt.company_monthly(arts, START, END).set_index("month")
    assert c.loc["2024-01", "skh"] == 1 and c.loc["2024-01", "sec"] == 0  # b는 HBM '언급'이라 제외
    assert c.loc["2024-03", "skh"] == 0 and c.loc["2024-03", "sec"] == 1  # SK '언급'은 제외
    assert c.loc["2024-03", "sec_share"] == pytest.approx(1.0)


def test_category_relevance(arts):
    r = nt.category_relevance(arts).set_index("category")
    assert r.loc["기술 및 트렌드", "total"] == 2 and r.loc["기술 및 트렌드", "hbm"] == 2
    assert r.loc["규제 및 정책", "unrelated_share"] == pytest.approx(1.0)


def test_load_articles_excludes_duplicates(tmp_path):
    from src.common import db

    path = db.init_db(tmp_path / "t.db")
    conn = db.connect(path)
    db.write_table(conn, "news", [
        {"news_id": "a", "published_at": "2024-01-20", "title": "t", "url": "u1", "category": "기술 및 트렌드",
         "is_duplicate": 0, "dup_group_id": None},
        {"news_id": "b", "published_at": "2024-01-20", "title": "t", "url": "u2", "category": "기술 및 트렌드",
         "is_duplicate": 1, "dup_group_id": "a"},
    ])
    db.write_table(conn, "news_tag", [
        {"news_id": "a", "tag_type": "tech", "tag": "HBM", "relevance": "핵심", "in_title": 1, "body_count": 0, "rule_version": "v"},
        {"news_id": "b", "tag_type": "tech", "tag": "HBM", "relevance": "핵심", "in_title": 1, "body_count": 0, "rule_version": "v"},
    ])
    conn.close()
    out = nt.load_articles(path)
    assert list(out["news_id"]) == ["a"] and out.loc[0, "hbm"] == "핵심"
