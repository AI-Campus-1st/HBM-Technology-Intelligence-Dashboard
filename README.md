# AI 기반 HBM 기술 경쟁 분석 — SK하이닉스 vs 삼성전자 기술 인텔리전스 대시보드

**HBM Technology Intelligence Dashboard** · 기획 v1.2

> **"HBM 경쟁에서 SK하이닉스와 삼성전자에 대한 시장의 관심과 이슈는 시기별로 어떻게 달라졌으며, 공시로 확인되는 대응과 애널리스트가 추가로 확인해야 할 기회·위험 신호는 무엇인가?"**

최근 3년(2023-10-19 ~ 2026-10-19) 반도체 뉴스와 SK하이닉스·삼성전자 DART 공시를 통합 분석하여 HBM 이슈의 **비중 변화와 급증 시점**을 탐지하고, 기업별 보도·감성 차이와 공시 근거를 비교합니다. 이를 통해 **근거와 한계를 명시하는 애널리스트용 기술 인텔리전스 대시보드**를 만듭니다.

**분석 흐름:** HBM 이슈 비중 변화 → 급증 시점 탐지 → 기업별(SK하이닉스·삼성전자) 보도·감성 비교 → 공시 근거 확인

| 항목 | 내용 |
|---|---|
| 기간 / 인원 | 7일 / 2인 1조 |
| 산업군 | 반도체 |
| 대상 기업 | **SK하이닉스** (비교: **삼성전자**) — 두 기업 모두 DART 공시 수집 |
| 분석 기술 범위 | **HBM 단독** (패키징·DRAM은 기사 수가 적어 HBM 기사 안의 보조 정보로만 사용, 2026-11-16 확정) |
| 뉴스 데이터 | 제공 반도체 묶음 7,177건 (2023-10-19 ~ 2026-10-19) — `반도체 수출 통제` · `반도체 세제 혜택` (규제 및 정책) / `반도체 R&D` (기술 및 트렌드) / `반도체 밸류체인` · `반도체 원자재` (공급망 및 인프라) |
| 분석 기간 | **2023-10-19 ~ 2026-10-19** (뉴스·공시 동일 기간, 월별 집계) |
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

- 기사 **절대량이 아니라 비중**으로 관심도를 판단한다. 분기별 수집 기사 수가 310~1,132건으로 크게 달라지기 때문이다.
- 보도 점유·감성은 실제 시장 점유율이나 사업 성과가 아니다.
- 회사 전체 R&D 지출은 HBM 투자액이 아니며, 사업 구조가 다른 삼성전자와 전체 수치를 직접 비교하지 않는다.
- 같은 시점에 뉴스와 공시가 있다고 해서 인과관계로 해석하지 않는다.

> 기획 상세(데이터 1차 점검 결과, 지표 정의, 검증 설계, 대시보드 구성, 일정)는 [docs/guidelines/초안_v1.2.md](docs/guidelines/초안_v1.2.md)를 참고합니다.

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
| 5-1 | `python -m src.dart.collect_attachments` | 한도윤 | 실적 공시 첨부 경영설명회 PDF(국문 27건) 수집·텍스트 추출 (4 다음. DART 웹 화면에서 받음. 공유받은 `data/raw/dart/attachments`가 있으면 `--extract`로 추출만, 네트워크 불필요) |
| 6 | `python -m src.dart.parse_documents` | 한도윤 | 공시 텍스트 DB 적재 + 정기보고서 R&D·투자 섹션 추출 (`--sections`면 섹션만 다시: `data/processed/disclosure_sections.csv`, `outputs/reports/disclosure_section_summary.csv`·`disclosure_rnd_capex.csv`) |
| 6-1 | `python -m src.dart.news_link` | 한도윤 | HBM 기사↔공시 연결 후보, 새 RAG 기준 미리보기 (`--apply`는 김한승과 기준 합의 후. 5-1 다음이면 첨부에 HBM이 있는 실적 공시도 RAG 대상) |
| 6-2 | `python -m src.rag.chunking` | 한도윤 | RAG 대상 공시 청크 (6-1 `--apply` 다음. 첨부는 쪽마다 청크. `data/processed/disclosure_chunks.jsonl`, 요약 `outputs/reports/disclosure_chunk_summary.csv`) |
| 7 | `python -m src.news.preprocess` | 김한승 | 제목 중복(재배포) 표시, `news_tag` 적재 (2 다음. 7을 처음 돌리거나 다시 돌렸으면 6-1 `news_link --apply` → 6-2 `chunking`을 다시 실행해 실제 태그·중복 제외를 반영) |
| 7-1 | `python -m src.eda.disclosure_trend` | 한도윤 | 공시 건수 추이 (6 다음이면 언제든. `outputs/reports/disclosure_*.csv`, `outputs/figures/disclosure_monthly.html`) |
| 7-2 | `python -m src.dart.sql_report` | 한도윤 | 공시 SQL 집계 `sql/05_*.sql` 실행 (7·6-1 `--apply` 다음. `outputs/reports/sql05_*.csv`) |
| 8 | `python -m src.eda.spike_detection` | 공동 | 이슈 급증 시점 (방식 B `rolling6m_2sigma_exclude_spikes_min10_v1` → `issues`, 미리보기 `--dry-run`, 비교 `--method-a`) |
| 8-1 | `python -m src.dart.issue_evidence` | 공동 | 급증 구간별 근거 공시 후보 → `issue_evidence` (8·6-1 다음. 사람 확인은 `data/labels/issue_evidence_review_v1.csv`의 `verified`를 채우고 다시 실행. 급증 기준을 바꿀 때는 `--clear` → 8 → 8-1) |
| 8-1a | `python -m src.dart.issue_summary` | 한도윤 | 사건 요약 라벨 `data/labels/issue_summary_v1.csv` 점검(구간·상태·근거 접수번호가 `verified=1`인지). `--apply`는 `status=확정` 행만 `issues.summary`에 쓴다 (8·8-1 다음. 8을 다시 돌리면 summary가 비므로 다시 실행) |
| 8-2 | `python -m src.eda.news_sql_report` | 김한승 | 뉴스 SQL 집계 `sql/01~03_*.sql` 실행 (8 다음 — 03이 `issues`를 읽음. `outputs/reports/sql01~03_*.csv`) |
| 9 | `python -m src.llm.classify` | 김한승 | HBM 기사 385건 기업별 감성(SK하이닉스·삼성전자)·이슈 키워드 → `news_analysis` (프롬프트 `sent_v1`, 7 다음. `--dry-run`은 대상·입력 글자 수만, `--limit N`은 앞 N건만. 다시 실행하면 남은 기사만 처리) |
| 10 | `python -m src.rag.build_index` | 한도윤 | 벡터 DB `data/vectordb/` (6-2 다음. OpenAI 임베딩 호출, `--dry-run`은 토큰 수만, `--query "질문"`은 검색만. 김한승은 실행하지 않고 공유 드라이브의 vectordb zip을 풀어 쓴다) |
| 10-1 | `python -m src.rag.qa_chain "질문"` | 한도윤 | 공시 근거 질의응답 (10 다음. `--samples`는 예시 질문 9개 → `outputs/reports/qa_samples.csv`, 대시보드용 저장 답변 `qa_samples.json`. LLM은 `config.LLM_MODEL`) |
| 10-2 | `python -m src.rag.evaluate` | 한도윤 | 공시 Q&A 평가 (10-1 다음. 평가 질문 `data/labels/qa_eval_v1.csv` 24문항 → `outputs/reports/qa_eval_v1.csv`·`qa_eval_v1_summary.csv`. 질문마다 LLM 1회) |
| 11 | `streamlit run dashboard/app.py` | 공동 | 대시보드 실행 |

> 2·7·9(김한승)와 3~6·10(한도윤)은 서로 독립이라 병행할 수 있습니다.

**각자 로컬 DB 맞추기:** DB 파일은 주고받지 않고, 같은 코드 + 같은 입력(DART 원본 zip, LLM 결과 파일)으로 각자 다시 만듭니다. 자세한 규칙은 [`docs/conventions.md` §5](docs/conventions.md)를 봅니다.

| 명령 | 용도 |
|---|---|
| `python -m src.common.db --rebuild` | DB를 지우고 빈 테이블로 다시 생성 (스키마 변경 후, 처음부터 다시 적재할 때) |
| `python -m src.common.db --check` | 테이블별 행 수·기본키 지문·FK 위반 출력 → 두 사람 출력이 같으면 같은 DB |

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
├── sql/                          # 🗃️ SQL 분석 쿼리 (01~04 김한승 뉴스, 05 한도윤 공시)
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
| `db.py` | DB 연결(FK 켜기), 테이블 생성·재생성, `read_table`·`write_table`(재실행해도 같은 결과), `--check`로 두 컴퓨터 DB 비교. |

### `src/news/` — 뉴스 [김한승]

| 파일 | 일정 | 목적 |
|---|---|---|
| `load_news.py` | Day 2 | 제공 뉴스(`data/raw/news`)를 스키마에 맞춰 DB에 적재. |
| `preprocess.py` | Day 3 | 정규표현식 정제, 중복 기사 제거, 키워드별 무관 기사 필터링. |

### `src/dart/` — DART 공시 [한도윤]

| 파일 | 일정 | 목적 |
|---|---|---|
| `corp_code.py` | Day 1 | `corpCode.xml`로 SK하이닉스·삼성전자 `corp_code` 확인. |
| `collect_list.py` | Day 2 | `list.json` 공시 목록 수집 (기간 `20231019`~`20261019`, `config.DART_BGN_DE`~`DART_END_DE`). 요청 간 딜레이, 원본 저장, 재실행 시 이미 받은 건 건너뛰기. |
| `collect_documents.py` | Day 2 | 공시서류원본파일 API로 원문 다운로드. |
| `collect_attachments.py` | Day 4 | 실적 공시의 첨부 경영설명회 PDF(국문)를 DART 웹 화면에서 받아 쪽별 텍스트 추출 (OpenAPI zip에는 첨부가 없음). [기재정정]의 첨부는 정정 전 원래 공시 번호로 받는다. |
| `parse_documents.py` | Day 2~3 | 원문에서 텍스트를 추출해 DB에 적재. 정기보고서를 'II. 사업의 내용' 소제목(사업·제품·투자·연구개발)과 삼성전자 연구개발실적(상세)으로 나누고, R&D 비용·매출 대비 비율·시설투자액을 뽑는다. |
| `relevance_review.py` | Day 2~3 | 공시 관련성 표본 검수 (sample → 라벨 → score). |
| `issue_evidence.py` | Day 3 | 급증 구간(`issues`)별 근거 공시 후보: 구간 안 기사와 연결된 공시(`키워드`) + 구간 안 사건성 공시(`기간`). 사람 확인 결과(`data/labels/issue_evidence_review_v1.csv`)를 반영해 `issue_evidence`를 다시 쓴다. |
| `issue_summary.py` | Day 6 | 사건 요약 라벨 점검과 `issues.summary` 반영(확정 행만). `spike_detection`은 고치지 않고 그 다음에 실행한다. |
| `sql_report.py` | Day 3 | `sql/05_*.sql` 공시 집계 쿼리를 실행해 `outputs/reports/sql05_*.csv`로 저장. |
| `news_link.py` | Day 3 | HBM 기사와 공시 연결(`link_v2`: 주 대상 기업·±7일·주제) → `issue_evidence` 후보, RAG 대상 재선정(A 정기공시 + HBM 언급 + 뉴스 연결, 실적 주제만으로 연결된 공시는 제외). |

### `sql/` — SQL 분석 쿼리

| 파일 | 담당 | 목적 |
|---|---|---|
| `01_news_monthly_dedup.sql` | 김한승 | 월별 수집·중복(재배포)·중복 제외 기사 수와 중복률 (재귀 CTE로 0건 달 채움). 분석 분모의 근거. |
| `02_hbm_monthly_share.sql` | 김한승 | 월별 HBM 기사 수·비중, 전월 대비 변화(`LAG`)·3개월 이동평균·비중 순위(`RANK`). `news_trend.monthly_hbm`과 같은 값인지 테스트로 대조. |
| `03_issue_company_coverage.sql` | 김한승 | 급증 구간(`issues`)별 HBM 기사의 SK하이닉스·삼성전자 점유 vs 구간 밖 (JOIN·기간 비교). |
| `05_1_disclosure_events_vs_hbm_news.sql` | 한도윤 | 기업·월별 사건성 공시 건수와 HBM 기사 수를 같은 월 축에 (재귀 CTE로 0건 달 채움). 급증 구간의 근거 공시 후보 찾기. |
| `05_2_disclosure_category_yoy.sql` | 한도윤 | 기업·공시 성격별 12개월 구간(Y1~Y3) 건수, 직전 구간 대비 증감(`LAG`), 원문 확보·RAG 대상 건수. |

### `src/eda/` — EDA

| 파일 | 담당 | 목적 |
|---|---|---|
| `news_trend.py` | 김한승 | 월별 기사량·HBM 비중·기업 점유, 카테고리별 무관 기사 비중. |
| `news_sql_report.py` | 김한승 | `sql/01~03_*.sql` 뉴스 집계 쿼리 실행 → `outputs/reports/sql01~03_*.csv` (실행 함수는 `src/dart/sql_report.py` 재사용). |
| `disclosure_trend.py` | 한도윤 | 기업 × 유형 × 월 공시 건수, 공시 성격(투자·실적·풍문 등) 분류, 사건성 공시 타임라인. 필터 인자를 받아 대시보드에서 재사용. |
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
| `chunking.py` | Day 3 | RAG 대상 공시를 청크(1,000자, 겹침 150자)로 나누고 공시명·제출일·링크·섹션 메타데이터를 붙인다. 정기보고서는 사업·제품·투자·연구개발 섹션만, 표는 행 단위로 묶어서 자른다. |
| `build_index.py` | Day 5 | 청크를 `text-embedding-3-small`로 임베딩해 Chroma(`data/vectordb`, 컬렉션 `disclosure_chunks`)에 **미리 저장**. `manifest.json`에 모델·청크 수·청크 지문을 남겨 공유본을 맞춰 본다. |
| `qa_chain.py` | Day 5 | 공시 근거 질의응답. 기업 필터(비교 질문은 기업별 검색) → 벡터 후보 40개 + 키워드(BM25) RRF 재정렬 → `gpt-6-luna` 구조화 답변. 출처(공시명·제출일·링크·첨부 쪽)를 붙이고, 검색 거리 기준·LLM 판단으로 근거가 없으면 거절한다. |
| `evaluate.py` | Day 5 | 평가 질문(정답 근거·핵심 사실)으로 검색 적중(하이브리드 vs 벡터만)·답변 정확·거절 정확·위임장(D) 비중·거리 분포를 잰다. |

### `dashboard/` — Streamlit

| 파일 | 담당 | 목적 |
|---|---|---|
| `app.py` | 공동 | 진입점. 상단 결론과 페이지 연결만 두고 로직은 넣지 않아 충돌을 줄인다. |
| `pages/1_이슈_분석.py` | 김한승 | HBM 이슈 비중·급증 추이, 기업별 보도 점유·감성 비교 화면. |
| `pages/2_공시_QA.py` | 한도윤 | 공시 Q&A 화면: 예시 질문은 저장된 답변(API 호출 없음), 직접 질문은 실시간 → 답변·근거 공시 카드(DART 링크·발췌), 거절 표시, 검색 대상 공시 101건 목록(기업·유형 필터). |
| `components/filters.py` | 공동 | 기간·기업(SK하이닉스/삼성전자)·카테고리·기술 태그 공통 필터. 모든 차트가 이 값을 받는다. |
| `components/conclusion.py` | 공동 | 상단 의사결정 결론 문구. |
| `components/issue_charts.py` | 김한승 | Plotly 이슈·감성 차트 함수. |
| `components/qa_view.py` | 한도윤 | 답변·근거 카드·공시 목록 HTML과 페이지 전용 어두운 테마(Spotify 디자인 문서 참조). |
| `data_access/issue_loader.py` | 김한승 | 뉴스·분석 결과 조회 (`st.cache_data`). |
| `data_access/disclosure_loader.py` | 한도윤 | RAG 대상 공시 목록·벡터 DB 매니페스트·평가 요약 읽기, 벡터 DB·LLM 1회 로드(`st.cache_resource`). |

### `data/` — 데이터 (git 제외)

| 경로 | 목적 |
|---|---|
| `raw/news/` | 제공 뉴스 원본. 수정하지 않는다. 분석에 쓰는 파일은 `config.NEWS_CSV`로 지정한다. |
| `raw/dart/` | DART API 응답 원본(목록 JSON, 원문 zip). 재정제할 때 API를 다시 부르지 않기 위해 보관. |
| `processed/` | 정제·중간 결과(CSV/Parquet). |
| `db/` | 통합 DB 파일. |
| `vectordb/` | 공시 임베딩 저장소. |
| `labels/` | **커밋 대상.** 사람이 검수한 표본 라벨. 정확도 근거 자료. |

> 데이터는 git에 올리지 않습니다. 각자 실행 순서대로 스크립트를 돌려 DB를 재생성하고, DART 원본·LLM 결과·벡터 DB만 공유 드라이브로 주고받습니다 (`docs/conventions.md` §5).

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
