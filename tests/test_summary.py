"""
요약(첫 화면) 조각(components/summary.py) 테스트. 숫자는 compute_facts 값이 그대로 들어가는지,
근거 카드 3장·한계·링크가 있는지 확인한다.

담당: 공동
일정: Day 7
"""

import pandas as pd
import pytest

from dashboard.components import conclusion as cc
from dashboard.components import summary as sm
from tests.test_conclusion import tables  # noqa: F401  (pytest fixture 재사용)


@pytest.fixture
def facts(tables):  # noqa: F811
    return cc.compute_facts(*tables)


def test_hero_answers_question_with_computed_numbers(facts):
    html = sm.hero_html(facts)
    assert sm.QUESTION in html and sm.JUDGMENT in html
    assert "2024-12 정점(21.0%)" in html                        # 계산값 그대로
    assert f"{facts['recent_share']:.1%}" in html
    assert "~" not in html                                       # 취소선 방지


def test_cards_have_three_claims_with_evidence(facts, tables):  # noqa: F811
    monthly = tables[0]
    links = pd.DataFrame([{"rcept_no": cc.EVIDENCE_HIGHLIGHTS[0]["rcept_no"], "url": "https://dart/r1"}])
    html = sm.cards_html(facts, monthly, links)
    assert html.count('class="sm-card"') == 3
    for k in ("① 무슨 일이 있었나", "② 누구 이야기인가", "③ 공시로 확인된 사실"):
        assert k in html
    assert "60–90%" in html and "평소(급증 구간 밖) 50%" in html   # 삼성 점유 범위·평소
    assert 'href="https://dart/r1"' in html and "공시 링크 없음" in html  # 링크 있는 것·없는 것
    assert f'href="{sm.ISSUE_PAGE}"' in html and f'href="{sm.QA_PAGE}"' in html
    assert "<svg" in html


def test_sparkline_marks_peak_and_skips_partial_months(tables):  # noqa: F811
    monthly = tables[0].copy()
    def n_points(svg):
        return len(svg.split('points="')[1].split('"')[0].split())

    svg = sm.sparkline_svg(monthly, "2024-12")
    assert svg.count("<circle") == 1 and n_points(svg) == 12        # 12개 점 + 정점 표시
    monthly.loc[0, "partial"] = 1
    assert n_points(sm.sparkline_svg(monthly, "2024-12")) == 11     # 부분 월 제외
    assert sm.sparkline_svg(monthly.iloc[:1], "2024-01") == ""


def test_limits_state_what_cannot_be_confirmed(facts):
    html = sm.limits_html(facts)
    assert "HBM 투자액" in html and "0.78" in html and "표본 50건" in html
