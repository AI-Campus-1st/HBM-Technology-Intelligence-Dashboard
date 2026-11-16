"""
DB 공통 함수(src/common/db.py) 테스트. 임시 폴더의 DB만 쓰고 data/db는 건드리지 않는다.

- 적재를 다시 실행해도 결과가 같은지 (replace 모드)
- 실패하면 기존 데이터가 남는지 (트랜잭션)
- 같은 데이터면 기본키 지문이 같은지 (두 컴퓨터 비교용 --check)

담당: 공동 (변경 시 PR로 합의)
일정: Day 2
"""

import sqlite3

import pandas as pd
import pytest

from src.common import db


def news_rows(ids):
    return [
        {"news_id": i, "published_at": "2024-01-01", "title": f"제목 {i}", "url": f"https://example.com/{i}"}
        for i in ids
    ]


@pytest.fixture
def conn(tmp_path):
    path = db.init_db(tmp_path / "test.db")
    c = db.connect(path)
    yield c
    c.close()


def test_connect_enables_foreign_keys(conn):
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_replace_is_idempotent(conn):
    db.write_table(conn, "news", news_rows(["a", "b"]))
    db.write_table(conn, "news", news_rows(["a", "b"]))
    assert len(db.read_table(conn, "news")) == 2


def test_replace_rolls_back_on_error(conn):
    db.write_table(conn, "news", news_rows(["a"]))
    bad = news_rows(["b"])
    bad[0]["title"] = None  # NOT NULL 위반
    with pytest.raises(sqlite3.IntegrityError):
        db.write_table(conn, "news", bad)
    assert db.read_table(conn, "news")["news_id"].tolist() == ["a"]


def test_upsert_overwrites_same_key(conn):
    db.write_table(conn, "news", news_rows(["a"]))
    db.write_table(conn, "news", [{**news_rows(["a"])[0], "title": "새 제목"}, *news_rows(["b"])], mode="upsert")
    df = db.read_table(conn, "news")
    assert df["news_id"].tolist() == ["a", "b"]
    assert df.loc[0, "title"] == "새 제목"


def test_dataframe_nan_and_numpy_ints(conn):
    df = pd.DataFrame(news_rows(["a"]))
    df["content"] = float("nan")
    df["is_duplicate"] = pd.Series([0], dtype="int64")
    db.write_table(conn, "news", df)
    row = db.read_table(conn, "news").iloc[0]
    assert row["content"] is None
    assert row["is_duplicate"] == 0


def test_unknown_table_or_column_rejected(conn):
    with pytest.raises(ValueError):
        db.write_table(conn, "nope", [])
    with pytest.raises(ValueError):
        db.write_table(conn, "news", [{**news_rows(["a"])[0], "extra": 1}])


def test_replace_parent_with_children_fails_without_change(conn):
    db.write_table(conn, "news", news_rows(["a"]))
    db.write_table(
        conn,
        "news_tag",
        [{"news_id": "a", "tag_type": "tech", "tag": "HBM", "relevance": "핵심",
          "in_title": 1, "body_count": 3, "rule_version": "regex_v2"}],
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.write_table(conn, "news", news_rows(["b"]))
    assert db.read_table(conn, "news")["news_id"].tolist() == ["a"]


def test_summary_same_for_same_data_regardless_of_order(tmp_path):
    results = []
    for name, ids in (("one.db", ["a", "b", "c"]), ("two.db", ["c", "a", "b"])):
        c = db.connect(db.init_db(tmp_path / name))
        db.write_table(c, "news", news_rows(ids))
        results.append(db.table_summary(c))
        c.close()
    assert results[0] == results[1]
    news = next(r for r in results[0] if r["table"] == "news")
    assert news["rows"] == 3


def test_rebuild_clears_data(tmp_path):
    path = tmp_path / "test.db"
    c = db.connect(db.init_db(path))
    db.write_table(c, "news", news_rows(["a"]))
    c.close()
    db.rebuild_db(path)
    c = db.connect(path)
    assert db.read_table(c, "news").empty
    c.close()


def test_cli_check(tmp_path, capsys):
    path = tmp_path / "test.db"
    assert db.main(["--db", str(path), "--check"]) == 1  # 아직 없음
    assert db.main(["--db", str(path)]) == 0
    assert db.main(["--db", str(path), "--check"]) == 0
    assert "FK 위반: 0건" in capsys.readouterr().out
