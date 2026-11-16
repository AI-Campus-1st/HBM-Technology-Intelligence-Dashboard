# data/labels — 표본 검수 결과 (커밋 대상)

`src/llm/validate_sample.py`가 만든 검수용 CSV에 사람이 정답 라벨을 채워 이곳에 저장한다.
예) `sentiment_sample_v1.csv` — 컬럼: news_id, title, llm_sentiment, human_sentiment

## disclosure_review_v1.csv — 공시 관련성 검수 (한도윤)

`python -m src.dart.relevance_review sample`이 만든 표본 134건. 수집한 공시가 프로젝트 질문에 실제로 관련 있는지 확인한다.

| 층 (`stratum`) | 표본 | 보는 것 |
|---|---:|---|
| A·D·J RAG대상 | 전수 (24·11·29) | 정밀도 |
| B·I RAG대상 | 무작위 20씩 | 정밀도 |
| I·J 제외 | 무작위 15씩 | 놓친 비율 (필터가 관련 공시를 잘못 뺐는지) |

**채우는 법:** `head`(본문 앞 300자)와 `context`(판정 단서 주변 발췌)를 보고 `label`을 채운다. 애매하면 `url`로 원문을 연다.

| label | 의미 | 예 |
|---|---|---|
| 2 | 직접: HBM 또는 HBM 관련 투자·제품·실적·고객을 다룸 | 사업보고서의 HBM 매출·R&D, HBM 라인 신규시설투자, 패키징 공장 보도 해명 |
| 1 | 간접: 메모리 사업·설비투자·실적·경영계획 등 HBM 판단의 배경 근거 | FAB 건설 매입, 영업(잠정)실적, 장래사업·경영계획 |
| 0 | 무관 | 자사주 보상 처분, 배당, 계열사 보험·급식 거래, 위임장 플랫폼 안내 |

- `note`: 애매한 이유, `labeler`: 판정한 사람 (예: `한도윤`, `claude_1차` → 사람 확인 후 이름으로 바꿈)
- 다 채우면 `python -m src.dart.relevance_review score` → `outputs/reports/disclosure_relevance_v1.csv`
- 표본을 다시 뽑으려면 `sample --force` (채운 라벨이 지워지므로 주의)
