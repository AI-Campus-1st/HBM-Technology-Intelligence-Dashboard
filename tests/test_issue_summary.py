"""
사건 요약 점검·반영(src/dart/issue_summary.py) 테스트.

담당: 한도윤 (공시 분석)
일정: Day 6
"""

import sqlite3

import pandas as pd

from src.dart import issue_summary as isum


def summaries(**over):
    rows = [
        {"issue_id": "I1", "period": "2024-10", "summary": "요약1", "evidence_rcept_no": "a; b", "status": "확정",
         "reviewer": "한도윤", "note": ""},
        {"issue_id": "I2", "period": "2024-12", "summary": "요약2", "evidence_rcept_no": "c", "status": "초안",
         "reviewer": "claude_1차", "note": ""},
    ]
    for k, v in over.items():
        rows[0][k] = v
    return pd.DataFrame(rows)


VERIFIED = pd.DataFrame({"issue_id": ["I1", "I1", "I2", "I2"], "rcept_no": ["a", "b", "c", "d"]})


def test_evidence_ids():
    assert isum.evidence_ids("a; b ;") == ["a", "b"] and isum.evidence_ids("") == []


def test_check_passes_and_warns_unused_evidence():
    problems, warnings = isum.check(summaries(), ["I1", "I2"], VERIFIED)
    assert problems == [] and warnings == ["I2: 확인된 근거 중 요약에 안 쓴 공시 d"]


def test_check_finds_problems():
    problems, _ = isum.check(summaries(evidence_rcept_no="a; x", status="완료"), ["I1", "I3"], VERIFIED)
    assert "I3: 라벨 파일에 없음" in problems and "I2: issues에 없는 구간" in problems
    assert any("x는 이 구간의 확인된 근거" in p for p in problems) and any("status '완료'" in p for p in problems)
    problems, _ = isum.check(summaries(summary=""), ["I1", "I2"], VERIFIED)
    assert problems == ["I1: 확정인데 summary가 비어 있음"]


def test_apply_writes_confirmed_only(tmp_path):
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.execute("CREATE TABLE issues (issue_id TEXT, summary TEXT)")
    conn.executemany("INSERT INTO issues VALUES (?, ?)", [("I1", None), ("I2", "옛 요약")])
    assert isum.apply(conn, summaries()) == 1
    assert dict(conn.execute("SELECT issue_id, summary FROM issues")) == {"I1": "요약1", "I2": None}


def test_label_file_passes_check_against_its_own_evidence():
    """커밋된 라벨 파일: 형식이 맞고, 근거 접수번호가 근거 라벨 파일의 verified=1 행에 있다 (DB 없이)."""
    from src.dart import issue_evidence

    df = isum.load_summaries()
    review = issue_evidence.load_review()
    verified = review.loc[review["verified"].astype(str) == "1", ["issue_id", "rcept_no"]]
    problems, _ = isum.check(df, list(df["issue_id"]), verified)
    assert problems == []


def test_excluded_status_needs_reason_and_is_not_applied(tmp_path):
    problems, _ = isum.check(summaries(status="제외", note=""), ["I1", "I2"], VERIFIED)
    assert "I1: 제외인데 note(제외 이유)가 비어 있음" in problems
    problems, _ = isum.check(summaries(status="제외", note="공시로 확인 안 됨"), ["I1", "I2"], VERIFIED)
    assert problems == []
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.execute("CREATE TABLE issues (issue_id TEXT, summary TEXT)")
    conn.executemany("INSERT INTO issues VALUES (?, ?)", [("I1", "옛 요약"), ("I2", None)])
    isum.apply(conn, summaries(status="제외", note="이유"))
    assert dict(conn.execute("SELECT issue_id, summary FROM issues"))["I1"] is None
