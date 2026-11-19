"""
뉴스 SQL 집계 쿼리(sql/01~04_*.sql) 실행 → CSV 저장 (Day 3·5, 리포트 3.1·4장).

SQL 원문은 sql/ 폴더에 두고 이 모듈은 읽어서 실행만 한다. 쿼리 설명·기준은 각 .sql 파일 머리 주석에 있다.
- 01_news_monthly_dedup.sql      : 월별 수집 기사·중복(재배포) 기사·중복률 (중복 제거 증거)
- 02_hbm_monthly_share.sql       : 월별 HBM 기사 수·비중 + 전월 대비 변화(LAG)·3개월 이동평균·순위(윈도 함수)
- 03_issue_company_coverage.sql  : 급증 구간(issues)별 HBM 기사의 기업 점유 vs 구간 밖 (JOIN·기간 비교)
- 04_company_sentiment_monthly.sql: 기업별 LLM 감성 월별 추이·3개월 순감성·급증 달 표시 (Day 5, classify 다음)

실행 함수(run_query, output_path)는 한도윤의 src/dart/sql_report.py를 그대로 재사용하고,
이 모듈은 실행할 파일 범위(01~04 뉴스 쿼리)만 다르게 정한다.

실행: python -m src.eda.news_sql_report   (spike_detection·classify 다음 — 03·04는 issues, 04는 news_analysis를 읽는다. DB만 읽고 쓰지 않는다)
저장: outputs/reports/sql01~04_*.csv

담당: 김한승 (이슈 분석)
일정: Day 3 (04는 Day 5)
"""

from pathlib import Path

import pandas as pd

from src.common import config, db
from src.dart.sql_report import output_path, run_query

SQL_DIR = config.ROOT_DIR / "sql"
REPORTS_DIR = config.OUTPUTS_DIR / "reports"
QUERY_GLOB = "0[1-4]_*.sql"     # 김한승 담당 뉴스 쿼리
OUTSIDE_LABEL = "(급증 구간 밖)"  # 03 쿼리에서 어떤 issues 구간에도 속하지 않는 기사 묶음 이름

__all__ = ["SQL_DIR", "REPORTS_DIR", "OUTSIDE_LABEL", "query_files", "run_query", "main"]


def query_files(sql_dir: Path = SQL_DIR) -> list[Path]:
    """실행할 뉴스 .sql 파일 목록 (이름순)."""
    return sorted(sql_dir.glob(QUERY_GLOB))


def main(db_path: Path = config.DB_PATH, sql_dir: Path = SQL_DIR, reports_dir: Path = REPORTS_DIR) -> dict[str, pd.DataFrame]:
    """뉴스 쿼리를 모두 실행해 CSV로 저장하고 {파일 이름(stem): 결과}를 돌려준다."""
    conn = db.connect(db_path)
    try:
        results = {path.stem: run_query(conn, path) for path in query_files(sql_dir)}
    finally:
        conn.close()
    reports_dir.mkdir(parents=True, exist_ok=True)
    for name, df in results.items():
        out = output_path(Path(f"{name}.sql"), reports_dir)
        df.to_csv(out, index=False, encoding="utf-8-sig")
        shown = out.relative_to(config.ROOT_DIR) if out.is_relative_to(config.ROOT_DIR) else out
        print(f"{name}: {len(df):,}행 → {shown}")
    return results


if __name__ == "__main__":
    main()
