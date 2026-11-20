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
from src.eda import news_trend
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


# ── 기간·기업 필터 (화면의 필터가 모든 차트에 같은 기준으로 걸리도록 한곳에 둔다) ──
COMPANY_COL = {"SK하이닉스": "sentiment_skh", "삼성전자": "sentiment_sec"}


def month_options(monthly: pd.DataFrame) -> list[str]:
    """기간 선택지: 분석 기간 전체 월 (YYYY-MM)."""
    return monthly["month"].tolist()


def in_months(df: pd.DataFrame, start: str, end: str, col: str = "month") -> pd.DataFrame:
    """월 열이 start~end(YYYY-MM, 양 끝 포함)인 행."""
    return df[(df[col] >= start) & (df[col] <= end)].reset_index(drop=True)


def issues_in_range(issues: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """선택 기간과 한 달이라도 겹치는 급증 구간 (원래 순서 유지)."""
    s, e = issues["start_date"].str[:7], issues["end_date"].str[:7]
    return issues[(s <= end) & (e >= start)].reset_index(drop=True)


def coverage_in_range(db_path: Path, start: str, end: str) -> pd.DataFrame:
    """SQL 03(급증 구간별 기업 점유)을 선택 기간(YYYY-MM) 안의 기사로만 계산한다. 전체 기간이면 SQL 03과 같다 (테스트로 대조)."""
    sql = (SQL_DIR / "03_issue_company_coverage.sql").read_text(encoding="utf-8")
    sql = sql.replace("    WHERE n.is_duplicate = 0\n),\ncompany AS",
                      "    WHERE n.is_duplicate = 0 AND substr(n.published_at, 1, 7) BETWEEN :start AND :end\n),\ncompany AS")
    assert ":start" in sql, "SQL 03 구조가 바뀌었다 — coverage_in_range의 기간 조건 위치를 확인할 것"
    conn = db.connect(db_path)
    try:
        return pd.read_sql_query(sql, conn, params={"start": start, "end": end})
    finally:
        conn.close()


def company_monthly(db_path: Path = config.DB_PATH) -> pd.DataFrame:
    """월별 HBM 기사 중 기업 태그(핵심·관련) 기사 수 — news_trend.company_monthly를 그대로 쓴다 (리포트 3.1과 같은 정의)."""
    return news_trend.company_monthly(news_trend.load_articles(db_path))


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


def issue_articles(db_path: Path, start: str, end: str, limit: int = 8, company: str | None = None) -> pd.DataFrame:
    """구간 안 HBM 기사 (제목에 HBM이 있는 '핵심' 먼저, 같은 등급은 발행일 순) + 기업별 감성.

    company를 주면 그 기업이 등장한(LLM 판정이 '해당없음'이 아닌) 기사만.
    """
    where = f" AND a.{COMPANY_COL[company]} IS NOT NULL AND a.{COMPANY_COL[company]} <> '해당없음'" if company else ""
    sql = (_HBM_ARTICLES + where +
           " ORDER BY CASE t.relevance WHEN '핵심' THEN 0 ELSE 1 END, n.published_at, n.news_id LIMIT ?")
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


def issue_evidence(db_path: Path, issue_id: str, review_path: Path = EVIDENCE_REVIEW_PATH,
                   company: str | None = None) -> pd.DataFrame:
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
    if company:  # 기업 필터: 그 기업이 낸 공시만
        e = e[e["corp_name"] == company].reset_index(drop=True)
    return e


def evidence_counts(db_path: Path = config.DB_PATH) -> dict:
    """급증 구간별 사람이 확인한(verified = 1) 근거 공시 수 {issue_id: n} — 기간 필터에 맞춰 요약 지표를 다시 셀 때 쓴다."""
    df = _read(db_path, "SELECT issue_id, COUNT(*) AS n FROM issue_evidence WHERE verified = 1 GROUP BY issue_id")
    return dict(zip(df["issue_id"], df["n"].astype(int)))


def range_overview(monthly: pd.DataFrame, issues: pd.DataFrame, evidence: dict) -> dict:
    """기간 필터를 적용한 요약 숫자 (overview와 같은 키). monthly·issues는 이미 기간으로 거른 표."""
    return {"articles": int(monthly["total"].sum()), "hbm_articles": int(monthly["hbm"].sum()),
            "issues": len(issues), "confirmed": int((issues["status"] == "확정").sum()),
            "excluded": int((issues["status"] == "제외").sum()),
            "verified_evidence": int(sum(evidence.get(i, 0) for i in issues["issue_id"]))}


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
