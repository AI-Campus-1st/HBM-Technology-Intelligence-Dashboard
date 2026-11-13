# AI 기반 HBM 기술 경쟁 분석 — SK하이닉스 vs 삼성전자 기술 인텔리전스 대시보드

**HBM Technology Intelligence Dashboard** · 기획 v1.1

> **"HBM 경쟁에서 SK하이닉스와 삼성전자에 대한 시장의 관심과 이슈는 시기별로 어떻게 달라졌으며, 공시로 확인되는 대응과 애널리스트가 추가로 확인해야 할 기회·위험 신호는 무엇인가?"**

AI 반도체 뉴스와 SK하이닉스·삼성전자 DART 공시를 통합 분석하여 HBM 이슈의 **비중 변화와 급증 시점**을 탐지하고, 기업별 보도·감성 차이와 공시 근거를 비교합니다. 이를 통해 **근거와 한계를 명시하는 애널리스트용 기술 인텔리전스 대시보드**를 만듭니다.

**분석 흐름:** HBM 이슈 비중 변화 → 급증 시점 탐지 → 기업별(SK하이닉스·삼성전자) 보도·감성 비교 → 공시 근거 확인

| 항목 | 내용 |
|---|---|
| 기간 / 인원 | 7일 / 2인 1조 |
| 산업군 | 반도체 |
| 대상 기업 | **SK하이닉스** (비교: **삼성전자**) — 두 기업 모두 DART 공시 수집 |
| 분석 기술 범위 | **우선:** HBM · **보조 후보:** 첨단 패키징, DRAM (팀 논의 후 확정) |
| 뉴스 데이터 | 제공 AI반도체 묶음 120,057건 (2021-10-16 ~ 2026-10-16), 수집 키워드 `AI 반도체` · `인공지능 반도체` |
| 분석 기간 | **2023-01-01 ~ 2026-09-30** 제안 (뉴스·공시 동일 기간, 팀 논의 후 확정) |
| 기술 | Python(Pandas·NumPy) · 정규표현식 · DART OpenAPI · LLM API · LangChain · VectorDB · Plotly · Streamlit |

### 대시보드 사용자

**증권사 반도체 담당 애널리스트** *(가상 페르소나)*
- **업무:** 메모리 업체 실적·전략 리포트 작성 전, HBM 경쟁 구도의 변화와 근거 자료를 빠르게 정리한다.
- **문제:** 기사가 많고 중복이 많아 "언제, 왜, 누구에게 유리하게" 이슈가 바뀌었는지와 공시 근거를 찾는 데 시간이 든다.
- **필요한 결과:** HBM 이슈 비중 추이, 급증 시점과 원인 기사, 기업별 보도·감성 비교, 공시상 확인 사실, 확인 불가 항목
- **범위:** 공개자료 기반 기술 인텔리전스. 투자 의견·목표주가는 제시하지 않는다.

> 기관투자자·협력사 전략기획 담당자는 필요한 데이터(주가, 고객사별 발주 등)가 범위 밖이라 주 사용자에서 제외하고, 리포트에서 확장 사용자로만 언급합니다.

### 핵심 질문

**메인:** HBM 경쟁에서 SK하이닉스와 삼성전자에 대한 시장의 관심과 이슈는 시기별로 어떻게 달라졌으며, 공시로 확인되는 대응과 애널리스트가 추가로 확인해야 할 기회·위험 신호는 무엇인가?

1. HBM 관련 보도 **비중**은 언제 급증하고 둔화했는가? 급증 시점의 대표 사건은 무엇인가?
2. 같은 기간 SK하이닉스와 삼성전자의 HBM 보도 점유율과 감성은 어떻게 달랐는가?
3. 두 기업의 공시에서 확인되는 R&D·투자·제품 관련 정보는 무엇이며, 공시로 확인할 수 없는 부분은 무엇인가?

### 해석 원칙

- 기사 **절대량이 아니라 비중**으로 관심도를 판단한다. 전체 수집 기사 자체가 2023년 대비 약 10배 늘었기 때문이다.
- 보도 점유·감성은 실제 시장 점유율이나 사업 성과가 아니다.
- 회사 전체 R&D 지출은 HBM 투자액이 아니며, 사업 구조가 다른 삼성전자와 전체 수치를 직접 비교하지 않는다.
- 같은 시점에 뉴스와 공시가 있다고 해서 인과관계로 해석하지 않는다.

> 기획 상세(데이터 1차 점검 결과, 지표 정의, 검증 설계, 대시보드 구성, 일정)는 [docs/guidelines/초안_v1.1.md](docs/guidelines/초안_v1.1.md)를 참고합니다.

### 역할

| 역할 | 담당 영역 |
|---|---|
| **김한승 — 이슈 분석** | 뉴스 적재·정제, EDA, LLM 감성 분류·이슈 추출, 이슈 분석 화면 |
| **한도윤 — 공시 분석** | DART 공시 수집·파싱, 청킹·임베딩, RAG Q&A, 공시 Q&A 화면 |
| **공동** | 통합 스키마, 대시보드 통합, 스토리텔링, 리포트 |

---

## 빠른 시작

```bash
python -m venv .venv
```
```bash
.venv\Scripts\activate
```
```bash
pip install -r requirements.txt
```
```bash
copy .env.example .env
```
`.env`에 `DART_API_KEY`, `OPENAI_API_KEY`를 채운 뒤 아래 실행 순서대로 진행합니다.

## 실행 순서 (파이프라인)

모든 명령은 프로젝트 루트에서 실행합니다. 수집·분석 결과는 `data/`에 저장되고, 대시보드는 **저장된 결과만 조회**합니다.

| 순서 | 명령 | 담당 | 결과 |
|---|---|---|---|
| 1 | `python -m src.common.db` | 공동 | DB·테이블 생성 |
| 2 | `python -m src.news.load_news` | 김한승 | 뉴스 DB 적재 |
| 3 | `python -m src.dart.corp_code` | 한도윤 | SK하이닉스·삼성전자 corp_code |
| 4 | `python -m src.dart.collect_list` | 한도윤 | 공시 목록 (원본 저장) |
| 5 | `python -m src.dart.collect_documents` | 한도윤 | 공시 원문 파일 |
| 6 | `python -m src.dart.parse_documents` | 한도윤 | 공시 텍스트 DB 적재 |
| 7 | `python -m src.news.preprocess` | 김한승 | 정제·중복 제거된 뉴스 |
| 8 | `python -m src.eda.spike_detection` | 공동 | 이슈 급증 시점 |
| 9 | `python -m src.llm.classify` | 김한승 | 감성·이슈 분석 결과 |
| 10 | `python -m src.rag.build_index` | 한도윤 | 벡터 DB |
| 11 | `streamlit run dashboard/app.py` | 공동 | 대시보드 실행 |

> 2·7·9(김한승)와 3~6·10(한도윤)은 서로 독립이라 병행할 수 있습니다.

---

## 폴더 구조

```
mid_project/
├── README.md                     # 이 문서: 프로젝트 소개, 실행 순서, 구조 설명
├── requirements.txt              # 전체 설치용 (requirements/ 3개를 포함만 함, 직접 수정 X)
├── requirements/                 # 담당별 패키지 목록 (충돌 방지용 분리)
├── .env.example                  # 환경변수 견본 (실제 키는 .env, 커밋 금지)
├── .gitignore / .gitattributes   # 비밀·데이터 제외 / 줄바꿈 통일
├── .github/                      # PR 템플릿, CODEOWNERS
├── .streamlit/                   # Streamlit 설정
│
├── docs/                         # 📚 모든 문서
│   ├── guidelines/               #   과제 가이드라인, 일일 체크리스트 등 받은/정리한 참고 문서
│   ├── schema.md                 #   뉴스·공시 통합 스키마 (Day 1 확정)
│   ├── conventions.md            #   협업 규칙 (브랜치, 커밋, 파일 소유권)
│   ├── daily_log/                #   날짜·사람별 작업 일지
│   ├── report/                   #   최종 리포트 (장별 파일)
│   └── presentation/             #   발표 PPT, 스크린샷
│
├── src/                          # 🔧 수집·분석 코드 (대시보드와 분리된 계층)
│   ├── common/   [공동]          #   설정, 스키마, DB 연결
│   ├── news/     [김한승]        #   뉴스 적재·정제
│   ├── dart/     [한도윤]        #   DART 공시 수집·파싱
│   ├── eda/      [각자·공동]    #   추이 집계, 급증 시점 탐지
│   ├── llm/      [김한승]        #   LLM 감성 분류·이슈 추출·검수
│   └── rag/      [한도윤]        #   청킹·임베딩·질의응답
│
├── dashboard/                    # 📊 Streamlit 대시보드 (저장된 결과만 조회)
│   ├── app.py    [공동]          #   진입점, 상단 결론, 페이지 연결
│   ├── pages/                    #   화면별 파일 (김한승: 이슈 분석, 한도윤: 공시 Q&A)
│   ├── components/               #   필터·차트·Q&A UI 조각
│   └── data_access/              #   DB·벡터 DB 조회 함수
│
├── data/                         # 💾 데이터 (git 제외, 스크립트로 재생성)
│   ├── raw/news, raw/dart        #   원본 그대로
│   ├── processed/                #   정제 결과
│   ├── db/                       #   통합 DB 파일
│   ├── vectordb/                 #   임베딩 저장소
│   └── labels/   (커밋 O)        #   사람이 만든 표본 검수 결과
│
├── notebooks/                    # 🧪 탐색용 노트북 (김한승_issue / 한도윤_disclosure / shared)
├── outputs/                      # 📈 리포트·발표용 그림과 표
└── tests/                        # ✅ 테스트
```

---

## 폴더·파일별 목적

### 루트

| 파일 | 목적 |
|---|---|
| `README.md` | 프로젝트 소개, 실행 순서, 폴더 구조. 제출물 요구사항(실행 순서 기술)을 충족한다. |
| `requirements.txt` | `pip install -r requirements.txt` 한 번으로 전체 설치. `-r`로 아래 3개 파일을 포함하기만 하며 **직접 수정하지 않는다.** |
| `requirements/common.txt` | [공동] pandas, plotly, streamlit 등 공통 패키지. 추가 시 합의. |
| `requirements/issue.txt` | [김한승] LLM 분석에 필요한 패키지. 김한승만 수정한다. |
| `requirements/disclosure.txt` | [한도윤] DART 수집·LangChain·벡터 DB 패키지. 한도윤만 수정한다. |
| `.env.example` | 필요한 환경변수 이름만 적은 견본. 복사해 `.env`를 만든다. |
| `.gitignore` | `.env`, `data/` 내용물, 캐시 등을 git에서 제외해 키 노출과 대용량 충돌을 막는다. |
| `.gitattributes` | 줄바꿈을 LF로 통일해 Windows/Mac 간 "내용은 같은데 전부 바뀐" 충돌을 막는다. |
| `.github/pull_request_template.md` | PR 작성 시 담당 범위·키 노출·스키마 동기화를 체크하게 한다. |
| `.github/CODEOWNERS` | 담당 폴더가 바뀌면 담당자를 자동 리뷰어로 지정 (김한승 `han0210`, 한도윤 `DoyoonHan`). |
| `.streamlit/config.toml` | 대시보드 테마·서버 설정. |

### `docs/` — 문서

| 경로 | 목적 |
|---|---|
| `guidelines/` | 과제 가이드라인(`중간프로젝트_가이드_...md`), 일일 체크리스트 등 **참고용 문서**를 모아 둔다. 새로 받은 안내 문서도 여기에 넣는다. |
| `schema.md` | 뉴스·공시 통합 스키마. Day 1에 확정하면 이후 두 사람이 서로 기다리지 않고 병행할 수 있다. `src/common/schema.py`와 항상 같이 고친다. |
| `conventions.md` | 브랜치·커밋 규칙, 파일 소유권, 충돌 방지 방법 정리. |
| `daily_log/` | `YYYY-MM-DD_김한승.md`처럼 날짜·사람별 일지. 판단 근거를 남겨 리포트·회고에 쓴다. `_TEMPLATE.md`를 복사해 사용. |
| `report/01~07_*.md` | 리포트 7개 장(분석 목적·데이터·EDA·AI 이슈 분석·공시 Q&A·대시보드·회고)을 파일로 나눠 동시에 써도 충돌이 적다. |
| `presentation/` | 발표 PPT(포트폴리오용)와 대시보드 스크린샷. |

### `src/common/` — 공동 기반 [공동, 변경 시 PR로 합의]

| 파일 | 목적 |
|---|---|
| `config.py` | `.env` 로딩, 경로 상수(`DATA_DIR`, `DB_PATH`, `VECTORDB_DIR`). 키는 `os.getenv`로만 읽는다. |
| `schema.py` | 테이블·컬럼 정의 (`docs/schema.md`와 동일하게 유지). |
| `db.py` | DB 연결, 테이블 생성, 공통 읽기/쓰기 함수. |

### `src/news/` — 뉴스 [김한승]

| 파일 | 일정 | 목적 |
|---|---|---|
| `load_news.py` | Day 2 | 제공 뉴스(`data/raw/news`)를 스키마에 맞춰 DB에 적재. |
| `preprocess.py` | Day 3 | 정규표현식 정제, 중복 기사 제거, 키워드별 무관 기사 필터링. |

### `src/dart/` — DART 공시 [한도윤]

| 파일 | 일정 | 목적 |
|---|---|---|
| `corp_code.py` | Day 2 | `corpCode.xml`로 SK하이닉스·삼성전자 `corp_code` 확인. |
| `collect_list.py` | Day 2 | `list.json` 공시 목록 수집. 요청 간 딜레이, 원본 저장, 재실행 시 이미 받은 건 건너뛰기. |
| `collect_documents.py` | Day 2 | 공시서류원본파일 API로 원문 다운로드. |
| `parse_documents.py` | Day 2 | 원문에서 텍스트를 추출해 DB에 적재. |

### `src/eda/` — EDA

| 파일 | 담당 | 목적 |
|---|---|---|
| `news_trend.py` | 김한승 | 키워드·기업·일자별 기사량, 무관 기사 비중. |
| `disclosure_trend.py` | 한도윤 | 기업·공시유형·일자별 공시 건수. |
| `spike_detection.py` | 공동 | 이슈 급증 시점 탐지 및 저장. |

### `src/llm/` — LLM 이슈 분석 [김한승]

| 파일 | 일정 | 목적 |
|---|---|---|
| `prompts.py` | Day 4 | 감성 분류·이슈 추출 프롬프트 (버전 관리 → 리포트에 설계 과정 기록). |
| `classify.py` | Day 4 | 배치로 분류해 결과를 DB에 **미리 저장** (대시보드 실시간 호출 금지). |
| `validate_sample.py` | Day 4 | 표본 추출 → 사람 검수 CSV(`data/labels/`) → 정확도 계산. |

### `src/rag/` — 공시 Q&A [한도윤]

| 파일 | 일정 | 목적 |
|---|---|---|
| `chunking.py` | Day 5 | 공시 텍스트를 청크로 나누고 공시명·제출일·링크 메타데이터를 붙인다. |
| `build_index.py` | Day 5 | 임베딩 후 벡터 DB(`data/vectordb`)에 **미리 저장**. |
| `qa_chain.py` | Day 5 | LangChain 질의응답. 근거 공시를 표시하고, 근거가 없으면 답변을 거절한다. |

### `dashboard/` — Streamlit

| 파일 | 담당 | 목적 |
|---|---|---|
| `app.py` | 공동 | 진입점. 상단 결론과 페이지 연결만 두고 로직은 넣지 않아 충돌을 줄인다. |
| `pages/1_이슈_분석.py` | 김한승 | HBM 이슈 비중·급증 추이, 기업별 보도 점유·감성 비교 화면. |
| `pages/2_공시_QA.py` | 한도윤 | 기업별 공시 근거와 공시 Q&A 화면. |
| `components/filters.py` | 공동 | 기간·기업(SK하이닉스/삼성전자)·기술 태그 공통 필터. 모든 차트가 이 값을 받는다. |
| `components/conclusion.py` | 공동 | 상단 의사결정 결론 문구. |
| `components/issue_charts.py` | 김한승 | Plotly 이슈·감성 차트 함수. |
| `components/qa_view.py` | 한도윤 | 질문 입력, 답변, 근거 공시 표시 UI. |
| `data_access/issue_loader.py` | 김한승 | 뉴스·분석 결과 조회 (`st.cache_data`). |
| `data_access/disclosure_loader.py` | 한도윤 | 공시 데이터·벡터 DB 로드. |

### `data/` — 데이터 (git 제외)

| 경로 | 목적 |
|---|---|
| `raw/news/` | 제공 뉴스 원본. 수정하지 않는다. |
| `raw/dart/` | DART API 응답 원본(목록 JSON, 원문 zip). 재정제할 때 API를 다시 부르지 않기 위해 보관. |
| `processed/` | 정제·중간 결과(CSV/Parquet). |
| `db/` | 통합 DB 파일. |
| `vectordb/` | 공시 임베딩 저장소. |
| `labels/` | **커밋 대상.** 사람이 검수한 표본 라벨. 정확도 근거 자료. |

> 데이터는 git에 올리지 않습니다. 실행 순서대로 스크립트를 돌려 재생성하거나, 큰 DB·벡터 DB는 공유 드라이브로 주고받습니다.

### 기타

| 경로 | 목적 |
|---|---|
| `notebooks/김한승_issue`, `한도윤_disclosure`, `shared` | 탐색용 노트북. 사람별 폴더 분리, **출력 지우고 커밋**. 확정 로직은 `src/`로 옮긴다. |
| `outputs/figures/` | 차트 이미지 (자동 생성, git 제외). |
| `outputs/reports/` | 표본 검수 정확도표 등 리포트에 넣을 표. |
| `tests/test_news.py`, `tests/test_dart.py` | 담당별 테스트 파일 (김한승 / 한도윤). |

---

## 협업 규칙 요약 (자세히: [docs/conventions.md](docs/conventions.md))

1. **파일 맨 위 `담당:` 표시를 따른다.** 내 담당 파일만 수정하고, 공동 파일은 한 번에 한 사람만 수정한다.
2. **`main`에 직접 push하지 않는다.** `issue/작업명`(김한승), `disclosure/작업명`(한도윤), `common/작업명`(공동) 브랜치 → PR → 상대 리뷰 후 merge.
3. **작업 시작 전·PR 전 `git pull origin main`.**
4. **패키지 추가는 자기 `requirements/*.txt`에만.**
5. **API 키는 `.env`에만.** 코드·노트북 출력·발표자료에 키가 없는지 확인.
6. **스키마 변경은 `src/common/schema.py` + `docs/schema.md`를 같은 PR에서.**
