"""
대시보드 상단 결론(components/conclusion.py) 테스트. 숫자는 저장된 결과에서 계산되는지, 문장에 그대로 들어가는지 확인한다.

담당: 김한승 (이슈 분석)
일정: Day 7
"""

import ast
import json

import pandas as pd
import pytest

from dashboard.components import conclusion as cc


@pytest.fixture
def tables():
    months = [f"2024-{m:02d}" for m in range(1, 13)]
    share = [0.02, 0.03, 0.02, 0.02, 0.03, 0.04, 0.02, 0.03, 0.15, 0.03, 0.02, 0.21]
    monthly = pd.DataFrame({"month": months, "partial": [0] * 12, "share": share,
                            "total": [100] * 12, "hbm": [int(s * 100) for s in share]})
    issues = pd.DataFrame({"issue_id": ["HBM-2024-09", "HBM-2024-12", "HBM-2024-03"],
                           "start_date": ["2024-09-01", "2024-12-01", "2024-03-01"],
                           "end_date": ["2024-09-30", "2024-12-31", "2024-03-31"],
                           "status": ["확정", "확정", "제외"]})
    coverage = pd.DataFrame({"period": ["HBM-2024-09", "HBM-2024-12", "HBM-2024-03", "(급증 구간 밖)"],
                             "skh_share": [0.2, 0.1, 0.9, 0.48], "sec_share": [0.6, 0.9, 0.1, 0.50]})
    rows = []
    for m in months:
        for comp, pos, neg in (("SK하이닉스", 3, 1), ("삼성전자", 1, 2 if m < "2024-07" else 0)):
            rows.append({"month": m, "company": comp, "partial": 0, "positive": pos, "neutral": 1,
                         "negative": neg, "articles": pos + 1 + neg})
    sentiment = pd.DataFrame(rows)
    ev = {"SK하이닉스": {"accuracy": 0.78, "n": 50, "macro_f1": 0.80}, "삼성전자": {"accuracy": 0.88, "n": 50, "macro_f1": 0.87}}
    return monthly, issues, coverage, sentiment, ev


@pytest.fixture
def earnings():
    return pd.DataFrame({"corp_name": ["SK하이닉스", "삼성전자"], "releases": [12, 12], "articles": [5, 33]})


def test_compute_facts(tables):
    f = cc.compute_facts(*tables)
    assert f["peak_month"] == "2024-12" and f["peak_share"] == pytest.approx(0.21)
    assert f["later_spikes"] == 0                                    # 정점 뒤 확정 구간 없음
    assert f["recent_share"] == pytest.approx((0.03 + 0.02 + 0.21) / 3)   # 마지막 3개월 평균
    assert f["confirmed"] == 2 and f["sec_share_min"] == pytest.approx(0.6) and f["sec_share_max"] == pytest.approx(0.9)
    assert f["outside_sec"] == pytest.approx(0.50) and f["outside_skh"] == pytest.approx(0.48)  # 제외 구간은 빠짐
    assert f["neg_share"]["SK하이닉스"] == pytest.approx(12 / 60)          # 부정 12 / 등장 60
    assert f["accuracy"] == {"SK하이닉스": 0.78, "삼성전자": 0.88} and f["eval_n"] == 50
    assert f["neg_counts"]["SK하이닉스"] == (12, 60)                     # 부정 건수·분모도 함께 보여 준다
    assert f["earnings"] is None                                       # 실적 기사 수를 안 넘기면 None


def test_sec_turn_reports_quarter_article_counts(tables):
    f = cc.compute_facts(*tables)
    # 삼성 분기: 2024Q1·Q2 각 12건(긍3·부6) 순감성 −0.25, Q3·Q4 각 6건(긍3·부0) +0.5
    assert f["sec_trough"] == ("2024Q1", pytest.approx(-0.25)) and f["sec_trough_n"] == 12
    assert f["sec_rebound"][0] == "2024Q3" and f["sec_rebound_n"] == 6


def test_compute_facts_earnings_counts(tables, earnings):
    f = cc.compute_facts(*tables, earnings=earnings)
    assert f["earnings"] == {"SK하이닉스": (5, 12), "삼성전자": (33, 12)}    # (기사 수, 실적 공시 횟수)


def test_negative_share_uses_appearing_articles(tables):
    f = cc.compute_facts(*tables)
    # 삼성: 1~6월 기사 4건(긍1·중1·부2), 7~12월 2건(긍1·중1) → 부정 12 / 등장 36
    assert f["neg_share"]["삼성전자"] == pytest.approx(12 / 36)


def test_conclusion_html_contains_facts_and_links(tables, earnings):
    f = cc.compute_facts(*tables, earnings=earnings)
    evidence = pd.DataFrame([{"rcept_no": "20241024800002", "url": "https://dart/r1"}])
    html = cc.conclusion_html(f, evidence)
    assert "2024-12" in html and "21.3%" not in html and "21.0%" in html   # 계산값 그대로
    assert "60–90%" in html and "50%" in html and "~" not in html  # 취소선 방지
    assert "12/60" in html and "12/36" in html                          # 부정 비율의 분자/분모
    assert "0.78" in html and "0.88" in html and "Macro-F1 0.80" in html and "사람 라벨 50건" in html
    assert "HBM 투자액" in html                                        # 공시로 확인 못 하는 부분 명시
    assert 'href="https://dart/r1"' in html and "공시 링크 없음" in html  # 링크가 없는 인용은 표시
    assert "p.5" in html and "p.8" in html                              # 인용 쪽 번호


def test_conclusion_html_news_gap_is_qualified(tables, earnings):
    html = cc.conclusion_html(cc.compute_facts(*tables, earnings=earnings), pd.DataFrame(columns=["rcept_no", "url"]))
    assert "덜 드러난다" not in html and "거의 없어" not in html            # 근거 없는 '과소 보도' 단정 금지
    assert "수집한 뉴스" in html and "SK하이닉스 <b>5건</b>" in html and "삼성전자 <b>33건</b>" in html
    assert "언론 전체" in html                                         # 수집 데이터 한정임을 밝힌다


def test_conclusion_html_without_earnings_counts(tables):
    html = cc.conclusion_html(cc.compute_facts(*tables), pd.DataFrame(columns=["rcept_no", "url"]))
    assert "실적 공시 전후" not in html and "덜 드러난다" not in html     # 숫자가 없으면 그 문장을 빼고 그린다


def test_conclusion_html_marks_computed_vs_approved(tables, earnings):
    html = cc.conclusion_html(cc.compute_facts(*tables, earnings=earnings), pd.DataFrame(columns=["rcept_no", "url"]))
    assert "자동 계산" in html and "두 사람이 검토해 고정" in html


def test_highlights_reference_verified_evidence_only():
    ids = {h["rcept_no"] for h in cc.EVIDENCE_HIGHLIGHTS}
    review = pd.read_csv(cc.REVIEW_PATH, dtype=str, keep_default_na=False)
    verified = set(review.loc[review["verified"] == "1", "rcept_no"])
    assert ids and ids <= verified                                    # 결론 인용은 사람이 확인한 공시만


def _norm(text: str) -> str:
    return "".join(text.split()).replace("’", "'").replace("‘", "'")


def test_highlight_quotes_appear_verbatim_on_cited_page():
    """인용 문구가 공시 첨부 PDF의 해당 쪽 텍스트에 그대로 있는지 확인 (verified=1만으로는 문구를 보증하지 못한다).

    추출 텍스트는 단 구분을 잃기 때문에, 문구가 어느 단('25.1분기 현황/전망)에 속하는지는 PDF를 직접 보고 section에 적었다.
    data/processed는 git에 없으므로 파일이 없으면 건너뛴다.
    """
    path = cc.config.PROCESSED_DIR / "disclosure_attachments.jsonl"
    if not path.exists():
        pytest.skip("disclosure_attachments.jsonl 없음 (data/processed는 git 제외)")
    pages = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        doc = ast.literal_eval(d["pages"]) if isinstance(d["pages"], str) else d["pages"]   # 쪽별 텍스트 목록
        pages.setdefault(d["rcept_no"], []).append(doc)
    for h in cc.EVIDENCE_HIGHLIGHTS:
        docs = pages.get(h["rcept_no"])
        assert docs, h["rcept_no"]
        for page, text in h["excerpts"]:
            found = any(len(doc) >= page and _norm(text) in _norm(doc[page - 1]) for doc in docs)
            assert found, f"{h['rcept_no']} p.{page}: {text}"
