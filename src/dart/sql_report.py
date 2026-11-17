"""
공시 SQL 집계 쿼리(sql/05_*.sql) 실행 → CSV 저장 (Day 3, 리포트 3장).

SQL 원문은 sql/ 폴더에 두고 이 모듈은 읽어서 실행만 한다. 쿼리 설명·기준은 각 .sql 파일 머리 주석에 있다.
- 05_1_disclosure_events_vs_hbm_news.sql : 기업·월별 사건성 공시 건수 + HBM 기사 수 (같은 월 축)
- 05_2_disclosure_category_yoy.sql       : 기업·공시 성격별 12개월 구간 건수, 직전 구간 대비 증감, 원문·RAG 건수

실행: python -m src.dart.sql_report   (news_link --apply 다음. DB만 읽고 쓰지 않는다)
저장: outputs/reports/sql05_1_*.csv, sql05_2_*.csv (파일 이름은 .sql 이름을 따른다)

담당: 한도윤 (공시 분석)
일정: Day 3
"""

import sqlite3
from pathlib import Path

import pandas as pd

from src.common import config, db

SQL_DIR = config.ROOT_DIR / "sql"
REPORTS_DIR = config.OUTPUTS_DIR / "reports"
QUERY_GLOB = "05_*.sql"  # 한도윤 담당 공시 쿼리


def query_files(sql_dir: Path = SQL_DIR) -> list[Path]:
    """실행할 .sql 파일 목록 (이름순)."""
    return sorted(sql_dir.glob(QUERY_GLOB))


def run_query(conn: sqlite3.Connection, path: Path) -> pd.DataFrame:
    """.sql 파일 하나(SELECT 한 문장)를 실행해 DataFrame으로 돌려준다."""
    return pd.read_sql_query(path.read_text(encoding="utf-8"), conn)


def output_path(path: Path, reports_dir: Path = REPORTS_DIR) -> Path:
    """sql/05_1_xxx.sql → outputs/reports/sql05_1_xxx.csv"""
    return reports_dir / f"sql{path.stem}.csv"


def main(db_path: Path = config.DB_PATH, sql_dir: Path = SQL_DIR, reports_dir: Path = REPORTS_DIR) -> dict[str, pd.DataFrame]:
    conn = db.connect(db_path)
    try:
        results = {path.stem: run_query(conn, path) for path in query_files(sql_dir)}
    finally:
        conn.close()
    reports_dir.mkdir(parents=True, exist_ok=True)
    for name, df in results.items():
        out = output_path(Path(f"{name}.sql"), reports_dir)
        df.to_csv(out, index=False, encoding="utf-8-sig")
        print(f"{name}: {len(df):,}행 → {out.relative_to(config.ROOT_DIR) if out.is_relative_to(config.ROOT_DIR) else out}")
    return results


if __name__ == "__main__":
    main()
