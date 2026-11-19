"""
대시보드 탭 1(이슈 분석)이 쓰는 저장된 분석 결과를 읽는다. 계산·LLM 호출은 하지 않는다 (초안 §6 구현 원칙).

읽는 것 (모두 앞 단계가 미리 만든 결과):
- DB: news·news_tag(태깅), issues(급증 구간), news_analysis(LLM 감성, 현재 프롬프트 버전), issue_evidence·disclosure(근거 공시)
- SQL: sql/02(월별 HBM 비중), 03(급증 구간별 기업 점유), 04(기업별 감성 월별) — 리포트·CSV와 같은 쿼리를 그대로 실행해 숫자를 맞춘다
- 파일: outputs/reports/hbm_spike_months.csv(급증 판정·문턱), data/labels/issue_summary_v1.csv(사건 요약·확정/제외),
        outputs/reports/sentiment_eval_<버전>.csv(감성 검수 정확도)

Streamlit을 import하지 않는 순수 함수로 두어 테스트할 수 있게 하고, 캐시(st.cache_data)는 화면(pages/1_이슈_분석.py)에서 감싼다.
파일이 없으면 빈 표·빈 dict를 돌려주고 화면이 안내한다.

담당: 김한승 (이슈 분석)
일정: Day 6
"""

from pathlib import Path

import pandas as pd

from src.common import config, db
from src.dart.sql_report import run_query
from src.llm import prompts

SQL_DIR = config.ROOT_DIR / "sql"
REPORTS_DIR = config.OUTPUTS_DIR / "reports"
SPIKE_PATH = REPORTS_DIR / "hbm_spike_months.csv"
SUMMARY_PATH = config.LABELS_DIR / "issue_summary_v1.csv"
EVAL_PATH = REPORTS_DIR / f"sentiment_eval_{prompts.PROMPT_VERSION}.csv"
EVIDENCE_REVIEW_PATH = config.LABELS_DIR / "issue_evidence_review_v1.csv"  # 사람이 쓴 확인 메모
COMPANIES = ("SK하이닉스", "삼성전자")
STATUS_ORDER = {"확정": 0, "검토 전": 1, "제외": 2}


def _query(db_path: Path, sql_file: str) -> pd.DataFrame:
    conn = db.connect(db_path)
    try:
        return run_query(conn, SQL_DIR / sql_file)
    finally:
        conn.close()


def _read(db_path: Path, sql: str, params: tuple = ()) -> pd.DataFrame:
    conn = db.connect(db_path)
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


def monthly_share(db_path: Path = config.DB_PATH, spike_path: Path = SPIKE_PATH) -> pd.DataFrame:
    """월별 전체·HBM 기사 수와 비중(SQL 02) + 급증 판정(threshold, status, is_spike)."""
    m = _query(db_path, "02_hbm_monthly_share.sql")
    if spike_path.exists():
        s = pd.read_csv(spike_path, encoding="utf-8-sig", usecols=["month", "threshold", "status", "is_spike"])
        m = m.merge(s, on="month", how="left")
    else:
        m["threshold"], m["status"], m["is_spike"] = float("nan"), None, False
    m["is_spike"] = m["is_spike"].fillna(False).astype(bool)
    return m


def issue_table(db_path: Path = config.DB_PATH, summary_path: Path = SUMMARY_PATH) -> pd.DataFrame:
    """급증 구간 + 사건 요약 라벨(확정/제외/검토 전). 확정 → 검토 전 → 제외, 같은 상태는 시작일 순."""
    t = _read(db_path, "SELECT issue_id, start_date, end_date, peak_date, peak_share, baseline_share, "
                       "article_count, method FROM issues WHERE tech_tag = 'HBM'")
    if summary_path.exists():
        s = pd.read_csv(summary_path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
        t = t.merge(s[["issue_id", "summary", "status", "note", "evidence_rcept_no"]], on="issue_id", how="left")
    for col in ("summary", "note", "evidence_rcept_no"):
        if col not in t:
            t[col] = ""
        t[col] = t[col].fillna("")
    if "status" not in t:
        t["status"] = None
    t["status"] = t["status"].replace("", None).fillna("검토 전")
    start, end = t["start_date"].str[:7], t["end_date"].str[:7]
    t["label"] = [a if a == b else f"{a} ~ {b}" for a, b in zip(start, end)]
    t["_o"] = t["status"].map(STATUS_ORDER).fillna(1)
    return t.sort_values(["_o", "start_date"]).drop(columns="_o").reset_index(drop=True)


def company_coverage(db_path: Path = config.DB_PATH) -> pd.DataFrame:
    """급증 구간별 HBM 기사의 기업 점유 vs 구간 밖 (SQL 03)."""
    return _query(db_path, "03_issue_company_coverage.sql")


def sentiment_monthly(db_path: Path = config.DB_PATH) -> pd.DataFrame:
    """월 × 기업 LLM 감성·순감성·3개월 순감성 (SQL 04, 현재 프롬프트 버전)."""
    return _query(db_path, "04_company_sentiment_monthly.sql")


_HBM_ARTICLES = """
    SELECT n.news_id, n.published_at, n.title, n.media, n.url, t.relevance,
           a.sentiment_skh, a.sentiment_sec, a.issue_keywords
    FROM news AS n
    JOIN news_tag AS t ON t.news_id = n.news_id AND t.tag_type = 'tech' AND t.tag = 'HBM'
                      AND t.relevance IN ('핵심', '관련')
    LEFT JOIN news_analysis AS a ON a.news_id = n.news_id AND a.prompt_version = ?
    WHERE n.is_duplicate = 0 AND n.published_at BETWEEN ? AND ?
"""


def issue_articles(db_path: Path, start: str, end: str, limit: int = 8) -> pd.DataFrame:
    """구간 안 HBM 기사 (제목에 HBM이 있는 '핵심' 먼저, 같은 등급은 발행일 순) + 기업별 감성."""
    sql = _HBM_ARTICLES + " ORDER BY CASE t.relevance WHEN '핵심' THEN 0 ELSE 1 END, n.published_at, n.news_id LIMIT ?"
    return _read(db_path, sql, (prompts.PROMPT_VERSION, start, end, limit))


def period_sentiment(db_path: Path, start: str, end: str) -> pd.DataFrame:
    """구간 안 기업별 감성 건수와 순감성 ('해당없음'은 그 기업의 분모에서 뺀다)."""
    a = _read(db_path, _HBM_ARTICLES, (prompts.PROMPT_VERSION, start, end))
    rows = []
    for name, col in zip(COMPANIES, ("sentiment_skh", "sentiment_sec")):
        v = a[col].dropna()
        v = v[v != "해당없음"]
        pos, neg = int((v == "긍정").sum()), int((v == "부정").sum())
        rows.append({"company": name, "articles": len(v), "positive": pos, "neutral": int((v == "중립").sum()),
                     "negative": neg, "net": (pos - neg) / len(v) if len(v) else float("nan")})
    return pd.DataFrame(rows)


def issue_evidence(db_path: Path, issue_id: str, review_path: Path = EVIDENCE_REVIEW_PATH) -> pd.DataFrame:
    """사람이 확인한(verified = 1) 근거 공시와 연결 기사 제목.

    DB의 note는 자동 생성 메모(연결 규칙·주제 등)와 사람 메모가 이어 붙어 있어 화면에 길다.
    사람이 쓴 메모만 보이도록 라벨 파일(issue_evidence_review_v1.csv)의 note로 바꾼다. 라벨 파일이 없으면 빈 칸.
    """
    e = _read(db_path, """
        SELECT e.issue_id, e.match_type, e.note, e.rcept_no, d.corp_name, d.report_nm, d.rcept_dt, d.url,
               n.title AS news_title, n.url AS news_url
        FROM issue_evidence AS e
        JOIN disclosure AS d ON d.rcept_no = e.rcept_no
        LEFT JOIN news AS n ON n.news_id = e.news_id
        WHERE e.issue_id = ? AND e.verified = 1
        ORDER BY d.rcept_dt, e.rcept_no
    """, (issue_id,))
    human = {}
    if review_path.exists():
        r = pd.read_csv(review_path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
        human = {(a, b, c): n for a, b, c, n in zip(r["issue_id"], r["rcept_no"], r["match_type"], r["note"])}
    e["note"] = [human.get((a, b, c), "") for a, b, c in zip(e["issue_id"], e["rcept_no"], e["match_type"])]
    return e


def eval_summary(path: Path = EVAL_PATH) -> dict:
    """감성 검수 결과 {기업: {n, accuracy, ci_low, ci_high, macro_f1}}. 파일이 없으면 빈 dict."""
    if not path.exists():
        return {}
    df = pd.read_csv(path, encoding="utf-8-sig")
    cols = [c for c in ("n", "accuracy", "ci_low", "ci_high", "macro_f1") if c in df]
    return {r["company"]: {c: r[c] for c in cols} for _, r in df.iterrows()}


def overview(db_path: Path = config.DB_PATH, summary_path: Path = SUMMARY_PATH) -> dict:
    """상단 요약 숫자: 분석 기사(중복 제외)·HBM 기사·급증 구간(확정/제외)·사람이 확인한 근거 공시."""
    counts = _read(db_path, """
        SELECT (SELECT COUNT(*) FROM news WHERE is_duplicate = 0) AS articles,
               (SELECT COUNT(*) FROM news AS n JOIN news_tag AS t ON t.news_id = n.news_id
                 AND t.tag_type = 'tech' AND t.tag = 'HBM' AND t.relevance IN ('핵심', '관련')
                WHERE n.is_duplicate = 0) AS hbm_articles,
               (SELECT COUNT(*) FROM issue_evidence WHERE verified = 1) AS verified_evidence
    """).iloc[0]
    issues = issue_table(db_path, summary_path)
    return {"articles": int(counts["articles"]), "hbm_articles": int(counts["hbm_articles"]),
            "issues": len(issues), "confirmed": int((issues["status"] == "확정").sum()),
            "excluded": int((issues["status"] == "제외").sum()),
            "verified_evidence": int(counts["verified_evidence"])}
