"""
기업별 감성 분류·이슈 키워드 추출 프롬프트 (버전 관리 → 리포트에 설계 과정 기록).

한 기사에 대해 SK하이닉스 관점과 삼성전자 관점의 감성을 따로 판정한다.
같은 기사가 한 기업에는 호재, 다른 기업에는 악재일 수 있어서다 (예: "삼성 HBM 인증 지연" → 삼성 부정, SK는 중립 또는 긍정).

라벨 정의는 초안 v1.2 §5 C '기업별 감성 라벨 정의'와 같다. 기준은 '해당 기업의 HBM 사업 관점'.
출력은 JSON 하나: {"sentiment_skh": 라벨, "sentiment_sec": 라벨, "issue_keywords": [키워드, ...]}

버전 기록 (바꿀 때마다 PROMPT_VERSION을 올리고 아래에 이유를 남긴다. news_analysis는 버전별로 따로 저장된다):
- sent_v1 (Day 4): 라벨 정의 + 판정 규칙 6개 + 본문 앞 1,500자. 근거: HBM 기사 385건 본문 중앙값 1,778자,
  핵심 사실이 앞에 오는 기사 구조라는 가정(표본 검수에서 확인). 본문 입력은 전체 본문 합계(791,489자, 평균 2,056자·최대 12,047자)보다 35% 적은 516,934자.
- sent_v2 (Day 5): 표본 50건 검수(리포트 4.5·4.6)에서 확인한 두 오류 유형을 고쳤다.
  ① 본문 잘림: 기업이 긴 기사 뒤쪽에만 나오면 '해당없음'으로 판정(SK 4·삼성 3건) → 본문 6,000자 (기사 98.2%를 끝까지, 입력 780,570자 +51%)
  ② 업계 공통 악재를 중립으로: 미국 수출 규제처럼 'K반도체' 전체 기사에서 사람은 부정, LLM은 중립(SK 4건)
     → 규칙 7 추가: 기사가 업계 전체의 사건이 그 기업에도 영향을 준다고 서술하면 그 영향으로 판정
  나머지(라벨 정의·판정 규칙 1~6·출력 형식)는 v1과 같다. v1 프롬프트는 PROMPTS에 그대로 남겨 재현할 수 있다.

담당: 김한승 (이슈 분석)
일정: Day 4
"""

import json
import re

PROMPT_VERSION = "sent_v2"  # 현재 버전 (classify 기본값)
LABELS = ("긍정", "중립", "부정", "해당없음")
MAX_KEYWORDS = 5

_SYSTEM_V1 = """당신은 증권사 반도체 담당 애널리스트를 돕는 뉴스 분석가입니다.
HBM(고대역폭 메모리) 관련 기사 한 건을 읽고, SK하이닉스와 삼성전자 각각의 HBM 사업 관점에서 감성을 판정합니다.

[라벨 정의 — 해당 기업의 HBM 사업 관점]
- 긍정: 해당 기업에 유리한 사건·평가 (예: 고객사 인증 통과, 공급 확대, 점유율 상승 전망)
- 부정: 해당 기업에 불리한 사건·평가 (예: 인증 지연, 수율 문제, 점유율 하락, 수출 규제로 인한 타격)
- 중립: 해당 기업이 등장하지만 사실 전달 위주이거나 유불리를 판단할 수 없음 (예: 일정 발표, 업계 일반 동향)
- 해당없음: 기사에 해당 기업이 등장하지 않음

[판정 규칙]
1. 두 기업을 따로 판정합니다. 한 기업의 호재가 다른 기업에는 중립이나 부정일 수 있습니다.
2. 기사에 나온 사실과 평가만 근거로 합니다. 기사 밖의 지식이나 주가 전망으로 추론하지 않습니다.
3. 기업이 이름만 스치듯 나오고 그 기업의 HBM 사업과 관련된 내용이 없으면 '중립'입니다.
4. '하이닉스', 'SK하닉'은 SK하이닉스, '삼성', '삼전'(삼성전자를 가리킬 때)은 삼성전자로 봅니다. SK그룹 회장 발언처럼 SK하이닉스 사업에 관한 내용이면 SK하이닉스로 판정합니다.
5. 유리한 내용과 불리한 내용이 섞여 있으면 기사의 중심 사건 기준으로 판정하고, 판단이 어려우면 '중립'으로 합니다.
6. issue_keywords는 기사의 핵심 이슈를 나타내는 짧은 명사구 1~5개입니다 (예: "HBM3E 인증", "엔비디아 공급", "대중 수출 규제"). 기업명만 단독으로 쓰지 않습니다.

[출력 형식]
설명 없이 아래 JSON 하나만 출력합니다.
{"sentiment_skh": "긍정|중립|부정|해당없음", "sentiment_sec": "긍정|중립|부정|해당없음", "issue_keywords": ["...", "..."]}"""

_RULE_7 = """7. 수출 규제·정책·금리·업황처럼 업계 전체에 걸친 사건이라도, 기사가 그 기업(또는 그 기업을 포함한 '한국 메모리 업체', 'K반도체')이 영향을 받는다고 서술하면 그 영향의 방향으로 판정합니다 (예: "미국 대중 HBM 수출 통제로 삼성·SK 타격 우려" → 두 기업 모두 부정). 기사에 영향 서술이 없으면 규칙 3·5를 따릅니다.
"""
_SYSTEM_V2 = _SYSTEM_V1.replace("\n\n[출력 형식]", "\n" + _RULE_7.rstrip("\n") + "\n\n[출력 형식]")

# 버전별 프롬프트와 본문 길이. 지난 버전도 지우지 않는다 (news_analysis에 버전별 결과가 남아 있어 재현·비교에 필요).
PROMPTS = {
    "sent_v1": {"system": _SYSTEM_V1, "max_chars": 1500, "body_label": "본문 앞부분"},
    "sent_v2": {"system": _SYSTEM_V2, "max_chars": 6000, "body_label": "본문"},
}
SYSTEM_PROMPT = PROMPTS[PROMPT_VERSION]["system"]
MAX_CONTENT_CHARS = PROMPTS[PROMPT_VERSION]["max_chars"]


def build_messages(title: str, content: str | None, max_chars: int | None = None,
                   version: str = PROMPT_VERSION) -> list[dict]:
    """Chat Completions용 메시지. 본문은 앞 max_chars자(기본: 버전별 길이)만 넣는다 (없으면 제목만)."""
    spec = PROMPTS[version]
    body = (content or "").strip()[:max_chars or spec["max_chars"]]
    user = f"[제목]\n{title.strip()}\n\n[{spec['body_label']}]\n{body if body else '(본문 없음)'}"
    return [{"role": "system", "content": spec["system"]}, {"role": "user", "content": user}]


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def parse_response(text: str) -> dict:
    """LLM 응답을 검증해 news_analysis 형식(dict)으로 바꾼다. 형식이 틀리면 ValueError.

    Returns:
        {"sentiment_skh": 라벨, "sentiment_sec": 라벨, "issue_keywords": [중복·공백 제거, 최대 MAX_KEYWORDS개]}
    """
    try:
        data = json.loads(_FENCE.sub("", (text or "").strip()))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON이 아님: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("JSON 객체가 아님")
    out = {}
    for key in ("sentiment_skh", "sentiment_sec"):
        if data.get(key) not in LABELS:
            raise ValueError(f"{key} 라벨이 잘못됨: {data.get(key)!r}")
        out[key] = data[key]
    keywords = data.get("issue_keywords")
    if not isinstance(keywords, list):
        raise ValueError("issue_keywords가 배열이 아님")
    cleaned = []
    for k in keywords:
        k = str(k).strip()
        if k and k not in cleaned:
            cleaned.append(k)
    out["issue_keywords"] = cleaned[:MAX_KEYWORDS]
    return out
