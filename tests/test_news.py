"""
뉴스 정제·중복 처리·태깅 테스트.

담당: 김한승 (이슈 분석)
일정: Day 1~
"""

import pytest

from src.common.schema import RELEVANCE_LEVELS, TABLES
from src.news import tagging


def tags_of(rows):
    """tag_article 결과를 {태그: 관련도} 딕셔너리로 줄인다."""
    return {row["tag"]: row["relevance"] for row in rows}


# ── 관련도 등급 ──

@pytest.mark.parametrize(
    "in_title, body_count, expected",
    [
        (True, 0, "핵심"),   # 제목에 있으면 본문 횟수와 관계없이 핵심
        (True, 5, "핵심"),
        (False, 2, "관련"),  # 경계값: 본문 2회부터 관련
        (False, 9, "관련"),
        (False, 1, "언급"),
        (False, 0, None),    # 어디에도 없으면 태그하지 않음
    ],
)
def test_classify_relevance(in_title, body_count, expected):
    assert tagging.classify_relevance(in_title, body_count) == expected


def test_relevance_values_match_schema():
    assert {"핵심", "관련", "언급"} == set(RELEVANCE_LEVELS)


# ── 기술 태그 ──

def test_hbm_variants_are_counted():
    rows = tagging.tag_article("n1", "반도체 동향", "HBM3E 양산. HBM4 개발. 고대역폭 메모리 수요.")
    assert tags_of(rows)["HBM"] == "관련"
    hbm = next(r for r in rows if r["tag"] == "HBM")
    assert hbm["body_count"] == 3 and hbm["in_title"] == 0


def test_title_hit_makes_core():
    rows = tagging.tag_article("n1", "SK하이닉스, HBM 공급 확대", "공급 계약을 맺었다.")
    assert tags_of(rows)["HBM"] == "핵심"
    assert tags_of(rows)["SK하이닉스"] == "핵심"


def test_policy_package_is_not_packaging():
    # '패키지'는 정책·지원 패키지에서 흔하므로 단독으로는 패키징이 아니다
    rows = tagging.tag_article("n1", "정부, 반도체 지원 패키지 발표", "세제 패키지와 금융 패키지를 포함한다.")
    assert "패키징" not in tags_of(rows)


def test_advanced_packaging_is_tagged():
    rows = tagging.tag_article("n1", "제목", "첨단 패키지 투자와 CoWoS 증설, 하이브리드 본딩 도입")
    assert tags_of(rows)["패키징"] == "관련"


def test_dram_variants():
    rows = tagging.tag_article("n1", "제목", "D램 가격 상승, DDR5 수요")
    assert tags_of(rows)["DRAM"] == "관련"


# ── 기업 태그 ──

def test_samsung_affiliates_are_not_samsung_electronics():
    rows = tagging.tag_article("n1", "삼성SDI·삼성바이오로직스 실적", "삼성물산과 삼성생명도 언급")
    assert "삼성전자" not in tags_of(rows)


def test_samsung_short_form_with_semiconductor_context():
    rows = tagging.tag_article("n1", "제목", "삼성 HBM 인증 지연. 삼성전자 대응")
    assert tags_of(rows)["삼성전자"] == "관련"


def test_hynix_variants():
    rows = tagging.tag_article("n1", "제목", "SK 하이닉스와 SK hynix")
    assert tags_of(rows)["SK하이닉스"] == "관련"


def test_company_rows_have_company_type():
    rows = tagging.tag_article("n1", "삼성전자 HBM", "")
    types = {r["tag"]: r["tag_type"] for r in rows}
    assert types == {"HBM": "tech", "삼성전자": "company"}


# ── 결측·출력 형식 ──

@pytest.mark.parametrize("content", [None, "", float("nan")])
def test_missing_content_uses_title_only(content):
    rows = tagging.tag_article("n1", "HBM 수요 급증", content)
    assert tags_of(rows) == {"HBM": "핵심"}


def test_no_match_returns_empty_list():
    assert tagging.tag_article("n1", "날씨", "맑음") == []


def test_rows_match_news_tag_columns():
    rows = tagging.tag_article("n1", "HBM", "")
    expected = [c.name for c in TABLES["news_tag"].columns]
    assert list(rows[0]) == expected
    assert rows[0]["rule_version"] == tagging.RULE_VERSION


# ── 태깅 정밀도 검수 (tag_validation) ──

import re

import pandas as pd

from src.news import tag_validation as tv


def test_wilson_interval_bounds():
    low, high = tv.wilson_interval(27, 30)
    assert 0.73 < low < 0.75 and 0.96 < high < 0.98  # 27/30 = 0.9


def test_wilson_interval_handles_extremes():
    assert tv.wilson_interval(0, 0) == (0.0, 0.0)
    low, high = tv.wilson_interval(30, 30)
    assert high == pytest.approx(1.0) and low < 1.0  # 전부 맞아도 하한은 1보다 작다


def test_precision_table_ignores_unlabeled_rows():
    labels = pd.DataFrame({
        "tag": ["HBM"] * 4 + ["삼성전자"] * 2,
        "relevance": ["핵심", "핵심", "핵심", "핵심", "언급", "언급"],
        "label": [1, 1, 0, None, 0, 1],
    })
    table = tv.precision_table(labels).set_index(["tag", "relevance"])
    assert table.loc[("HBM", "핵심"), "n_labeled"] == 3
    assert table.loc[("HBM", "핵심"), "precision"] == pytest.approx(2 / 3)
    assert table.loc[("삼성전자", "언급"), "n_correct"] == 1


def test_precision_table_rejects_invalid_label():
    labels = pd.DataFrame({"tag": ["HBM"], "relevance": ["핵심"], "label": [2]})
    with pytest.raises(ValueError):
        tv.precision_table(labels)


def test_extract_contexts_shows_text_around_matches():
    text = "앞부분 " * 20 + "HBM 공급" + " 뒷부분" * 20
    snippet = tv.extract_contexts(text, re.compile("HBM"), width=10)
    assert "HBM 공급" in snippet and len(snippet) < 40


def test_extract_contexts_limits_hits_and_handles_missing():
    text = "HBM 하나. " + "x" * 200 + " HBM 둘. " + "x" * 200 + " HBM 셋."
    assert tv.extract_contexts(text, re.compile("HBM"), width=5, max_hits=2).count("HBM") == 2
    assert tv.extract_contexts(None, re.compile("HBM")) == ""


def test_reservoir_sampler_is_reproducible_and_capped():
    def run(seed):
        sampler = tv.ReservoirSampler(k=5, seed=seed)
        for i in range(100):
            sampler.add(i)
        return sampler.items

    assert run(1) == run(1)
    assert len(run(1)) == 5
    assert run(1) != run(2)


def test_reservoir_sampler_keeps_all_when_fewer_than_k():
    sampler = tv.ReservoirSampler(k=5, seed=0)
    for i in range(3):
        sampler.add(i)
    assert sorted(sampler.items) == [0, 1, 2]
