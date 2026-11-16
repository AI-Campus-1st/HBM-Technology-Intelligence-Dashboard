"""
DB 연결, 테이블 생성, 공통 조회/저장 함수(read_table, write_table), 두 컴퓨터의 DB 비교(--check).

두 사람은 각자 컴퓨터의 로컬 DB(data/db/hbm.db)에 적재한다. DB 파일은 주고받지 않고,
같은 코드 + 같은 입력 데이터로 각자 DB를 다시 만든다 (docs/conventions.md §5).
그래서 이 모듈은 다음을 보장한다.
- 연결할 때마다 FK 제약을 켠다 (PRAGMA foreign_keys = ON).
- write_table(mode="replace")는 '테이블 비우기 + 넣기'를 한 트랜잭션으로 해서,
  적재 스크립트를 몇 번 다시 돌려도 결과가 같다 (중간에 실패하면 원래 상태로 돌아간다).
- --check는 테이블별 행 수와 기본키 지문을 출력한다. 두 사람이 출력을 비교해 같으면 같은 DB다.

사용:
    python -m src.common.db            # DB·테이블 생성 (이미 있으면 그대로 둠)
    python -m src.common.db --rebuild  # DB 파일을 지우고 빈 테이블로 다시 생성
    python -m src.common.db --check    # 테이블별 행 수·기본키 지문·FK 위반 출력

담당: 공동 (변경 시 PR로 합의)
일정: Day 1~2
"""

import argparse
import hashlib
import sqlite3
from collections.abc import Iterable, Mapping
from pathlib import Path

import pandas as pd

from src.common import config, schema

WRITE_MODES = ("replace", "append", "upsert")


def connect(db_path: Path | str = config.DB_PATH) -> sqlite3.Connection:
    """DB에 연결한다. 폴더가 없으면 만들고, FK 제약을 켠다."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path | str = config.DB_PATH) -> Path:
    """스키마의 모든 테이블을 만든다. 이미 있는 테이블과 데이터는 건드리지 않는다."""
    conn = connect(db_path)
    try:
        schema.create_all(conn)
    finally:
        conn.close()
    return Path(db_path)


def rebuild_db(db_path: Path | str = config.DB_PATH) -> Path:
    """DB 파일을 지우고 빈 테이블로 다시 만든다. 스키마가 바뀌었거나 처음부터 다시 적재할 때 쓴다."""
    db_path = Path(db_path)
    for suffix in ("", "-wal", "-shm", "-journal"):
        Path(f"{db_path}{suffix}").unlink(missing_ok=True)
    return init_db(db_path)


def _table(name: str) -> schema.Table:
    if name not in schema.TABLES:
        raise ValueError(f"스키마에 없는 테이블입니다: {name} (가능: {', '.join(schema.TABLES)})")
    return schema.TABLES[name]


def _to_frame(rows: pd.DataFrame | Iterable[Mapping]) -> pd.DataFrame:
    return rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(list(rows))


def write_table(
    conn: sqlite3.Connection,
    table: str,
    rows: pd.DataFrame | Iterable[Mapping],
    mode: str = "replace",
) -> int:
    """행을 테이블에 저장하고 저장한 행 수를 돌려준다.

    Args:
        conn: connect()로 연 연결
        table: 스키마에 정의된 테이블명
        rows: DataFrame 또는 dict 목록. 스키마에 없는 컬럼이 있으면 오류를 낸다.
        mode:
            - "replace": 테이블을 비우고 넣는다 (기본값, 재실행해도 결과가 같다).
            - "upsert": 기본키가 같은 행은 덮어쓰고 나머지는 추가한다.
            - "append": 추가만 한다 (기본키가 겹치면 오류).

    다른 테이블이 참조 중인 행을 지우면(예: news_tag가 있는데 news를 replace) FK 오류가 나고
    아무것도 바뀌지 않는다. 이때는 `python -m src.common.db --rebuild` 후 실행 순서대로 다시 적재한다.
    """
    if mode not in WRITE_MODES:
        raise ValueError(f"mode는 {WRITE_MODES} 중 하나여야 합니다: {mode}")
    spec = _table(table)
    df = _to_frame(rows)

    known = [c.name for c in spec.columns]
    unknown = [c for c in df.columns if c not in known]
    if unknown:
        raise ValueError(f"{table} 테이블에 없는 컬럼입니다: {unknown}")
    columns = [c for c in known if c in df.columns]

    # NaN·pd.NA·NaT는 NULL로 저장한다.
    df = df[columns].astype(object).where(df[columns].notna(), None)
    values = df.itertuples(index=False, name=None)

    verb = {"replace": "INSERT", "append": "INSERT", "upsert": "INSERT OR REPLACE"}[mode]
    placeholders = ", ".join("?" for _ in columns)
    sql = f"{verb} INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"

    with conn:  # 한 트랜잭션: 중간에 실패하면 지운 행도 되돌린다.
        if mode == "replace":
            conn.execute(f"DELETE FROM {table}")
        if columns:
            conn.executemany(sql, values)
    return len(df)


def read_table(
    conn: sqlite3.Connection,
    table: str,
    columns: list[str] | None = None,
    where: str | None = None,
    params: tuple | Mapping = (),
) -> pd.DataFrame:
    """테이블을 DataFrame으로 읽는다. where에는 값 대신 ?·:name 자리표시자를 쓰고 params로 넘긴다."""
    spec = _table(table)
    known = [c.name for c in spec.columns]
    selected = columns or known
    unknown = [c for c in selected if c not in known]
    if unknown:
        raise ValueError(f"{table} 테이블에 없는 컬럼입니다: {unknown}")
    sql = f"SELECT {', '.join(selected)} FROM {table}"
    if where:
        sql += f" WHERE {where}"
    sql += f" ORDER BY {', '.join(spec.primary_key)}"
    return pd.read_sql_query(sql, conn, params=params)


def table_summary(conn: sqlite3.Connection) -> list[dict]:
    """테이블별 행 수와 기본키 지문(정렬한 기본키 값의 SHA-1 앞 12자리)을 돌려준다.

    두 컴퓨터에서 행 수와 지문이 모두 같으면 같은 행들이 들어 있는 것이다.
    (값 자체의 차이까지 보지는 않는다. 같은 코드·같은 입력이면 기본키가 같을 때 값도 같다.)
    """
    summary = []
    for spec in schema.TABLES.values():
        pk = ", ".join(spec.primary_key)
        digest = hashlib.sha1()
        count = 0
        for row in conn.execute(f"SELECT {pk} FROM {spec.name} ORDER BY {pk}"):
            digest.update(repr(row).encode("utf-8"))
            count += 1
        summary.append(
            {"table": spec.name, "owner": spec.owner, "rows": count, "pk_hash": digest.hexdigest()[:12] if count else "-"}
        )
    return summary


def foreign_key_violations(conn: sqlite3.Connection) -> list[tuple]:
    """FK 위반 행 목록 (테이블, rowid, 참조 테이블, FK 번호). 비어 있어야 정상이다."""
    return conn.execute("PRAGMA foreign_key_check").fetchall()


def print_check(db_path: Path | str = config.DB_PATH) -> bool:
    """--check 출력. FK 위반이 없으면 True."""
    db_path = Path(db_path)
    if not db_path.exists():
        print(f"DB가 없습니다: {db_path}\n먼저 `python -m src.common.db`를 실행하세요.")
        return False
    conn = connect(db_path)
    try:
        schema.create_all(conn)  # 새로 추가된 테이블이 있으면 0행으로 보이게 한다.
        rows = table_summary(conn)
        violations = foreign_key_violations(conn)
    finally:
        conn.close()

    print(f"DB     : {db_path}")
    print(f"기준일 : {config.REFERENCE_DATE:{config.DATE_FORMAT}}")
    print(f"{'테이블':<16}{'담당':<8}{'행 수':>10}  기본키 지문")
    for r in rows:
        print(f"{r['table']:<16}{r['owner']:<8}{r['rows']:>10,}  {r['pk_hash']}")
    print(f"FK 위반: {len(violations)}건")
    for v in violations[:10]:
        print(f"  {v}")
    return not violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="통합 DB 생성·재생성·점검")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--rebuild", action="store_true", help="DB 파일을 지우고 빈 테이블로 다시 만든다")
    group.add_argument("--check", action="store_true", help="테이블별 행 수·기본키 지문·FK 위반을 출력한다")
    parser.add_argument("--db", type=Path, default=config.DB_PATH, help="DB 파일 경로 (기본: data/db/hbm.db)")
    args = parser.parse_args(argv)

    if args.check:
        return 0 if print_check(args.db) else 1
    path = rebuild_db(args.db) if args.rebuild else init_db(args.db)
    print(f"{'다시 만듦' if args.rebuild else '준비됨'}: {path} (테이블 {len(schema.TABLES)}개)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
