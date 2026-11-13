# 뉴스·공시 통합 스키마

> Day 1에 확정. 변경 시 `src/common/schema.py`와 이 문서를 **같은 PR**에서 함께 고친다.

## news (담당 A)
| 컬럼 | 타입 | 설명 |
|---|---|---|
| news_id | TEXT (PK) | |
| published_at | DATE | |
| title | TEXT | |
| content | TEXT | |
| keyword | TEXT | 수집 키워드 |
| category | TEXT | 규제 및 정책 / 기술 및 트렌드 / 시장 및 경쟁 / 공급망 및 인프라 |
| corp_name | TEXT | 관련 기업 (매칭 시) |
| url | TEXT | |

## disclosure (담당 B)
| 컬럼 | 타입 | 설명 |
|---|---|---|
| rcept_no | TEXT (PK) | 접수번호 |
| corp_code | TEXT | |
| corp_name | TEXT | |
| report_nm | TEXT | 공시명 |
| rcept_dt | DATE | 제출일 |
| pblntf_ty | TEXT | 공시 유형 |
| url | TEXT | 원문 링크 |
| text | TEXT | 추출 본문 |

## news_analysis (담당 A, LLM 결과)
| 컬럼 | 타입 | 설명 |
|---|---|---|
| news_id | TEXT (FK) | |
| sentiment | TEXT | 긍정/중립/부정 |
| issue_keywords | TEXT | |
| model / prompt_version | TEXT | 재현용 |

## 공통 규칙
- 날짜는 `YYYY-MM-DD`
- 기업 식별 키는 `corp_code`
