# 뉴스·공시 통합 스키마

> 변경 시 `src/common/schema.py`와 이 문서를 **같은 PR**에서 함께 고친다. 둘이 어긋나면 `tests/test_schema.py`가 실패한다.
> DB는 SQLite(`data/db/hbm.db`), 테이블 생성은 `src.common.schema.create_all()`.

**v1.2** — 근거: `docs/guidelines/초안_v1.2.md` §4.4 (뉴스 파일 교체에 따라 category 사용, 급증 구간을 월 단위로 변경)

## 테이블 관계

```
news ─┬─< news_tag        (규칙 기반 기술·기업 태그, 기사당 여러 행)
      ├─< news_analysis   (LLM 결과, 프롬프트 버전별 1행)
      └─< issue_evidence >─ issues     (급증 구간)
                         >─ disclosure (공시)
```

## news (담당 김한승)

제공 뉴스 원본을 적재한 테이블. 정제·중복 표시는 Day 3에 같은 테이블에 채운다.

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| news_id | TEXT | PK | 원문 URL의 SHA-1 앞 16자리 |
| published_at | DATE | NOT NULL | 발행일 (시각 제외) |
| title | TEXT | NOT NULL | 제목 |
| content | TEXT | | 본문 (원본에 비어 있으면 NULL) |
| keyword | TEXT | | 수집 키워드 원문 (`; ` 구분) |
| media | TEXT | | 매체명 |
| category | TEXT | | 가이드 이슈 카테고리 (수집 키워드에서 변환, `; ` 구분) |
| url | TEXT | NOT NULL | 원문 링크 |
| is_duplicate | INTEGER | NOT NULL, 기본 0, 0/1 | 중복 기사 여부 (대표 기사는 0) |
| dup_group_id | TEXT | | 같은 기사 묶음의 대표 news_id |

## news_tag (담당 김한승)

정규표현식 규칙으로 붙인 기술·기업 태그. 기사 하나에 여러 행이 생긴다 (예: HBM + SK하이닉스 + 삼성전자).

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| news_id | TEXT | PK, FK→news | 기사 |
| tag_type | TEXT | PK, `tech` / `company` | 태그 종류 |
| tag | TEXT | PK, `HBM` / `패키징` / `DRAM` / `SK하이닉스` / `삼성전자` | 기술·기업 태그 |
| relevance | TEXT | NOT NULL, `핵심` / `관련` / `언급` | 관련도 등급 |
| in_title | INTEGER | NOT NULL, 0/1 | 제목 포함 여부 |
| body_count | INTEGER | NOT NULL | 본문 언급 횟수 |
| rule_version | TEXT | NOT NULL | 태깅 규칙 버전 |

관련도 기준(regex_v2): **핵심** 제목 포함 / **관련** 본문 5회 이상 / **언급** 본문 1~4회. 분석에는 핵심+관련만 쓰고, 기업 태그는 HBM 핵심·관련 기사 안에서만 집계한다. `in_title`·`body_count`를 함께 저장해 기준을 바꿔도 원문을 다시 읽지 않고 재계산할 수 있다.

## news_analysis (담당 김한승, LLM 결과)

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| news_id | TEXT | PK, FK→news | 기사 |
| prompt_version | TEXT | PK | 프롬프트 버전 |
| sentiment_skh | TEXT | NOT NULL, `긍정` / `중립` / `부정` / `해당없음` | SK하이닉스 관점 감성 |
| sentiment_sec | TEXT | NOT NULL, `긍정` / `중립` / `부정` / `해당없음` | 삼성전자 관점 감성 |
| issue_keywords | TEXT | | 핵심 이슈 키워드 (JSON 배열 문자열) |
| model | TEXT | NOT NULL | LLM 모델명 |

PK에 `prompt_version`을 넣어 v1·v2 결과를 함께 보관하고 검수 정확도를 비교한다.

## issues (담당 김한승)

HBM 비중 급증 구간 (월 단위). Day 3에 생성해 한도윤에게 전달한다 (근거 연결의 입력).

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| issue_id | TEXT | PK | 급증 구간 ID (예: HBM-2024-12) |
| tech_tag | TEXT | NOT NULL, `HBM` / `패키징` / `DRAM` | 기술 태그 |
| start_date | DATE | NOT NULL | 구간 첫 달의 1일 |
| end_date | DATE | NOT NULL | 구간 마지막 달의 말일 |
| peak_date | DATE | NOT NULL | 비중 최고 달의 1일 |
| peak_share | REAL | NOT NULL | 구간 내 최대 월별 비중 (0~1) |
| baseline_share | REAL | | 직전 6개월 평균 비중 (0~1) |
| article_count | INTEGER | NOT NULL | 구간 내 관련 기사 수 (중복 제외) |
| method | TEXT | NOT NULL | 탐지 기준·버전 (예: rolling6m_2sigma_v1) |
| summary | TEXT | | 사건 요약 (검토 후 작성) |

## disclosure (담당 한도윤)

v1.0과 같다. 제약 조건(NOT NULL 등) 추가는 담당자가 결정한다.

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| rcept_no | TEXT | PK | 접수번호 |
| corp_code | TEXT | | DART 고유번호 |
| corp_name | TEXT | | 기업명 |
| report_nm | TEXT | | 공시명 |
| rcept_dt | DATE | | 제출일 |
| pblntf_ty | TEXT | | 공시 유형 |
| url | TEXT | | 원문 링크 |
| text | TEXT | | 추출 본문 |

## issue_evidence (공동, P1)

급증 구간과 기사·공시의 연결. 자동 연결은 **후보**이며, 사람이 확인한 행만 `verified = 1`로 표시한다.

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| evidence_id | INTEGER | PK | 자동 증가 ID |
| issue_id | TEXT | NOT NULL, FK→issues | 급증 구간 |
| news_id | TEXT | FK→news | 근거 기사 |
| rcept_no | TEXT | FK→disclosure | 근거 공시 |
| match_type | TEXT | NOT NULL, `기간` / `키워드` / `수동` | 연결 방식 |
| verified | INTEGER | NOT NULL, 기본 0, 0/1 | 사람이 확인했는지 여부 |
| note | TEXT | | 확인 메모 |

공시 청크는 별도 테이블 없이 `data/vectordb/` 메타데이터(`rcept_no`, `corp_code`, `report_nm`, `rcept_dt`, `section`)로 관리한다.

## 공통 규칙

- 날짜는 `YYYY-MM-DD` 문자열 (SQLite에는 TEXT로 저장)
- 기업 식별 키는 `corp_code`
- 라벨 값(기술 태그, 감성, 관련도 등)은 `src/common/schema.py`의 상수를 사용하고 문자열을 직접 쓰지 않는다
- FK 제약은 연결마다 `PRAGMA foreign_keys = ON`을 켜야 동작한다

## 변경 이력

| 버전 | 내용 |
|---|---|
| v1.0 | news, disclosure, news_analysis 최초 정의 |
| v1.1 | news: `media`·`is_duplicate`·`dup_group_id` 추가, `category` NULL 허용, `corp_name` 제거 → 기업은 `news_tag`로 / `news_tag` 신규 / news_analysis: `sentiment` → 기업별 `sentiment_skh`·`sentiment_sec`, PK에 `prompt_version` / `issues`·`issue_evidence` 신규 / disclosure 변경 없음 |
| v1.2 | 뉴스 파일을 반도체 묶음(04)으로 교체: news.category를 수집 키워드에서 변환해 채움 / issues를 주 단위 → 월 단위로 변경(설명만 변경, 컬럼 동일) |
