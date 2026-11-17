"""
급증 구간 탐지(src/eda/spike_detection.py) 테스트. 인공 시계열과 임시 DB로 확인한다.

확정 기준(방식 B): 고정 6개월 창, 창 안의 이전 급증 달 제외(대체 없음), 평균 + 2×표본표준편차,
HBM 기사 10건 이상, 일부 기간 달 제외, 기준선이 3개 달 미만이면 판정 안 함.

담당: 공동
일정: Day 3
"""

from datetime import date

import pandas as pd
import pytest

from src.common import db, schema
from src.eda import spike_detection as sd

BASE = [0.02, 0.03, 0.025, 0.02, 0.03, 0.025]  # 6개월 기준선 (평범한 달)


def series(shares, counts=None, partial=None, start="2024-01"):
    months = pd.period_range(start, periods=len(shares), freq="M").astype(str)
    return pd.DataFrame({
        "month": months, "share": shares, "hbm": counts or [20] * len(shares),
        "total": [200] * len(shares), "partial": partial or [False] * len(shares),
    })


# ── 기본 판정 ──

def test_method_id_is_consistent():
    assert sd.METHOD == "rolling6m_2sigma_exclude_spikes_min10_v1"
    assert sd.method_id(exclude_spikes=False) == "rolling6m_2sigma_min10_v1"


def test_detects_month_above_mean_plus_2_sample_std():
    flags = sd.flag_months(series(BASE + [0.20, 0.03]), min_count=0)
    assert flags["is_spike"].tolist() == [False] * 6 + [True, False]
    base = pd.Series(BASE)
    assert flags.loc[6, "threshold"] == pytest.approx(base.mean() + 2 * base.std(ddof=1))  # 표본표준편차


def test_first_months_without_six_month_history_are_not_judged():
    flags = sd.flag_months(series([0.5] + BASE), min_count=0)
    assert flags.loc[0, "status"] == sd.STATUS_NO_HISTORY and pd.isna(flags.loc[0, "threshold"])
    assert flags.loc[5, "status"] == sd.STATUS_NO_HISTORY  # 앞의 6개월이 다 있어야 판정
    assert flags.loc[6, "status"] != sd.STATUS_NO_HISTORY  # 2024-01~06이 모두 있으면 판정 대상


@pytest.mark.parametrize("count, expected", [(9, False), (10, True), (11, True)])
def test_min_count_is_inclusive_at_10(count, expected):
    flags = sd.flag_months(series(BASE + [0.20], counts=[20] * 6 + [count]))  # 기본 min_count=10
    assert bool(flags.loc[6, "is_spike"]) is expected
    if not expected:
        assert flags.loc[6, "status"] == sd.STATUS_LOW_COUNT


def test_partial_months_are_not_judged_and_not_in_baseline():
    shares = [0.9] + BASE + [0.20, 0.25]
    partial = [True] + [False] * 7 + [True]
    flags = sd.flag_months(series(shares, partial=partial), min_count=0)
    assert flags.loc[0, "status"] == sd.STATUS_PARTIAL and flags.loc[8, "status"] == sd.STATUS_PARTIAL
    assert flags.loc[7, "baseline_mean"] == pytest.approx(sum(BASE) / 6)
    assert flags.loc[7, "is_spike"] and not flags.loc[8, "is_spike"]


# ── 방식 B: 이전 급증 달 제외 ──

def test_spike_month_is_excluded_from_next_baseline():
    shares = BASE + [0.40, 0.03, 0.15]
    a = sd.flag_months(series(shares), min_count=0, exclude_spikes=False)
    b = sd.flag_months(series(shares), min_count=0, exclude_spikes=True)
    assert "2024-07" in a.loc[8, "baseline_months"] and not a.loc[8, "is_spike"]  # A: 0.40이 기준선에 들어가 놓침
    assert "2024-07" not in b.loc[8, "baseline_months"] and b.loc[8, "is_spike"]  # B: 빼고 판정


def test_window_is_fixed_six_calendar_months_without_older_replacement():
    # 2024-07, 2024-09 급증 → 2025-01의 창(2024-07~12)에서 두 달을 빼고 4개만 쓴다. 2024-06 이전으로 넓히지 않는다
    shares = BASE + [0.40, 0.03, 0.45, 0.02, 0.03, 0.025, 0.03]
    flags = sd.flag_months(series(shares), min_count=0)
    jan = flags.set_index("month").loc["2025-01"]
    assert jan["baseline_months"] == "2024-08;2024-10;2024-11;2024-12"
    assert jan["baseline_n"] == 4
    assert jan["baseline_mean"] == pytest.approx((0.03 + 0.02 + 0.03 + 0.025) / 4)


def test_insufficient_baseline_when_too_many_spikes_in_window():
    # 창 6개월 중 4개월이 급증이면 남는 2개월 < 3 → 판정하지 않는다 (0이나 오래된 달로 채우지 않는다)
    shares = BASE + [0.40, 0.03, 0.50, 0.60, 0.70, 0.02, 0.90]
    flags = sd.flag_months(series(shares), min_count=0).set_index("month")
    last = flags.loc["2025-01"]
    assert last["status"] == sd.STATUS_NO_BASELINE and not last["is_spike"]
    assert last["baseline_n"] == 2 and pd.isna(last["threshold"])


def test_classification_is_chronological():
    # 앞 달의 판정은 뒤의 데이터에 영향을 받지 않는다
    shares = BASE + [0.40, 0.03, 0.15, 0.02, 0.30]
    full = sd.flag_months(series(shares), min_count=0)
    for n in range(7, len(shares)):
        prefix = sd.flag_months(series(shares[:n]), min_count=0)
        assert prefix["status"].tolist() == full["status"].tolist()[:n]


def test_input_rows_and_articles_are_preserved():
    monthly = series(BASE + [0.40, 0.03])
    before = monthly.copy()
    flags = sd.flag_months(monthly, min_count=0)
    pd.testing.assert_frame_equal(monthly, before)  # 입력을 바꾸지 않는다
    assert len(flags) == len(monthly) and flags["hbm"].sum() == monthly["hbm"].sum()  # 급증 달도 남는다


# ── 구간 묶기 ──

def test_consecutive_spike_months_become_one_issue():
    flags = sd.flag_months(series(BASE + [0.20, 0.30, 0.02]), min_count=0)
    issues = sd.group_issues(flags)
    assert len(issues) == 1
    row = issues.iloc[0]
    assert row["issue_id"] == "HBM-2024-07" and row["method"] == sd.METHOD
    assert (row["start_date"], row["end_date"], row["peak_date"]) == ("2024-07-01", "2024-08-31", "2024-08-01")
    assert row["peak_share"] == pytest.approx(0.30) and row["article_count"] == 40
    assert list(issues.columns) == [c.name for c in schema.TABLES["issues"].columns]


def test_no_spike_gives_empty_issue_table():
    issues = sd.group_issues(sd.flag_months(series(BASE * 2), min_count=0))
    assert issues.empty and list(issues.columns) == [c.name for c in schema.TABLES["issues"].columns]


# ── 재현성·비교 ──

def test_repeated_runs_and_method_comparison_are_reproducible():
    monthly = series(BASE + [0.40, 0.03, 0.15, 0.02])
    first, second = sd.compare_options(monthly), sd.compare_options(monthly)
    pd.testing.assert_frame_equal(first, second)
    by = first.set_index(["exclude_spikes", "min_baseline", "min_count"])["spike_months"]
    assert by[(False, 3, 0)] == "2024-07"            # 방식 A
    assert by[(True, 3, 0)] == "2024-07, 2024-09"    # 방식 B


# ── DB 반영 ──

def _issue(issue_id, tech="HBM"):
    return {"issue_id": issue_id, "tech_tag": tech, "start_date": "2024-07-01", "end_date": "2024-07-31",
            "peak_date": "2024-07-01", "peak_share": 0.2, "baseline_share": 0.03, "article_count": 20,
            "method": sd.METHOD, "summary": None}


@pytest.fixture
def conn(tmp_path):
    c = db.connect(db.init_db(tmp_path / "t.db"))
    yield c
    c.close()


def test_persist_is_idempotent_and_keeps_other_tech_tags(conn):
    db.write_table(conn, "issues", [_issue("DRAM-2024-01", tech="DRAM"), _issue("HBM-2023-01")], mode="append")
    issues = pd.DataFrame([_issue("HBM-2024-07"), _issue("HBM-2024-09")])
    for _ in range(2):  # 두 번 돌려도 중복 행이 생기지 않는다
        result = sd.persist_issues(conn, issues)
    rows = conn.execute("SELECT issue_id FROM issues ORDER BY issue_id").fetchall()
    assert [r[0] for r in rows] == ["DRAM-2024-01", "HBM-2024-07", "HBM-2024-09"]  # 예전 HBM 행만 지움
    assert result == {"upserted": 2, "deleted": []}


def test_persist_refuses_to_delete_issue_referenced_by_evidence(conn):
    db.write_table(conn, "issues", [_issue("HBM-2023-01")], mode="append")
    conn.execute("INSERT INTO issue_evidence (issue_id, match_type) VALUES ('HBM-2023-01', '수동')")
    conn.commit()
    with pytest.raises(RuntimeError):
        sd.persist_issues(conn, pd.DataFrame([_issue("HBM-2024-07")]))
    assert conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0] == 1  # 아무것도 바꾸지 않음


def test_main_rerun_writes_same_issues(tmp_path, monkeypatch):
    # 임시 DB에 뉴스·태그를 넣고 main()을 두 번 돌려 issues가 같은지 확인
    path = db.init_db(tmp_path / "m.db")
    c = db.connect(path)
    news, tags = [], []
    shares = BASE + [0.20, 0.03]
    for i, (month, share) in enumerate(zip(pd.period_range("2024-01", periods=len(shares), freq="M").astype(str), shares)):
        n_hbm = int(round(share * 500))
        for j in range(500):
            nid = f"{i}-{j}"
            news.append({"news_id": nid, "published_at": f"{month}-15", "title": "t", "url": nid,
                         "category": "기술 및 트렌드", "is_duplicate": 0, "dup_group_id": None})
            if j < n_hbm:
                tags.append({"news_id": nid, "tag_type": "tech", "tag": "HBM", "relevance": "핵심",
                             "in_title": 1, "body_count": 0, "rule_version": "t"})
    db.write_table(c, "news", news)
    db.write_table(c, "news_tag", tags)
    c.close()
    monkeypatch.setattr(sd, "MONTHS_PATH", tmp_path / "months.csv")
    monkeypatch.setattr(sd, "OPTIONS_PATH", tmp_path / "options.csv")
    from src.eda import news_trend
    monkeypatch.setattr(news_trend.config, "ANALYSIS_START", date(2024, 1, 1))
    monkeypatch.setattr(news_trend.config, "ANALYSIS_END", date(2024, 8, 31))
    monkeypatch.setattr(news_trend.monthly_hbm, "__defaults__", (date(2024, 1, 1), date(2024, 8, 31), ("핵심", "관련")))
    first = sd.main(db_path=path)
    second = sd.main(db_path=path)
    c = db.connect(path)
    stored = pd.read_sql("SELECT issue_id, article_count FROM issues", c)
    c.close()
    assert list(first["issue_id"]) == list(second["issue_id"]) == ["HBM-2024-07"]
    assert stored.to_dict("records") == [{"issue_id": "HBM-2024-07", "article_count": 100}]
