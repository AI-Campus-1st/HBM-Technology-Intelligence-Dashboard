"""
대시보드 상단 결론(components/conclusion.py) 테스트. 숫자는 저장된 결과에서 계산되는지, 문장에 그대로 들어가는지 확인한다.

담당: 김한승 (이슈 분석)
일정: Day 7
"""

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
    ev = {"SK하이닉스": {"accuracy": 0.78, "n": 50}, "삼성전자": {"accuracy": 0.88, "n": 50}}
    return monthly, issues, coverage, sentiment, ev


def test_compute_facts(tables):
    f = cc.compute_facts(*tables)
    assert f["peak_month"] == "2024-12" and f["peak_share"] == pytest.approx(0.21)
    assert f["later_spikes"] == 0                                    # 정점 뒤 확정 구간 없음
    assert f["recent_share"] == pytest.approx((0.03 + 0.02 + 0.21) / 3)   # 마지막 3개월 평균
    assert f["confirmed"] == 2 and f["sec_share_min"] == pytest.approx(0.6) and f["sec_share_max"] == pytest.approx(0.9)
    assert f["outside_sec"] == pytest.approx(0.50) and f["outside_skh"] == pytest.approx(0.48)  # 제외 구간은 빠짐
    assert f["neg_share"]["SK하이닉스"] == pytest.approx(12 / 60)          # 부정 12 / 등장 60
    assert f["accuracy"] == {"SK하이닉스": 0.78, "삼성전자": 0.88} and f["eval_n"] == 50


def test_negative_share_uses_appearing_articles(tables):
    f = cc.compute_facts(*tables)
    # 삼성: 1~6월 기사 4건(긍1·중1·부2), 7~12월 2건(긍1·중1) → 부정 12 / 등장 36
    assert f["neg_share"]["삼성전자"] == pytest.approx(12 / 36)


def test_conclusion_html_contains_facts_and_links(tables):
    f = cc.compute_facts(*tables)
    evidence = pd.DataFrame([{"rcept_no": "r1", "url": "https://dart/r1"}])
    html = cc.conclusion_html(f, evidence)
    assert "2024-12" in html and "21.3%" not in html and "21.0%" in html   # 계산값 그대로
    assert "60–90%" in html and "50%" in html and "~" not in html  # 취소선 방지
    assert "0.78" in html and "0.88" in html and "표본 50건" in html
    assert "HBM 투자액" in html                                        # 공시로 확인 못 하는 부분 명시
    assert 'href="https://dart/r1"' in html or "공시 링크 없음" in html


def test_highlights_reference_verified_evidence_only():
    ids = {h["rcept_no"] for h in cc.EVIDENCE_HIGHLIGHTS}
    review = pd.read_csv(cc.REVIEW_PATH, dtype=str, keep_default_na=False)
    verified = set(review.loc[review["verified"] == "1", "rcept_no"])
    assert ids and ids <= verified                                    # 결론 인용은 사람이 확인한 공시만
