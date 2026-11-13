"""
정규표현식 규칙으로 뉴스에 기술·기업 태그와 관련도 등급을 붙인다 (news_tag 테이블용).

관련도 기준 (초안_v1.1 §4.3, docs/schema.md news_tag):
    핵심: 제목에 포함 / 관련: 본문에 2회 이상 / 언급: 본문에 1회
규칙을 바꾸면 RULE_VERSION을 올려 어떤 규칙으로 만든 태그인지 추적한다.

호출 관계: preprocess.py(Day 3)가 기사마다 tag_article()을 호출해 news_tag에 저장한다.
LLM을 쓰지 않으므로 비용 없이 전체 기사에 적용할 수 있고, 결과는 표본 검수로 정밀도를 확인한다.

담당: 김한승 (이슈 분석)
일정: Day 1 (규칙 초안) → Day 3 (적용·검수)
"""

import re
from typing import Optional

from src.common.schema import COMPANY_TAGS, TECH_TAGS

RULE_VERSION = "regex_v1"

# 관련도 경계값: 본문 언급이 이 횟수 이상이면 '관련'
RELATED_MIN_BODY_COUNT = 2

# (태그 종류, 태그, 패턴). 오탐을 줄이려고 넓은 단어는 앞뒤 문맥을 붙였다.
TAG_RULES: tuple[tuple[str, str, re.Pattern], ...] = (
    # HBM3E·HBM4 같은 세대 표기도 'HBM'으로 잡힌다.
    ("tech", "HBM", re.compile(r"HBM|고대역폭\s*메모리")),
    # '패키지' 단독은 '지원 패키지'·'세제 패키지' 같은 정책 기사에 많아서 수식어가 있을 때만 잡는다.
    ("tech", "패키징", re.compile(
        r"패키징|(?:첨단|어드밴스드|차세대)\s*패키지|CoWoS|하이브리드\s*본딩|2\.5D|3D\s*패키"
    )),
    # DDR5·LPDDR5X·GDDR7 같은 D램 규격 포함
    ("tech", "DRAM", re.compile(r"DRAM|D램|디램|(?:LP|G)?DDR\d")),
    ("company", "SK하이닉스", re.compile(r"SK\s*하이닉스|하이닉스|SK\s*hynix", re.IGNORECASE)),
    # '삼성' 단독은 삼성SDI·삼성바이오 등 계열사와 섞이므로 반도체 문맥이 바로 뒤에 올 때만 인정한다.
    ("company", "삼성전자", re.compile(
        r"삼성전자|삼성(?=\s*(?:HBM|D램|DRAM|메모리|반도체|파운드리))|Samsung\s+Electronics",
        re.IGNORECASE,
    )),
)

# 규칙의 태그가 스키마 CHECK 제약에 있는 값인지 임포트 시점에 확인한다.
assert {tag for kind, tag, _ in TAG_RULES if kind == "tech"} <= set(TECH_TAGS)
assert {tag for kind, tag, _ in TAG_RULES if kind == "company"} <= set(COMPANY_TAGS)


def _as_text(value) -> str:
    """None·NaN(판다스 결측값) 등 문자열이 아닌 값을 빈 문자열로 바꾼다."""
    return value if isinstance(value, str) else ""


def classify_relevance(in_title: bool, body_count: int) -> Optional[str]:
    """제목 포함 여부와 본문 언급 횟수로 관련도 등급을 정한다. 해당 없으면 None."""
    if in_title:
        return "핵심"
    if body_count >= RELATED_MIN_BODY_COUNT:
        return "관련"
    if body_count == 1:
        return "언급"
    return None


def tag_article(news_id: str, title, content) -> list[dict]:
    """기사 하나에 규칙을 적용해 news_tag 행(딕셔너리) 목록을 돌려준다.

    Args:
        news_id: 기사 ID
        title: 제목
        content: 본문 (None·NaN이면 제목만으로 판정)

    Returns:
        news_tag 컬럼 순서와 같은 키를 가진 딕셔너리 목록. 걸린 태그가 없으면 빈 목록.
    """
    title_text, body_text = _as_text(title), _as_text(content)
    rows = []
    for tag_type, tag, pattern in TAG_RULES:
        in_title = pattern.search(title_text) is not None
        body_count = len(pattern.findall(body_text))
        relevance = classify_relevance(in_title, body_count)
        if relevance is None:
            continue
        rows.append({
            "news_id": news_id,
            "tag_type": tag_type,
            "tag": tag,
            "relevance": relevance,
            "in_title": int(in_title),
            "body_count": body_count,
            "rule_version": RULE_VERSION,
        })
    return rows
