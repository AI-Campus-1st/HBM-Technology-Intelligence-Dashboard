"""
공시 SQL 집계 쿼리(sql/05_*.sql, src/dart/sql_report.py) 테스트. 작은 임시 DB로 확인한다.

담당: 한도윤 (공시 분석)
일정: Day 3
"""

import pandas as pd
import pytest

from src.common import db
from src.dart import sql_report
from src.eda import disclosure_trend

Q1 = sql_report.SQL_DIR / "05_1_disclosure_events_vs_hbm_news.sql"
Q2 = sql_report.SQL_DIR / "05_2_disclosure_category_yoy.sql"

# 공시 성격 규칙마다 한 건 이상 (실제 공시명). [기재정정] 꼬리표가 있어도 같은 성격이어야 한다.
NAMES = [
    "신규시설투자등", "투자판단관련주요경영사항", "주요사항보고서(유형자산취득결정)", "[기재정정]신규시설투자등",
    "연결재무제표기준영업(잠정)실적(공정공시)", "매출액또는손익구조30%(대규모법인은15%)이상변경",
    "[기재정정]장래사업ㆍ경영계획(공정공시)", "기업가치제고계획(자율공시)",
    "조회공시요구(풍문또는보도)에대한답변(미확정)", "풍문또는보도에대한해명(미확정)",
    "단일판매ㆍ공급계약체결",
    "주요사항보고서(자기주식처분결정)", "현금ㆍ현물배당결정", "주주명부폐쇄기간또는기준일설정",
    "주주총회소집공고", "대표이사(대표집행임원)변경(안내공시)", "의결권대리행사권유참고서류",
    "최대주주등소유주식변동신고서",
    "사업보고서 (2024.12)", "분기보고서 (2025.03)", "감사보고서제출",
    "대규모기업집단현황공시[연1회공시및1/4분기용(대표회사용)]", "특수관계인과의내부거래",
    "기타경영사항(자율공시)", "기업설명회(IR)개최(안내공시)",
]


@pytest.fixture
def conn(tmp_path):
    conn = db.connect(db.init_db(tmp_path / "t.db"))
    yield conn
    conn.close()


def add_disclosures(conn, rows):
    """rows: (rcept_no, corp_name, report_nm, rcept_dt[, text_status, rag_target])"""
    full = [(r + ("대기", 0))[:6] for r in rows]
    db.write_table(conn, "disclosure", pd.DataFrame([
        {"rcept_no": no, "corp_code": "00164779", "corp_name": corp, "report_nm": nm, "rcept_dt": dt,
         "pblntf_ty": "I", "url": "u", "text_status": status, "rag_target": rag}
        for no, corp, nm, dt, status, rag in full
    ]), mode="append")


def test_category_case_matches_python_rules(conn):
    add_disclosures(conn, [(str(i), "SK하이닉스", nm, "2025-01-10") for i, nm in enumerate(NAMES)])
    out = sql_report.run_query(conn, Q2)
    got = out[out["period"] == "Y2"].set_index("category")["disclosures"]
    expected = pd.Series([disclosure_trend.categorize(n) for n in NAMES]).value_counts()
    assert got[got > 0].sort_index().to_dict() == expected.sort_index().to_dict()
    events = out[out["is_event"] == 1]["category"].unique()
    assert set(events) == set(disclosure_trend.EVENT_CATEGORIES)


def test_yoy_uses_twelve_month_periods_and_lag(conn):
    add_disclosures(conn, [
        ("1", "SK하이닉스", "신규시설투자등", "2023-10-19", "확보", 1),   # Y1 첫날
        ("2", "SK하이닉스", "신규시설투자등", "2024-10-19", "확보", 0),   # Y2 첫날
        ("3", "SK하이닉스", "신규시설투자등", "2025-11-01", "확보", 1),
        ("4", "SK하이닉스", "신규시설투자등", "2026-10-19", "대상아님", 0),  # Y3 마지막 날
        ("5", "SK하이닉스", "신규시설투자등", "2026-10-20"),               # 기간 밖
    ])
    out = sql_report.run_query(conn, Q2)
    capex = out[out["category"] == "투자·설비"].set_index("period")
    assert capex["disclosures"].tolist() == [1, 1, 2]
    assert capex["change"].tolist()[1:] == [0, 1] and pd.isna(capex.loc["Y1", "change"])
    assert capex["with_text"].tolist() == [1, 1, 1]
    assert capex["rag_targets"].tolist() == [1, 0, 1]
    assert len(out) == 3 * 11  # 기업 1 × 구간 3 × 성격 11 (0건 포함)


def test_monthly_overlay_fills_months_and_counts_unique_hbm_news(conn):
    add_disclosures(conn, [
        ("1", "SK하이닉스", "신규시설투자등", "2024-04-24"),
        ("2", "SK하이닉스", "현금ㆍ현물배당결정", "2024-04-25"),
        ("3", "삼성전자", "풍문또는보도에대한해명(미확정)", "2024-05-02"),
    ])
    db.write_table(conn, "news", pd.DataFrame([
        {"news_id": nid, "published_at": dt, "title": "t", "url": "u", "is_duplicate": dup}
        for nid, dt, dup in [("a", "2024-04-01", 0), ("b", "2024-04-02", 1), ("c", "2024-04-03", 0), ("d", "2024-04-04", 0)]
    ]), mode="append")
    tag = lambda nid, typ, t, rel: {"news_id": nid, "tag_type": typ, "tag": t, "relevance": rel,  # noqa: E731
                                    "in_title": 1, "body_count": 1, "rule_version": "x"}
    db.write_table(conn, "news_tag", pd.DataFrame([
        tag("a", "tech", "HBM", "핵심"), tag("a", "company", "SK하이닉스", "언급"), tag("a", "company", "삼성전자", "언급"),
        tag("b", "tech", "HBM", "핵심"), tag("b", "company", "SK하이닉스", "핵심"),   # 중복 기사 → 제외
        tag("c", "tech", "HBM", "언급"), tag("c", "company", "SK하이닉스", "핵심"),   # HBM 언급 → 제외
        tag("d", "tech", "DRAM", "핵심"), tag("d", "company", "SK하이닉스", "핵심"),  # HBM 아님 → 제외
    ]), mode="append")

    out = sql_report.run_query(conn, Q1)
    assert len(out) == 37 * 2  # 2023-10 ~ 2026-10 37개월 × 기업 2
    assert out.loc[out["month"].isin(["2023-10", "2026-10"]), "partial"].eq(1).all()
    row = out.set_index(["corp_name", "month"])
    assert row.loc[("SK하이닉스", "2024-04"), ["disclosures", "event_disclosures", "hbm_news"]].tolist() == [2, 1, 1]
    assert row.loc[("SK하이닉스", "2024-04"), "event_categories"] == "투자·설비"
    assert row.loc[("삼성전자", "2024-04"), "hbm_news"] == 1  # 두 기업 태그 기사는 양쪽에 센다
    assert row.loc[("삼성전자", "2024-05"), "event_categories"] == "풍문·해명"
    assert row["hbm_news"].sum() == 2


def test_main_writes_one_csv_per_query(conn, tmp_path):
    add_disclosures(conn, [("1", "SK하이닉스", "신규시설투자등", "2024-04-24")])
    results = sql_report.main(db_path=tmp_path / "t.db", reports_dir=tmp_path / "reports")
    assert set(results) == {Q1.stem, Q2.stem}
    for path in (Q1, Q2):
        assert pd.read_csv(sql_report.output_path(path, tmp_path / "reports")).shape[0] == len(results[path.stem])
