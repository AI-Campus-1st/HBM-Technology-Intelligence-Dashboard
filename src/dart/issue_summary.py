"""
급증 구간 사건 요약(data/labels/issue_summary_v1.csv)을 점검하고 issues.summary에 반영한다 (리포트 3.5).

요약의 원본은 라벨 파일이다. spike_detection이 issues를 다시 만들 때 summary를 비우므로 DB가 아니라 파일에 둔다.
spike_detection 코드(김한승 담당)는 건드리지 않고, 이 모듈을 그 다음에 실행해 채운다.

점검 (check):
- 라벨 파일의 issue_id가 issues와 같은가 (빠진 구간·없는 구간)
- status가 미작성/초안/확정/제외 중 하나이고, 초안·확정이면 summary가, 제외면 note(제외 이유)가 있는가
- evidence_rcept_no가 모두 그 구간의 사람이 확인한 근거(issue_evidence verified=1)인가
- 그 구간의 확인된 근거 중 요약에 안 쓴 것 (경고만)

반영 (--apply): status=확정인 행만 issues.summary에 쓴다 (data/labels/README.md 규칙: 확정만 대시보드·리포트에 쓴다).
    확정이 아닌 구간의 summary는 비운다. 점검에서 문제가 있으면 쓰지 않는다.

실행: python -m src.dart.issue_summary            (점검만)
      python -m src.dart.issue_summary --apply    (spike_detection → issue_evidence 다음)

담당: 한도윤 (공시 근거 부분, 요약 확정은 김한승과 함께)
일정: Day 3 (요약 초안), Day 6 (점검·반영)
"""

import argparse
import sqlite3
from pathlib import Path

import pandas as pd

from src.common import config

SUMMARY_PATH = config.LABELS_DIR / "issue_summary_v1.csv"
STATUSES = ("미작성", "초안", "확정", "제외")  # 제외: 탐지됐지만 분석 대상에서 뺀 구간 (이유는 note, 리포트 3.5)


def load_summaries(path: Path | None = None) -> pd.DataFrame:
    df = pd.read_csv(path or SUMMARY_PATH, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    return df.apply(lambda col: col.str.strip())


def evidence_ids(value: str) -> list[str]:
    """'a; b' → ['a', 'b']"""
    return [x.strip() for x in str(value).split(";") if x.strip()]


def check(summaries: pd.DataFrame, issue_ids: list[str], verified: pd.DataFrame) -> tuple[list[str], list[str]]:
    """(문제, 경고). verified는 issue_evidence 중 verified=1 행 (issue_id, rcept_no)."""
    problems, warnings = [], []
    labeled = list(summaries["issue_id"])
    for iid in sorted(set(issue_ids) - set(labeled)):
        problems.append(f"{iid}: 라벨 파일에 없음")
    for iid in sorted(set(labeled) - set(issue_ids)):
        problems.append(f"{iid}: issues에 없는 구간")
    for iid in sorted({i for i in labeled if labeled.count(i) > 1}):
        problems.append(f"{iid}: 중복 행")

    ok = verified.groupby("issue_id")["rcept_no"].apply(set).to_dict()
    for r in summaries.itertuples(index=False):
        if r.status not in STATUSES:
            problems.append(f"{r.issue_id}: status '{r.status}'는 {'/'.join(STATUSES)} 중 하나여야 함")
        if r.status in ("초안", "확정") and not r.summary:
            problems.append(f"{r.issue_id}: {r.status}인데 summary가 비어 있음")
        if r.status == "제외" and not r.note:
            problems.append(f"{r.issue_id}: 제외인데 note(제외 이유)가 비어 있음")
        used = evidence_ids(r.evidence_rcept_no)
        for rno in used:
            if rno not in ok.get(r.issue_id, set()):
                problems.append(f"{r.issue_id}: {rno}는 이 구간의 확인된 근거(verified=1)가 아님")
        missing = sorted(ok.get(r.issue_id, set()) - set(used))
        if missing:
            warnings.append(f"{r.issue_id}: 확인된 근거 중 요약에 안 쓴 공시 {', '.join(missing)}")
    return problems, warnings


def confirmed_summaries(summaries: pd.DataFrame) -> dict[str, str]:
    return dict(summaries.loc[summaries["status"] == "확정", ["issue_id", "summary"]].itertuples(index=False))


def apply(conn: sqlite3.Connection, summaries: pd.DataFrame) -> int:
    """확정 행만 issues.summary에 쓰고 나머지 구간은 비운다. 쓴 행 수."""
    done = confirmed_summaries(summaries)
    conn.execute("UPDATE issues SET summary = NULL")
    conn.executemany("UPDATE issues SET summary = ? WHERE issue_id = ?", [(s, i) for i, s in done.items()])
    conn.commit()
    return len(done)


def read_db(conn: sqlite3.Connection) -> tuple[list[str], pd.DataFrame]:
    issue_ids = [r[0] for r in conn.execute("SELECT issue_id FROM issues ORDER BY issue_id")]
    verified = pd.read_sql_query("SELECT issue_id, rcept_no FROM issue_evidence WHERE verified = 1 AND rcept_no IS NOT NULL",
                                 conn)
    return issue_ids, verified


def main(do_apply: bool = False, db_path: Path | None = None, path: Path | None = None) -> int:
    summaries = load_summaries(path)
    with sqlite3.connect(db_path or config.DB_PATH) as conn:
        issue_ids, verified = read_db(conn)
        problems, warnings = check(summaries, issue_ids, verified)
        counts = summaries["status"].value_counts()
        print("상태: " + ", ".join(f"{s} {int(counts.get(s, 0))}" for s in STATUSES) + f" (전체 {len(summaries)}구간)")
        for w in warnings:
            print("경고:", w)
        for p in problems:
            print("문제:", p)
        if problems:
            print("문제가 있어 반영하지 않습니다." if do_apply else "")
            return 1
        if do_apply:
            n = apply(conn, summaries)
            print(f"issues.summary 반영: 확정 {n}구간 (나머지 {len(issue_ids) - n}구간은 비움)")
        else:
            print("점검 통과. 반영하려면 --apply")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="사건 요약 라벨 점검·issues.summary 반영")
    parser.add_argument("--apply", action="store_true", help="status=확정 행을 issues.summary에 쓴다")
    raise SystemExit(main(do_apply=parser.parse_args().apply))
