# 협업 규칙 (merge conflict 최소화)

## 1. 파일 소유권
- 모든 파일 맨 위 docstring에 `담당: A / B / 공동`이 적혀 있다.
- **자기 담당 파일만 수정한다.** 상대 담당 파일을 고쳐야 하면 먼저 말하거나 이슈를 남긴다.
- `공동 (변경 시 PR로 합의)` 파일(`src/common/*`, `dashboard/components/filters.py`, `dashboard/app.py`)은 한 번에 한 사람만 수정한다.

## 2. 브랜치
- `main`: 항상 실행 가능한 상태. 직접 push 금지.
- 작업 브랜치: `a/<작업>` 또는 `b/<작업>` (예: `a/news-preprocess`, `b/dart-collect`)
- 공동 작업: `common/<작업>` (예: `common/schema`)
- 작업 시작 전 `git pull origin main`, PR 올리기 전에도 한 번 더 main을 반영한다.

## 3. 커밋 메시지
`[A|B|공동] Day N: 내용` 예) `[B] Day 2: list.json 수집 재실행 지원`

## 4. 충돌을 피하는 장치
| 자주 충돌하는 곳 | 이 프로젝트의 해결 방법 |
|---|---|
| requirements.txt | `requirements/common·issue·disclosure.txt`로 나눠 각자 자기 파일에만 추가 |
| 대시보드 한 파일 | `pages/`, `components/`, `data_access/`를 담당별 파일로 분리 |
| 노트북(.ipynb) | `notebooks/A_issue`, `B_disclosure`로 폴더 분리, 출력 지우고 커밋 |
| 데이터·DB 파일 | git에 올리지 않고 수집 스크립트로 재생성 |
| 회의록·일지 | `docs/daily_log/YYYY-MM-DD_A.md`처럼 날짜+사람별 파일 |
| 리포트 | `docs/report/` 장별 파일로 분리 |
| 줄바꿈(CRLF/LF) | `.gitattributes`로 LF 통일 |

## 5. 데이터 공유
- `data/` 안 내용은 git에 올리지 않는다. 같은 결과가 필요하면 README 실행 순서대로 스크립트를 돌리거나, 용량이 큰 DB/벡터 DB는 공유 드라이브로 전달한다.
- 사람이 만든 표본 검수 결과(`data/labels/`)만 커밋한다.
