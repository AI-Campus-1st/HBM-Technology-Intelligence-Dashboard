"""
공시 건수 추이(src/eda/disclosure_trend.py) 테스트. DB 없이 작은 표로 확인한다.

담당: 한도윤 (공시 분석)
일정: Day 3
"""

from datetime import date

import pandas as pd
import pytest

from src.common import db
from src.eda import disclosure_trend as t


def make(rows):
    cols = ["rcept_no", "corp_name", "report_nm", "rcept_dt", "pblntf_ty"]
    df = pd.DataFrame(rows, columns=cols)
    df["url"] = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=" + df["rcept_no"]
    return t.prepare(df)


@pytest.fixture
def df():
    return make([
        ("1", "SK하이닉스", "신규시설투자등", "2024-04-24", "I"),
        ("2", "SK하이닉스", "연결재무제표기준영업(잠정)실적(공정공시)", "2024-04-25", "I"),
        ("3", "SK하이닉스", "분기보고서 (2024.03)", "2024-05-14", "A"),
        ("4", "삼성전자", "[기재정정]현금ㆍ현물배당결정", "2024-04-30", "I"),
        ("5", "삼성전자", "동일인등출자계열회사와의상품ㆍ용역거래", "2024-06-28", "J"),
        ("6", "SK하이닉스", "투자판단관련주요경영사항", "2024-12-20", "I"),
    ])


@pytest.mark.parametrize("name, expected", [
    ("신규시설투자등", "투자·설비"),
    ("투자판단관련주요경영사항", "투자·설비"),
    ("[기재정정]주요사항보고서(영업양수결정)", "투자·설비"),
    ("매출액또는손익구조30%(대규모법인은15%)이상변경", "실적"),
    ("장래사업ㆍ경영계획(공정공시)", "사업계획"),
    ("조회공시요구(풍문또는보도)에대한답변(미확정)", "풍문·해명"),
    ("단일판매ㆍ공급계약체결", "공급계약"),
    ("주요사항보고서(자기주식처분결정)", "자본·주주환원"),
    ("기타경영사항(자율공시) ((배당기준일 변경 안내))", "자본·주주환원"),
    ("의결권대리행사권유참고서류", "지배구조·주총"),
    ("최대주주등소유주식변동신고서", "지분변동"),
    ("반기보고서 (2025.06)", "정기보고서"),
    ("[분기별공시(대표회사용)]동일인등출자계열회사와의상품ㆍ용역거래변경", "공정위 거래"),
    ("기업설명회(IR)개최(안내공시)", "기타"),
])
def test_categorize(name, expected):
    assert t.categorize(name) == expected


def test_clean_name_strips_prefix_tags():
    assert t.clean_name("[기재정정][첨부추가] 사업보고서 (2024.12)") == "사업보고서 (2024.12)"


def test_prepare_adds_period_and_event(df):
    row = df.set_index("rcept_no").loc["1"]
    assert (row["month"], row["quarter"], row["is_event"]) == ("2024-04", "2024Q2", True)
    assert not df.set_index("rcept_no").loc["4", "is_event"]


def test_period_counts_fills_zero_months(df):
    out = t.period_counts(df, "M", "pblntf_ty", start="2024-04-01", end="2024-12-31")
    sk = out[out["corp_name"] == "SK하이닉스"]
    # 기업 2 × 9개월 × df에 나온 유형 3(A, I, J)
    assert len(out) == 2 * 9 * 3
    assert sk.loc[(sk["period"] == "2024-04") & (sk["pblntf_ty"] == "I"), "count"].item() == 2
    assert sk.loc[sk["period"] == "2024-08", "count"].sum() == 0
    assert out["count"].sum() == len(df)


def test_period_counts_total_only(df):
    out = t.period_counts(df, "Q", None, start="2024-04-01", end="2024-12-31")
    assert list(out.columns) == ["corp_name", "period", "count", "partial"]
    assert out.set_index(["corp_name", "period"]).loc[("SK하이닉스", "2024Q2"), "count"] == 3


def test_partial_periods_follow_analysis_window():
    assert t.is_partial("2023-10", date(2023, 10, 19), date(2026, 10, 19))
    assert t.is_partial("2026-10", date(2023, 10, 19), date(2026, 10, 19))
    assert not t.is_partial("2024-01", date(2023, 10, 19), date(2026, 10, 19))
    assert not t.is_partial("2026-09", date(2023, 10, 19), date(2026, 10, 30))


def test_type_distribution_share(df):
    out = t.type_distribution(df).set_index(["corp_name", "pblntf_ty"])
    assert out.loc[("SK하이닉스", "I"), "count"] == 3
    assert out.loc[("SK하이닉스", "I"), "share"] == 0.75
    assert out.loc[("삼성전자", "J"), "type_name"] == "공정위공시"


def test_category_counts_order_and_total(df):
    out = t.category_counts(df)
    assert out["category"].tolist() == ["투자·설비", "실적", "자본·주주환원", "정기보고서", "공정위 거래"]
    assert out["합계"].sum() == len(df)
    assert out.set_index("category").loc["투자·설비", "is_event"]


def test_event_timeline_sorted_with_source(df):
    out = t.event_timeline(df)
    assert out["rcept_no"].tolist() == ["1", "2", "6"]
    assert {"report_nm", "rcept_dt", "url"} <= set(out.columns)


def test_main_writes_outputs(tmp_path, monkeypatch, df):
    db_path = tmp_path / "hbm.db"
    db.init_db(db_path)
    conn = db.connect(db_path)
    try:
        db.write_table(conn, "disclosure", df[["rcept_no", "corp_name", "report_nm", "rcept_dt", "pblntf_ty", "url"]]
                       .assign(corp_code="00164779"), mode="replace")
    finally:
        conn.close()
    for name in ("MONTHLY_PATH", "TYPE_DIST_PATH", "CATEGORY_PATH", "TIMELINE_PATH"):
        monkeypatch.setattr(t, name, tmp_path / f"{name}.csv")
    monkeypatch.setattr(t, "REPORTS_DIR", tmp_path)
    out = t.main(db_path, save_figure=False)
    assert out["monthly"]["count"].sum() == len(df)
    assert (tmp_path / "TIMELINE_PATH.csv").exists()


def test_figure_monthly_builds(df):
    pytest.importorskip("plotly")
    fig = t.figure_monthly(df, start="2024-04-01", end="2024-12-31")
    assert len(fig.data) > 0
