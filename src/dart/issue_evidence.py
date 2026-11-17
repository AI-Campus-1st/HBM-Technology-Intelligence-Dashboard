"""
급증 구간(issues)마다 근거 공시 후보를 골라 issue_evidence에 넣는다 (Day 3, 리포트 3.5).

자동 후보 두 종류 (모두 verified=0으로 시작한다. 사람이 확인한 행만 대시보드 근거 카드에 올린다):
    키워드: 구간 안에 발행된 HBM 기사와 news_link(link_v2)로 연결된 공시. 공시 하나당 1행이고,
            news_id에는 대표 기사(핵심 우선 → 공시와 날짜가 가까운 순 → 이른 순)를 넣는다.
            '실적' 주제 연결도 넣는다 (RAG 선정에서만 빼고 근거 후보에는 남기기로 함, news_link 참고).
    기간:   구간 시작 PERIOD_LEAD_DAYS(7)일 전 ~ 구간 끝에 제출된 사건성 공시(disclosure_trend.EVENT_CATEGORIES) 중
            키워드 후보가 아닌 것. 기사 연결 없이 시점만 겹친 공시라 news_id는 비운다.
            구간 직전 공시는 보도가 공시 뒤에 몰리는 경우를 보려고 넣는다 (예: 신규시설투자 공시 → 다음 날 보도).

후보 범위 (SCOPES, 김한승과 합의 대기 — 초안 v1.2 §11 논의 질문 7):
    broad (기본, 한도윤 안): 키워드 후보 = 대표 기사가 HBM '핵심'이거나, 공시가 풍문·해명·투자·설비·사업계획
    core  (김한승 안):       키워드 후보 = HBM '핵심' 기사가 있는 연결만
    '기간' 후보는 기사와 무관하므로 범위와 상관없이 같다.

사람 검수 (각자 DB를 다시 만들어도 같은 결과가 나오도록 git의 라벨 파일로 공유한다):
    data/labels/issue_evidence_review_v1.csv (issue_id, rcept_no, news_id, match_type, verified, note, reviewer)
    - 실행할 때마다 새 후보를 빈 verified로 추가하고, 채운 행(verified 0/1 또는 note)과 '수동' 행은 그대로 둔다.
      더는 후보가 아닌 빈 행은 지운다.
    - 맨 끝 key 열이 진짜 키다. Excel로 열어 저장해도(rcept_no 지수 표기, cp949) key로 복구해서 읽는다.
    - verified=1이면 DB에 1, 0이면 기각(DB 0, note에 '기각')으로 넣는다. '수동' 행은 사람이 직접 추가한 근거다.

DB 반영: issue_evidence를 통째로 다시 쓴다 (replace). evidence_id는 정렬 순서로 1부터 매긴다 →
    같은 코드·입력·라벨이면 두 사람 DB의 --check 지문이 같다.
    spike_detection은 issue_evidence가 참조하는 issues 행을 지우지 않고 멈춘다. 급증 기준이 바뀌면
    --clear로 issue_evidence를 비운 뒤 spike_detection → issue_evidence 순서로 다시 돌린다 (사람 확인은 라벨 파일에 남는다).

실행: python -m src.dart.issue_evidence             (spike_detection·news_link 다음)
      python -m src.dart.issue_evidence --scope core
      python -m src.dart.issue_evidence --dry-run   (DB·라벨 파일은 그대로, 후보 CSV만)
      python -m src.dart.issue_evidence --clear     (issue_evidence만 비운다. 급증 기준 변경 전)
저장: outputs/reports/issue_evidence_candidates.csv (검토용: 공시명·제출일·링크·대표 기사 제목)

담당: 공동 (공시 근거 부분 한도윤)
일정: Day 3
"""

import argparse
from datetime import timedelta
from pathlib import Path

import pandas as pd

from src.common import config, db
from src.dart import news_link
from src.eda import disclosure_trend

EVIDENCE_VERSION = "evidence_v1"
PERIOD_LEAD_DAYS = 7  # '기간' 후보: 구간 시작 며칠 전 공시부터 볼지 (news_link.WINDOW_DAYS와 같게)
SCOPES = ("broad", "core")
DEFAULT_SCOPE = "broad"
# broad 범위에서 '관련' 기사로만 연결돼도 후보로 두는 공시 성격 (기사 사실을 회사가 직접 밝힌 공시)
BROAD_CATEGORIES = frozenset({"풍문·해명", "투자·설비", "사업계획"})
# J 계열사 거래는 분기마다 FAB 건설 거래가 들어 있어 시점만 맞아도 연결된다 (2026-11-17 확인: 대부분 우연)
J_HINT = "계열사 거래 — 우연 연결 가능, 원문 확인"

REVIEW_PATH = config.DATA_DIR / "labels" / "issue_evidence_review_v1.csv"
CANDIDATES_PATH = config.OUTPUTS_DIR / "reports" / "issue_evidence_candidates.csv"
KEY = ["issue_id", "rcept_no", "news_id", "match_type"]
REVIEW_COLUMNS = KEY + ["verified", "note", "reviewer"]
MATCH_ORDER = {"키워드": 0, "기간": 1, "수동": 2}


def keyword_candidates(issues: pd.DataFrame, links: pd.DataFrame, scope: str = DEFAULT_SCOPE) -> pd.DataFrame:
    """구간 안 기사의 기사↔공시 연결 → 공시당 1행 (대표 기사 포함).

    Args:
        links: news_link.link() 결과 + relevance(기사 HBM 관련도), category(공시 성격) 열
    """
    if scope not in SCOPES:
        raise ValueError(f"scope는 {SCOPES} 중 하나: {scope}")
    rows = []
    for issue in issues.itertuples(index=False):
        inside = links[(links["published_at"] >= issue.start_date) & (links["published_at"] <= issue.end_date)]
        for rcept_no, g in inside.groupby("rcept_no", sort=True):
            core = g[g["relevance"] == "핵심"]
            category = g["category"].iloc[0]
            if scope == "core" and core.empty:
                continue
            if scope == "broad" and core.empty and category not in BROAD_CATEGORIES:
                continue
            pool = core if not core.empty else g
            rep = pool.assign(gap=pool["days_from_article"].abs()).sort_values(["gap", "published_at", "news_id"]).iloc[0]
            articles = g.drop_duplicates("news_id")
            rows.append({
                "issue_id": issue.issue_id, "rcept_no": rcept_no, "news_id": rep["news_id"], "match_type": "키워드",
                "auto_note": (f"{EVIDENCE_VERSION} {scope} | 주제 {'·'.join(sorted(g['topic'].unique()))} | "
                              f"기사 {len(articles)}건(핵심 {core['news_id'].nunique()}) | "
                              f"대표 기사 대비 공시 {int(rep['days_from_article']):+d}일"
                              + (f" | {J_HINT}" if category == "공정위 거래" else "")),
                "n_articles": len(articles),
            })
    return pd.DataFrame(rows, columns=KEY + ["auto_note", "n_articles"])


def period_candidates(issues: pd.DataFrame, disclosures: pd.DataFrame, exclude: pd.DataFrame,
                      lead_days: int = PERIOD_LEAD_DAYS) -> pd.DataFrame:
    """구간(시작 lead_days일 전부터) 안의 사건성 공시 중 키워드 후보가 아닌 것.

    Args:
        disclosures: disclosure_trend.prepare()를 거친 표 (category, is_event 열)
        exclude: 이미 키워드 후보인 (issue_id, rcept_no)
    """
    taken = set(zip(exclude["issue_id"], exclude["rcept_no"]))
    events = disclosures[disclosures["is_event"]]
    rows = []
    for issue in issues.itertuples(index=False):
        start = (pd.Timestamp(issue.start_date) - timedelta(days=lead_days)).strftime(config.DATE_FORMAT)
        inside = events[(events["rcept_dt"] >= start) & (events["rcept_dt"] <= issue.end_date)]
        for d in inside.sort_values(["rcept_dt", "rcept_no"]).itertuples(index=False):
            if (issue.issue_id, d.rcept_no) in taken:
                continue
            before = d.rcept_dt < issue.start_date
            rows.append({
                "issue_id": issue.issue_id, "rcept_no": d.rcept_no, "news_id": None, "match_type": "기간",
                "auto_note": f"{EVIDENCE_VERSION} | {d.category} | 기사 연결 없음{' | 구간 시작 전' if before else ''}",
                "n_articles": 0,
            })
    return pd.DataFrame(rows, columns=KEY + ["auto_note", "n_articles"])


def _key_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["news_id"] = out["news_id"].where(out["news_id"].notna(), None)
    out["news_id"] = out["news_id"].map(lambda v: v if isinstance(v, str) and v else None)
    out["rcept_no"] = out["rcept_no"].map(lambda v: str(v) if pd.notna(v) and str(v) else None)
    return out


def row_key(issue_id, rcept_no, news_id, match_type) -> str:
    """라벨 파일의 key 열. 'HBM-2024-10|20241031800024|0339cd...|키워드' — 글자가 섞여 Excel이 숫자로 바꾸지 못한다."""
    return "|".join("" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
                    for v in (issue_id, rcept_no, news_id, match_type))


def _read_csv_any(path: Path) -> pd.DataFrame:
    """UTF-8로 읽고, 안 되면 cp949(Excel 한국어판 'CSV' 저장)로 읽는다."""
    try:
        return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="cp949")


def load_review(path: Path = REVIEW_PATH) -> pd.DataFrame:
    """라벨 파일을 읽는다. 없으면 빈 표.

    key 열이 있으면 키 4개(issue_id·rcept_no·news_id·match_type)를 key에서 다시 만든다. Excel로 저장하면
    rcept_no가 '2.0241E+13'처럼 지수 표기로 바뀌어 원래 값을 잃기 때문이다. key 없이 rcept_no가 깨져 있으면 멈춘다.
    key가 빈 행(사람이 새로 추가한 '수동' 행)은 키 열을 그대로 쓴다.
    """
    if not path.exists():
        return pd.DataFrame(columns=REVIEW_COLUMNS)
    df = _read_csv_any(path)
    for col in REVIEW_COLUMNS + ["key"]:
        if col not in df:
            df[col] = ""
    has_key = df["key"].str.count(r"\|") == 3
    parts = df.loc[has_key, "key"].str.split("|", expand=True)
    if has_key.any():
        df.loc[has_key, KEY] = parts.values
    broken = df["rcept_no"].str.contains(r"[Ee][+-]|\.", regex=True)
    if broken.any():
        raise ValueError(f"{path}: rcept_no가 숫자로 바뀐 행이 있습니다 (Excel 저장). git의 원본으로 되돌리거나 "
                         f"key 열을 지우지 말고 다시 저장하세요. 행: {df.index[broken].tolist()[:5]}")
    df = df[REVIEW_COLUMNS].replace({"": None})
    return _key_frame(df)


def merge_review(candidates: pd.DataFrame, review: pd.DataFrame) -> pd.DataFrame:
    """새 라벨 표: 기존의 채운 행(verified 또는 note)·수동 행 + 새 후보 빈 행. 후보가 아닌 빈 행은 버린다."""
    keep = review[review["verified"].notna() | review["note"].notna() | (review["match_type"] == "수동")]
    fresh = candidates[KEY].copy()
    for col in ("verified", "note", "reviewer"):
        fresh[col] = None
    merged = pd.concat([keep, fresh], ignore_index=True)
    merged = merged.drop_duplicates(subset=KEY, keep="first")  # 이미 있는 행(라벨 포함)을 우선
    return sort_rows(merged)[REVIEW_COLUMNS]


def sort_rows(df: pd.DataFrame) -> pd.DataFrame:
    order = df["match_type"].map(MATCH_ORDER)
    return (df.assign(_o=order, _n=df["news_id"].fillna(""), _r=df["rcept_no"].fillna(""))
              .sort_values(["issue_id", "_o", "_r", "_n"]).drop(columns=["_o", "_n", "_r"]).reset_index(drop=True))


def evidence_rows(candidates: pd.DataFrame, review: pd.DataFrame) -> pd.DataFrame:
    """issue_evidence에 넣을 행 (evidence_id 포함). 라벨의 verified·note를 반영한다."""
    manual = review[review["match_type"] == "수동"].assign(auto_note="수동 추가")
    rows = pd.concat([candidates[KEY + ["auto_note"]], manual[KEY + ["auto_note"]]], ignore_index=True)
    rows = rows.drop_duplicates(subset=KEY)
    labels = review.set_index(KEY)[["verified", "note"]]
    rows = rows.join(labels, on=KEY)
    rows["verified_int"] = (rows["verified"] == "1").astype(int)
    rejected = rows["verified"] == "0"

    def note(r) -> str:
        parts = [r.auto_note]
        if rejected[r.Index]:
            parts.append("기각")
        if isinstance(r.note, str) and r.note:
            parts.append(r.note)
        return " | ".join(parts)

    rows["note_out"] = [note(r) for r in rows.itertuples()]
    rows = sort_rows(rows)
    return pd.DataFrame({
        "evidence_id": range(1, len(rows) + 1),
        "issue_id": rows["issue_id"], "news_id": rows["news_id"], "rcept_no": rows["rcept_no"],
        "match_type": rows["match_type"], "verified": rows["verified_int"], "note": rows["note_out"],
    })


def build_candidates(conn, scope: str = DEFAULT_SCOPE) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """DB에서 후보를 만든다. Returns (issues, 후보, 검토용 공시 표)."""
    issues = db.read_table(conn, "issues", columns=["issue_id", "start_date", "end_date", "peak_date", "article_count"])
    articles, _ = news_link.hbm_articles(conn)
    disclosures = db.read_table(conn, "disclosure", columns=[
        "rcept_no", "corp_name", "report_nm", "rcept_dt", "pblntf_ty", "url", "text"])
    links = news_link.link(articles, disclosures)
    tags = db.read_table(conn, "news_tag", where="tag = 'HBM'", columns=["news_id", "relevance"])
    links["relevance"] = links["news_id"].map(tags.set_index("news_id")["relevance"])
    links["category"] = links["report_nm"].map(disclosure_trend.categorize)
    prepared = disclosure_trend.prepare(disclosures.drop(columns="text"))
    keyword = keyword_candidates(issues, links, scope)
    period = period_candidates(issues, prepared, keyword)
    candidates = pd.concat([keyword, period], ignore_index=True)
    return issues, _key_frame(candidates), prepared


def review_table(evidence: pd.DataFrame, disclosures: pd.DataFrame, news: pd.DataFrame,
                 issues: pd.DataFrame) -> pd.DataFrame:
    """사람이 볼 후보 표: 공시명·제출일·링크와 대표 기사 제목을 붙인다."""
    d = disclosures.set_index("rcept_no")
    n = news.set_index("news_id")
    out = evidence.merge(issues[["issue_id", "start_date", "end_date"]], on="issue_id", how="left")
    out["corp_name"] = out["rcept_no"].map(d["corp_name"])
    out["rcept_dt"] = out["rcept_no"].map(d["rcept_dt"])
    out["report_nm"] = out["rcept_no"].map(d["report_nm"])
    out["category"] = out["rcept_no"].map(d["category"])
    out["url"] = out["rcept_no"].map(d["url"])
    out["published_at"] = out["news_id"].map(n["published_at"])
    out["news_title"] = out["news_id"].map(n["title"])
    return out[["evidence_id", "issue_id", "start_date", "end_date", "match_type", "verified", "corp_name",
                "rcept_dt", "report_nm", "category", "rcept_no", "url", "published_at", "news_title", "news_id", "note"]]


CONTEXT_COLUMNS = ["corp_name", "rcept_dt", "report_nm", "news_title", "url"]


def with_context(review: pd.DataFrame, table: pd.DataFrame) -> pd.DataFrame:
    """라벨 파일에 판정용 참고 열(공시명·제출일·기사 제목·링크)을 붙인다. 읽을 때는 REVIEW_COLUMNS만 쓴다."""
    context = _key_frame(table)[KEY + CONTEXT_COLUMNS].drop_duplicates(subset=KEY)
    keyed = review.assign(_n=review["news_id"].fillna(""), _r=review["rcept_no"].fillna(""))
    context = context.assign(_n=context["news_id"].fillna(""), _r=context["rcept_no"].fillna(""))
    merged = keyed.merge(context.drop(columns=["news_id", "rcept_no"]),
                         on=["issue_id", "_r", "_n", "match_type"], how="left")
    merged["key"] = [row_key(*k) for k in merged[KEY].itertuples(index=False)]
    return merged[KEY + CONTEXT_COLUMNS + ["verified", "note", "reviewer", "key"]]


def clear(db_path: Path = config.DB_PATH) -> int:
    """issue_evidence를 비운다 (라벨 파일은 그대로). 지운 행 수를 돌려준다."""
    conn = db.connect(db_path)
    try:
        with conn:
            return conn.execute("DELETE FROM issue_evidence").rowcount
    finally:
        conn.close()


def main(scope: str = DEFAULT_SCOPE, dry_run: bool = False, db_path: Path = config.DB_PATH,
         review_path: Path = REVIEW_PATH, candidates_path: Path = CANDIDATES_PATH) -> pd.DataFrame:
    conn = db.connect(db_path)
    try:
        issues, candidates, disclosures = build_candidates(conn, scope)
        if issues.empty:
            print("issues가 비어 있습니다. 먼저 `python -m src.eda.spike_detection`을 실행하세요.")
            return pd.DataFrame()
        review = load_review(review_path)
        new_review = merge_review(candidates, review)
        evidence = evidence_rows(candidates, new_review)
        if not dry_run:
            db.write_table(conn, "issue_evidence", evidence, mode="replace")
        news = db.read_table(conn, "news", columns=["news_id", "published_at", "title"])
    finally:
        conn.close()

    table = review_table(evidence, disclosures, news, issues)
    if not dry_run:
        review_path.parent.mkdir(parents=True, exist_ok=True)
        with_context(new_review, table).to_csv(review_path, index=False, encoding="utf-8-sig")
    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(candidates_path, index=False, encoding="utf-8-sig")

    print(f"근거 후보 ({EVIDENCE_VERSION}, 범위 {scope}): {len(evidence)}행, 사람 확인 {int(evidence['verified'].sum())}행")
    summary = table.pivot_table(index="issue_id", columns="match_type", values="evidence_id",
                                aggfunc="count", fill_value=0)
    print(summary.to_string())
    print("DB·라벨 파일 그대로 (--dry-run)" if dry_run else f"DB issue_evidence 갱신, 라벨 파일: {review_path}")
    print(f"검토용: {candidates_path}")
    return table


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="급증 구간별 근거 공시 후보 → issue_evidence")
    parser.add_argument("--scope", choices=SCOPES, default=DEFAULT_SCOPE, help="키워드 후보 범위 (기본 broad)")
    parser.add_argument("--dry-run", action="store_true", help="DB·라벨 파일을 바꾸지 않고 후보 CSV만 저장")
    parser.add_argument("--clear", action="store_true", help="issue_evidence만 비운다 (급증 기준을 바꾸기 전)")
    args = parser.parse_args()
    if args.clear:
        print(f"issue_evidence {clear()}행 삭제 (라벨 파일은 그대로). 다음: spike_detection → issue_evidence")
    else:
        main(scope=args.scope, dry_run=args.dry_run)
