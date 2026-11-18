# 협업 규칙 (merge conflict 최소화)

## 1. 파일 소유권
- 모든 파일 맨 위 docstring에 `담당: 김한승 / 한도윤 / 공동`이 적혀 있다.
- **자기 담당 파일만 수정한다.** 상대 담당 파일을 고쳐야 하면 먼저 말하거나 이슈를 남긴다.
- `공동 (변경 시 PR로 합의)` 파일(`src/common/*`, `dashboard/components/filters.py`, `dashboard/app.py`)은 한 번에 한 사람만 수정한다.

## 2. 브랜치
- `main`: 항상 실행 가능한 상태. 직접 push 금지.
- 작업 브랜치: 김한승은 `issue/<작업>`, 한도윤은 `disclosure/<작업>` (예: `issue/news-preprocess`, `disclosure/dart-collect`)
- 공동 작업: `common/<작업>` (예: `common/schema`)
- 작업 시작 전 `git pull origin main`, PR 올리기 전에도 한 번 더 main을 반영한다.

## 3. 커밋 메시지
`[김한승|한도윤|공동] Day N: 내용` 예) `[한도윤] Day 2: list.json 수집 재실행 지원`

## 4. 충돌을 피하는 장치
| 자주 충돌하는 곳 | 이 프로젝트의 해결 방법 |
|---|---|
| requirements.txt | `requirements/common·issue·disclosure.txt`로 나눠 각자 자기 파일에만 추가 |
| 대시보드 한 파일 | `pages/`, `components/`, `data_access/`를 담당별 파일로 분리 |
| 노트북(.ipynb) | `notebooks/김한승_issue`, `한도윤_disclosure`로 폴더 분리, 출력 지우고 커밋 |
| 데이터·DB 파일 | git에 올리지 않고 수집 스크립트로 재생성 |
| 회의록·일지 | `docs/daily_log/YYYY-MM-DD_김한승.md`처럼 날짜+사람별 파일 |
| 리포트 | `docs/report/` 장별 파일로 분리 |
| 줄바꿈(CRLF/LF) | `.gitattributes`로 LF 통일 |

## 5. 데이터 공유 (각자 로컬 DB)
두 사람은 각자 컴퓨터의 `data/db/hbm.db`에 적재한다. **DB 파일은 주고받지 않는다.** 같은 코드와 같은 입력으로 각자 DB를 다시 만든다.

### 원칙
- **스키마·연결은 git 하나로:** 테이블 구조는 `src/common/schema.py`, 연결·읽기·쓰기는 `src/common/db.py`만 쓴다. 스키마를 바꾸면 PR로 합의하고, 상대에게 "pull 후 `--rebuild`" 하라고 알린다.
- **적재 스크립트는 자기 테이블만, 다시 돌려도 같은 결과:** `db.write_table(..., mode="replace")`(테이블 비우기 + 넣기, 한 트랜잭션)를 쓴다.
  - 김한승: `news`, `news_tag`, `news_analysis`, `issues` / 한도윤: `disclosure` / 공동: `issue_evidence`
  - `issue_evidence`는 `news`·`disclosure`를 참조하므로 두 적재가 끝난 뒤에 넣는다.
- **DB 대신 입력을 공유한다:**

| 데이터 | 만드는 사람 | 공유 방법 |
|---|---|---|
| 뉴스 CSV (`data/raw/news/`) | 제공 | 둘 다 같은 제공 파일 사용 (`config.NEWS_CSV`) |
| DART 원본 (`data/raw/dart/`) | 한도윤 | 수집 후 폴더를 zip으로 공유 드라이브에 올림. 김한승은 풀어서 `parse_documents`만 실행 (API 키·호출 불필요). 첨부 PDF(`data/raw/dart/attachments/`)도 같은 zip에 넣는다. 받은 쪽은 `collect_attachments --extract`로 텍스트만 추출 |
| LLM 분류 결과 | 김한승 | 다시 만들면 비용이 들고 결과가 달라지므로 `data/processed/`에 파일(CSV 등)로 저장해 공유. DB 적재는 그 파일을 읽어서 한다 |
| 벡터 DB (`data/vectordb/`) | 한도윤 | `build_index` 후 폴더를 zip으로 공유 드라이브에 올림. 받은 쪽은 풀기만 한다 (다시 임베딩하지 않음). `data/vectordb/manifest.json`의 `chunks_fingerprint`가 상대 `build_index --dry-run`의 지문과 같으면 같은 청크로 만든 DB다 |

- 사람이 만든 표본 검수 결과(`data/labels/`)만 git에 커밋한다. 나머지 `data/`는 커밋하지 않는다.

### 맞춰 보기 (하루 끝, 또는 상대 데이터가 바뀌었을 때)
1. `git pull origin main`, 상대가 올린 원본(DART zip, LLM 결과 파일)을 받아 같은 경로에 둔다.
2. `python -m src.common.db --rebuild` 후 README 실행 순서대로 다시 적재한다.
3. `python -m src.common.db --check` 출력을 서로 비교한다. **테이블별 행 수와 기본키 지문이 같고 FK 위반이 0건**이면 같은 DB다.
   - 지문은 기본키만 보므로 값의 차이는 잡지 못한다. 그래서 `disclosure.rag_target`은 RAG 대상 건수(101건, 첨부 반영 전 75건)로, `issue_evidence.verified`는 `python -m src.dart.issue_evidence` 출력의 '사람 확인 N행'으로 따로 맞춰 본다.
4. 다르면 어느 테이블이 다른지 보고 그 테이블 담당자가 입력 파일·코드 버전을 확인한다. 결과를 작업 일지에 적는다.
