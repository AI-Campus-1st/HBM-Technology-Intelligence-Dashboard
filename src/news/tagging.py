"""
정규표현식 규칙으로 뉴스에 기술·기업 태그와 관련도 등급을 붙인다 (news_tag 테이블용).

관련도 기준 (regex_v2부터, v3에서 유지):
    핵심: 제목에 포함 / 관련: 본문에 5회 이상 / 언급: 본문에 1~4회
    v1(관련 = 본문 2회 이상)은 표본 검수에서 '관련' 정밀도가 0.53(02 데이터)·0.20(04 데이터)으로 낮았다.
    본문 5회 이상으로 올리면 0.92·0.83이 되어 v2 기준으로 채택했다. (outputs/reports/tag_precision_*.csv)
규칙을 바꾸면 RULE_VERSION을 올려 어떤 규칙으로 만든 태그인지 추적한다.

regex_v3: 기업 약칭 보강. v2는 '삼성' 뒤에 반도체 단어가 바로 와야만 삼성전자로 인정해
'삼성·SK', '삼성 “…”', '삼성도' 같은 제목을 놓쳤다(04 검수 삼성 '언급' 15건 중 3건).
v3는 '삼성' 뒤에 계열사·지명이 오지 않으면 삼성전자로 보고, '삼전'·'하닉'·'삼전닉스' 같은 약칭과
'삼성·SK'의 SK를 인정한다.

사용 원칙: 기업 태그는 이름만 나열된 기사가 많아 단독 정밀도가 낮다(04 '관련' 0.15~0.45).
기업별 보도 점유·감성은 HBM 핵심·관련 기사 안에서만 집계한다.

호출 관계: preprocess.py(Day 3)가 기사마다 tag_article()을 호출해 news_tag에 저장한다.
LLM을 쓰지 않으므로 비용 없이 전체 기사에 적용할 수 있고, 결과는 표본 검수로 정밀도를 확인한다.

담당: 김한승 (이슈 분석)
일정: Day 1 (규칙 초안) → Day 3 (적용·검수)
"""

import re
from typing import Optional

from src.common.schema import COMPANY_TAGS, TECH_TAGS

RULE_VERSION = "regex_v3"

# 관련도 경계값: 본문 언급이 이 횟수 이상이면 '관련'
RELATED_MIN_BODY_COUNT = 5

# '삼성' 뒤에 오면 삼성전자가 아닌 것으로 보는 말 (계열사·지명·그룹). 앞의 것이 우선이라 긴 이름을 먼저 둔다.
SAMSUNG_EXCLUDE = (
    "SDI", "SDS", "에스디에스", "바이오", "물산", "생명", "화재", "증권", "카드", "선물", "자산운용", "액티브",
    "디스플레이", "전기", "중공업", "E&A", "엔지니어링", "웰스토리", "벤처", "글로벌리서치", "서울병원",
    "의료원", "재단", "라이온즈", "그룹", "동", "역", "로", "타운", "리서치",
)

# (태그 종류, 태그, 패턴). 오탐을 줄이려고 넓은 단어는 앞뒤 문맥을 붙였다.
TAG_RULES: tuple[tuple[str, str, re.Pattern], ...] = (
    # HBM3E·HBM4 같은 세대 표기도 'HBM'으로 잡힌다.
    # 'PLUS 글로벌HBM반도체' 같은 ETF 상품명은 HBM 기사가 아니므로 '글로벌' 바로 뒤의 HBM은 제외한다.
    ("tech", "HBM", re.compile(r"(?<!글로벌)HBM|고대역폭\s*메모리")),
    # '패키지' 단독은 '지원 패키지'·'세제 패키지' 같은 정책 기사에 많아서 수식어가 있을 때만 잡는다.
    ("tech", "패키징", re.compile(
        r"패키징|(?:첨단|어드밴스드|차세대)\s*패키지|CoWoS|하이브리드\s*본딩|2\.5D|3D\s*패키"
    )),
    # DDR5·LPDDR5X·GDDR7 같은 D램 규격 포함
    ("tech", "DRAM", re.compile(r"DRAM|D램|디램|(?:LP|G)?DDR\d")),
    # 'SK' 단독은 SK그룹·SK텔레콤 등과 섞이므로 '삼성·SK'처럼 삼성과 나란히 쓴 경우만 인정한다.
    ("company", "SK하이닉스", re.compile(
        r"SK\s*하이닉스|하이닉스|SK\s*hynix|하닉|(?<=삼전)닉스|(?<=삼성·)SK(?![A-Za-z가-힣])|(?<=삼성, )SK(?![A-Za-z가-힣])",
        re.IGNORECASE,
    )),
    # '삼성' 뒤에 계열사·지명이 오면 제외하고, 그 밖의 '삼성'(삼성·SK, 삼성도, 삼성 “…”)은 삼성전자로 본다.
    ("company", "삼성전자", re.compile(
        r"삼성전자|삼전|Samsung\s+Electronics|삼성(?!\s*(?:" + "|".join(SAMSUNG_EXCLUDE) + r"))",
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
    if body_count >= 1:
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
