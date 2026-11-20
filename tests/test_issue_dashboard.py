"""
대시보드 탭 1(이슈 분석) 데이터 로더·차트 테스트. 작은 임시 DB와 표로 확인한다 (Streamlit 실행 없이).

담당: 김한승 (이슈 분석)
일정: Day 6
"""

import pandas as pd
import pytest

from dashboard.components import issue_charts as ic
from dashboard.data_access import issue_loader as il
from src.common import db
from src.llm import prompts

NEWS = [  # (news_id, published_at, is_duplicate, HBM 관련도, SK, 삼성, v2 SK 감성, v2 삼성 감성)
    ("a", "2024-03-02", 0, "핵심", "핵심", None, "긍정", "해당없음"),
    ("b", "2024-03-05", 0, "관련", "언급", "관련", "중립", "부정"),
    ("c", "2024-03-06", 1, "핵심", "핵심", None, None, None),        # 중복 → 제외
    ("d", "2024-03-20", 0, "언급", None, None, None, None),          # HBM 언급 → 제외
    ("e", "2024-06-10", 0, "핵심", None, "핵심", "해당없음", "긍정"),
]
ISSUES = [("HBM-2024-03", "2024-03-01", "2024-03-31", 2), ("HBM-2024-06", "2024-06-01", "2024-06-30", 1)]


@pytest.fixture
def paths(tmp_path):
    path = db.init_db(tmp_path / "t.db")
    conn = db.connect(path)
    db.write_table(conn, "news", pd.DataFrame([
        {"news_id": i, "published_at": d, "title": f"제목 {i}", "content": "본문", "media": "매체", "url": f"https://x/{i}",
         "is_duplicate": dup, "dup_group_id": None} for i, d, dup, *_ in NEWS]), mode="append")
    tags = []
    for i, _, _, hbm, skh, sec, *_ in NEWS:
        for tt, tag, rel in (("tech", "HBM", hbm), ("company", "SK하이닉스", skh), ("company", "삼성전자", sec)):
            if rel:
                tags.append({"news_id": i, "tag_type": tt, "tag": tag, "relevance": rel, "in_title": int(rel == "핵심"),
                             "body_count": 1, "rule_version": "test"})
    db.write_table(conn, "news_tag", pd.DataFrame(tags), mode="append")
    db.write_table(conn, "news_analysis", pd.DataFrame([
        {"news_id": i, "prompt_version": prompts.PROMPT_VERSION, "sentiment_skh": s1, "sentiment_sec": s2,
         "issue_keywords": '["HBM"]', "model": "m"} for i, *_, s1, s2 in NEWS if s1]), mode="append")
    db.write_table(conn, "issues", pd.DataFrame([
        {"issue_id": iid, "tech_tag": "HBM", "start_date": s, "end_date": e, "peak_date": s, "peak_share": 0.5,
         "baseline_share": 0.1, "article_count": n, "method": "test", "summary": None} for iid, s, e, n in ISSUES]), mode="append")
    db.write_table(conn, "disclosure", pd.DataFrame([
        {"rcept_no": "r1", "corp_code": "00164779", "corp_name": "SK하이닉스", "report_nm": "신규시설투자등",
         "rcept_dt": "2024-03-03", "pblntf_ty": "I", "url": "https://dart/r1", "text_status": "확보", "rag_target": 1},
        {"rcept_no": "r2", "corp_code": "00126380", "corp_name": "삼성전자", "report_nm": "영업(잠정)실적",
         "rcept_dt": "2024-03-04", "pblntf_ty": "I", "url": "https://dart/r2", "text_status": "확보", "rag_target": 1}]), mode="append")
    db.write_table(conn, "issue_evidence", pd.DataFrame([
        {"evidence_id": 1, "issue_id": "HBM-2024-03", "news_id": "a", "rcept_no": "r1", "match_type": "키워드", "verified": 1, "note": "근거"},
        {"evidence_id": 2, "issue_id": "HBM-2024-03", "news_id": None, "rcept_no": "r2", "match_type": "기간", "verified": 0, "note": "미확인"}]),
        mode="append")
    conn.close()
    summary = tmp_path / "summary.csv"
    pd.DataFrame([
        {"issue_id": "HBM-2024-03", "period": "2024-03", "summary": "보도: <사건> 요약", "evidence_rcept_no": "r1",
         "status": "확정", "reviewer": "김한승", "note": ""},
        {"issue_id": "HBM-2024-06", "period": "2024-06", "summary": "보도: 다른 사건", "evidence_rcept_no": "",
         "status": "제외", "reviewer": "김한승", "note": "공시로 확인되지 않음"}]).to_csv(summary, index=False, encoding="utf-8-sig")
    spikes = tmp_path / "spikes.csv"
    pd.DataFrame({"month": ["2024-03", "2024-06"], "threshold": [0.2, 0.3], "status": ["spike", "spike"],
                  "is_spike": [True, True]}).to_csv(spikes, index=False, encoding="utf-8-sig")
    evalp = tmp_path / "eval.csv"
    pd.DataFrame([{"company": "SK하이닉스", "n": 50, "accuracy": 0.78, "ci_low": 0.65, "ci_high": 0.87, "macro_f1": 0.8},
                  {"company": "삼성전자", "n": 50, "accuracy": 0.88, "ci_low": 0.76, "ci_high": 0.94, "macro_f1": 0.87}]
                 ).to_csv(evalp, index=False, encoding="utf-8-sig")
    return {"db": path, "summary": summary, "spikes": spikes, "eval": evalp}


# ── 로더 ──
def test_monthly_share_merges_spike_status(paths):
    m = il.monthly_share(paths["db"], paths["spikes"]).set_index("month")
    assert m.loc["2024-03", "hbm"] == 2 and m.loc["2024-03", "total"] == 3  # c 중복 제외, d는 HBM 아님
    assert bool(m.loc["2024-03", "is_spike"]) and m.loc["2024-03", "threshold"] == 0.2
    assert not bool(m.loc["2024-04", "is_spike"])  # 급증 파일에 없는 달 = 급증 아님
    assert m.loc["2023-10", "partial"] == 1


def test_issue_table_uses_summary_status(paths):
    t = il.issue_table(paths["db"], paths["summary"]).set_index("issue_id")
    assert t.loc["HBM-2024-03", "status"] == "확정" and t.loc["HBM-2024-06", "status"] == "제외"
    assert t.loc["HBM-2024-06", "note"] == "공시로 확인되지 않음"
    assert t.loc["HBM-2024-03", "label"] == "2024-03"
    assert list(t.index) == ["HBM-2024-03", "HBM-2024-06"]


def test_issue_table_without_summary_file(paths, tmp_path):
    t = il.issue_table(paths["db"], tmp_path / "none.csv")
    assert set(t["status"]) == {"검토 전"}


def test_issue_articles_core_first_with_sentiment(paths):
    a = il.issue_articles(paths["db"], "2024-03-01", "2024-03-31")
    assert a["news_id"].tolist() == ["a", "b"]         # 핵심 먼저, 중복·언급 제외
    assert a.iloc[1]["sentiment_sec"] == "부정" and a.iloc[0]["url"] == "https://x/a"


def test_issue_evidence_only_verified_with_human_note(paths, tmp_path):
    review = tmp_path / "review.csv"
    pd.DataFrame([{"issue_id": "HBM-2024-03", "rcept_no": "r1", "news_id": "a", "match_type": "키워드",
                   "verified": "1", "note": "사람 메모"}]).to_csv(review, index=False, encoding="utf-8-sig")
    e = il.issue_evidence(paths["db"], "HBM-2024-03", review)
    assert e["rcept_no"].tolist() == ["r1"]
    assert e.iloc[0]["report_nm"] == "신규시설투자등" and e.iloc[0]["news_title"] == "제목 a"
    assert e.iloc[0]["note"] == "사람 메모"                  # DB의 자동 메모 대신 사람 메모
    assert il.issue_evidence(paths["db"], "HBM-2024-03", tmp_path / "x.csv").iloc[0]["note"] == ""


def test_period_sentiment(paths):
    s = il.period_sentiment(paths["db"], "2024-03-01", "2024-03-31").set_index("company")
    assert s.loc["SK하이닉스", "articles"] == 2 and s.loc["SK하이닉스", "net"] == pytest.approx(0.5)
    assert s.loc["삼성전자", "articles"] == 1 and s.loc["삼성전자", "net"] == pytest.approx(-1.0)


def test_eval_summary(paths, tmp_path):
    e = il.eval_summary(paths["eval"])
    assert e["SK하이닉스"]["accuracy"] == 0.78 and e["삼성전자"]["n"] == 50
    assert il.eval_summary(tmp_path / "none.csv") == {}


def test_overview(paths):
    o = il.overview(paths["db"], paths["summary"])
    assert o == {"articles": 4, "hbm_articles": 3, "issues": 2, "confirmed": 1, "excluded": 1, "verified_evidence": 1}


def test_earnings_news_counts_window_and_filters(paths):
    """실적 공시 전후(D-1~D+3) 제목에 실적 단어가 있는 HBM 기사만, 그 기업 태그(핵심·관련)로 센다."""
    conn = db.connect(paths["db"])
    db.write_table(conn, "news", pd.DataFrame([
        {"news_id": i, "published_at": d, "title": t, "content": "본문", "media": "매체", "url": f"https://x/{i}",
         "is_duplicate": dup, "dup_group_id": None}
        for i, d, t, dup in (("f", "2024-03-06", "삼성전자 1분기 영업이익 6조", 0),
                             ("g", "2024-03-06", "삼성전자 1분기 영업이익 6조", 1),     # 중복 → 제외
                             ("h", "2024-03-20", "삼성전자 실적 후속", 0),             # 창 밖 → 제외
                             ("k", "2024-03-05", "삼성전자 HBM 신제품", 0))]), mode="append")   # 실적 단어 없음 → 제외
    db.write_table(conn, "news_tag", pd.DataFrame([
        {"news_id": i, "tag_type": tt, "tag": tag, "relevance": "핵심", "in_title": 1, "body_count": 1, "rule_version": "test"}
        for i in ("f", "g", "h", "k") for tt, tag in (("tech", "HBM"), ("company", "삼성전자"))]), mode="append")
    db.write_table(conn, "disclosure", pd.DataFrame([
        {"rcept_no": "r3", "corp_code": "00126380", "corp_name": "삼성전자", "report_nm": "[기재정정]영업(잠정)실적",
         "rcept_dt": "2024-03-04", "pblntf_ty": "I", "url": "https://dart/r3", "text_status": "확보", "rag_target": 0}]),
        mode="append")
    conn.close()
    e = il.earnings_news_counts(paths["db"]).set_index("corp_name")
    assert e.loc["삼성전자", "releases"] == 1          # 같은 날 [기재정정]은 한 번으로 센다
    assert e.loc["삼성전자", "articles"] == 1          # f만 (g 중복, h 창 밖, k 제목에 실적 단어 없음)
    assert "SK하이닉스" not in e.index or e.loc["SK하이닉스", "releases"] == 0   # 시설투자 공시는 실적 공시가 아님


# ── 차트 ──
def test_share_figure_single_axis_and_issue_bands(paths):
    m = il.monthly_share(paths["db"], paths["spikes"])
    t = il.issue_table(paths["db"], paths["summary"])
    fig = ic.share_figure(m, t)
    assert "yaxis2" not in fig.to_dict()["layout"]       # 이중 축 금지
    assert len(fig.layout.shapes) == len(t)              # 급증 구간마다 띠 하나
    names = [tr.name for tr in fig.data]
    assert "HBM 비중" in names and "급증 달" in names
    assert "급증 구간 (공시로 확인)" in names and "급증 구간 (제외)" in names  # 띠 종류는 범례로


def test_sentiment_figure_follows_company_filter(paths):
    s = il.sentiment_monthly(paths["db"])
    t = il.issue_table(paths["db"], paths["summary"])
    both = ic.sentiment_figure(s, t, companies=["SK하이닉스", "삼성전자"])
    one = ic.sentiment_figure(s, t, companies=["삼성전자"])
    lines = lambda f: [tr.name for tr in f.data if tr.mode == "lines"]  # noqa: E731
    assert lines(both) == ["SK하이닉스", "삼성전자"]
    assert lines(one) == ["삼성전자"]
    assert one.data[0].line.color == ic.COMPANY_COLORS["삼성전자"]  # 필터해도 기업 색은 그대로


def test_coverage_figure(paths):
    cov = il.company_coverage(paths["db"])
    t = il.issue_table(paths["db"], paths["summary"])
    fig = ic.coverage_figure(cov, t, companies=["SK하이닉스", "삼성전자"])
    assert [tr.name for tr in fig.data] == ["SK하이닉스", "삼성전자"]
    assert "yaxis2" not in fig.to_dict()["layout"]


def test_html_builders_escape(paths):
    t = il.issue_table(paths["db"], paths["summary"])
    html = ic.issue_card_html(t.iloc[0], il.period_sentiment(paths["db"], "2024-03-01", "2024-03-31"))
    assert "&lt;사건&gt;" in html and "확정" in html
    rows = ic.article_list_html(il.issue_articles(paths["db"], "2024-03-01", "2024-03-31"))
    assert "https://x/a" in rows and "SK 긍정" in rows
    assert "신규시설투자등" in ic.evidence_html(il.issue_evidence(paths["db"], "HBM-2024-03"))
    assert "없습니다" in ic.evidence_html(il.issue_evidence(paths["db"], "HBM-2024-06"))


def test_coverage_axis_is_category(paths):
    cov = il.company_coverage(paths["db"])
    t = il.issue_table(paths["db"], paths["summary"])
    fig = ic.coverage_figure(cov, t, companies=["SK하이닉스"])
    assert fig.layout.yaxis.type == "category"               # '2024-03'을 날짜로 읽으면 막대가 한 줄로 뭉친다


# ── 기간·기업 필터 (Day 6: 필터가 모든 차트에 반영) ──
def test_month_range_filter(paths):
    m = il.monthly_share(paths["db"], paths["spikes"])
    months = il.month_options(m)
    assert months[0] == "2023-10" and months[-1] == "2026-10"
    sub = il.in_months(m, "2024-03", "2024-06")
    assert sub["month"].tolist() == ["2024-03", "2024-04", "2024-05", "2024-06"]


def test_issues_overlapping_range(paths):
    t = il.issue_table(paths["db"], paths["summary"])
    assert il.issues_in_range(t, "2024-04", "2024-12")["issue_id"].tolist() == ["HBM-2024-06"]
    assert il.issues_in_range(t, "2024-03", "2024-03")["issue_id"].tolist() == ["HBM-2024-03"]


def test_coverage_in_range_matches_sql03_for_full_period(paths):
    full = il.company_coverage(paths["db"]).set_index("period")
    mine = il.coverage_in_range(paths["db"], "2023-10", "2026-10").set_index("period")
    cols = ["hbm_articles", "skh_articles", "sec_articles", "both_articles", "neither_articles"]
    assert mine.loc[full.index, cols].astype(int).equals(full[cols].astype(int))


def test_coverage_in_range_subset(paths):
    c = il.coverage_in_range(paths["db"], "2024-06", "2024-06").set_index("period")
    assert list(c.index) == ["HBM-2024-06"] and c.loc["HBM-2024-06", "sec_articles"] == 1


def test_company_monthly_counts(paths):
    c = il.company_monthly(paths["db"]).set_index("month")
    assert c.loc["2024-03", "skh"] == 1 and c.loc["2024-03", "sec"] == 1  # SK '언급'은 제외
    assert c.loc["2024-06", "sec"] == 1


def test_issue_articles_and_evidence_follow_company(paths, tmp_path):
    a = il.issue_articles(paths["db"], "2024-03-01", "2024-03-31", company="삼성전자")
    assert a["news_id"].tolist() == ["b"]                     # a는 삼성 '해당없음' → 제외
    assert il.issue_evidence(paths["db"], "HBM-2024-03", tmp_path / "x.csv", company="삼성전자").empty
    assert len(il.issue_evidence(paths["db"], "HBM-2024-03", tmp_path / "x.csv", company="SK하이닉스")) == 1


def test_charts_follow_filters(paths):
    m = il.monthly_share(paths["db"], paths["spikes"])
    t = il.issue_table(paths["db"], paths["summary"])
    fig = ic.share_figure(il.in_months(m, "2024-03", "2024-06"), il.issues_in_range(t, "2024-03", "2024-06"),
                          x_range=ic.month_range("2024-03", "2024-06"))
    assert list(fig.layout.xaxis.range) == ["2024-03-01", "2024-07-01"]
    assert len(fig.layout.shapes) == 2
    cm = il.company_monthly(paths["db"])
    bars = ic.count_figure(m, company_counts=cm, companies=["삼성전자"])
    assert [b.name for b in bars.data] == ["삼성전자"] and bars.data[0].marker.color == ic.COMPANY_COLORS["삼성전자"]
    assert [b.name for b in ic.count_figure(m).data] == ["HBM 기사 수"]  # 전체 = 회색 한 막대


def test_range_overview_matches_full_overview(paths):
    m = il.monthly_share(paths["db"], paths["spikes"])
    t = il.issue_table(paths["db"], paths["summary"])
    ev = il.evidence_counts(paths["db"])
    assert ev == {"HBM-2024-03": 1}
    assert il.range_overview(m, t, ev) == il.overview(paths["db"], paths["summary"])  # 전체 기간이면 같다
    part = il.range_overview(il.in_months(m, "2024-06", "2024-06"), il.issues_in_range(t, "2024-06", "2024-06"), ev)
    assert part["hbm_articles"] == 1 and part["issues"] == 1 and part["verified_evidence"] == 0


def test_disclosure_links(paths):
    d = il.disclosure_links(paths["db"], ["r2", "nope"])
    assert d.to_dict("records") == [{"rcept_no": "r2", "url": "https://dart/r2"}]
    assert il.disclosure_links(paths["db"], []).empty


def test_stats_html_accuracy_label_matches_report(paths):
    """요약 타일의 정확도 표기는 리포트 4.5·6.5.2 정의(4분류 정확도, 기업별 사람 라벨 수)와 같아야 한다."""
    html = ic.stats_html(il.overview(paths["db"], paths["summary"]), il.eval_summary(paths["eval"]))
    assert "0.78 · 0.88" in html and "감성 4분류 정확도" in html and "기업별 사람 라벨 50건" in html
    assert "표본" not in html
