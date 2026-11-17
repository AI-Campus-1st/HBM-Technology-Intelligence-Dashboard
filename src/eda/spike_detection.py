"""
월별 HBM 기사 비중에서 이슈 급증 구간을 찾아 issues 테이블에 저장한다 (Day 3, 리포트 3.1).

확정 기준 — 방식 B (2026-11-17 팀 결정, 초안 v1.2 결정 로그 '급증 기준 확정'):
    METHOD = "rolling6m_2sigma_exclude_spikes_min10_v1"
    1) 비중 = 그 달 HBM 핵심+관련 기사 수 / 그 달 전체 기사 수 (둘 다 중복 제외, news_trend.monthly_hbm)
    2) 기준선 창 = 판정할 달 바로 앞의 6개 '달력상' 달 (고정 창)
       - 기록 요건: 6개 달이 모두 데이터 안에 있고 일부 기간 달이 아니어야 판정한다 (없으면 insufficient_history)
       - 그 6개 달 중 '이미 급증으로 판정된 달'은 기준선에서 뺀다 (방식 B). 뺀 자리를 더 오래된 달로 채우지 않는다
       - 남은 달이 MIN_BASELINE_MONTHS(3)개 미만이면 판정하지 않는다 (insufficient_baseline)
    3) 임계값 = 기준선 평균 + K(2) × 기준선 표본표준편차 (ddof=1)
    4) 급증 = 비중 > 임계값 그리고 HBM 기사 수 ≥ MIN_COUNT(10)  (10건은 통과, 9건은 탈락)
    5) 일부 기간 달(2023-10, 2026-10)은 판정하지 않는다 (partial). 데이터·그림에는 남는다
    6) 달 순서대로 처리하므로, 어떤 달의 판정은 그보다 앞 달의 판정에만 영향을 받는다
    7) 연속된 급증 달은 하나의 구간(issues 1행)으로 묶는다
- 기준선에서 빼는 것은 '평상시 수준' 계산뿐이다. 급증 달의 기사는 데이터·차트·기업 비교·리포트에 그대로 남는다.
- MIN_BASELINE_MONTHS = 3: 6개월 창의 절반이자 표본표준편차(자유도 2)를 낼 수 있는 최소 개수.
  기존 구현(이전 달로 채우는 방식)에는 이 값이 없어서 새로 정했다. 2·3·4 비교는 hbm_spike_options.csv에 남긴다.
- 방식 A(급증 달도 기준선에 포함, exclude_spikes=False)는 비교용으로 남긴다.

실행: python -m src.eda.spike_detection            (issues 테이블의 HBM 행을 이번 결과로 맞춘다)
      python -m src.eda.spike_detection --dry-run  (CSV만 저장)

저장:
- DB issues (tech_tag='HBM' 행만): 이번 결과를 upsert하고, 결과에 없는 예전 HBM 행은 지운다.
  다른 tech_tag 행은 건드리지 않는다. 지울 행을 issue_evidence가 참조 중이면 멈춘다 (근거 연결 보호).
- outputs/reports/hbm_spike_months.csv  : 월별 기준선 창·표본 수·임계값·상태 (방식 B, 핵심+관련 / 핵심만)
- outputs/reports/hbm_spike_options.csv : 방식 A·B × 최소 기사 수 × 최소 기준선 개수 비교

담당: 공동 (뉴스 부분 김한승)
일정: Day 3
"""

import argparse
import sqlite3
from pathlib import Path

import pandas as pd

from src.common import config, db, schema

WINDOW = 6                # 기준선 창: 판정 달 바로 앞 6개 달력상 달
K = 2.0                   # 표준편차 배수 (표본표준편차, ddof=1)
MIN_COUNT = 10            # 급증 달의 최소 HBM 핵심+관련 기사 수 (이상, 포함)
MIN_BASELINE_MONTHS = 3   # 급증 달을 뺀 뒤 기준선에 남아야 하는 최소 달 수
EXCLUDE_SPIKES = True     # 방식 B: 이미 급증으로 판정된 달을 기준선에서 뺀다
TECH_TAG = "HBM"

STATUS_PARTIAL = "partial"
STATUS_NO_HISTORY = "insufficient_history"
STATUS_NO_BASELINE = "insufficient_baseline"
STATUS_LOW_COUNT = "below_min_count"
STATUS_SPIKE = "spike"
STATUS_NORMAL = "normal"

MONTHS_PATH = config.OUTPUTS_DIR / "reports" / "hbm_spike_months.csv"
OPTIONS_PATH = config.OUTPUTS_DIR / "reports" / "hbm_spike_options.csv"
ISSUE_COLUMNS = [c.name for c in schema.TABLES["issues"].columns]


def method_id(window: int = WINDOW, k: float = K, min_count: int = MIN_COUNT,
              exclude_spikes: bool = EXCLUDE_SPIKES) -> str:
    """탐지 기준 식별자. 코드·CSV·DB·문서가 같은 문자열을 쓴다."""
    middle = "_exclude_spikes" if exclude_spikes else ""
    return f"rolling{window}m_{k:g}sigma{middle}_min{min_count}_v1"


METHOD = method_id()  # rolling6m_2sigma_exclude_spikes_min10_v1


def flag_months(monthly: pd.DataFrame, window: int = WINDOW, k: float = K, min_count: int = MIN_COUNT,
                share_col: str = "share", count_col: str = "hbm", exclude_spikes: bool = EXCLUDE_SPIKES,
                min_baseline: int = MIN_BASELINE_MONTHS) -> pd.DataFrame:
    """달마다 기준선(고정 6개월 창)과 판정 상태를 붙인다. 입력은 바꾸지 않고 행도 빼지 않는다.

    Args:
        monthly: month('YYYY-MM'), partial, share_col, count_col 열을 가진 월별 표
        exclude_spikes: True(방식 B)면 창 안의 이미 급증으로 판정된 달을 기준선에서 뺀다
        min_baseline: 급증 달을 뺀 뒤 기준선에 남아야 하는 최소 달 수
    Returns:
        입력 열 + baseline_months('YYYY-MM;...'), baseline_n, baseline_mean, baseline_std, threshold, status, is_spike
    """
    df = monthly.sort_values("month").reset_index(drop=True).copy()
    by_month = {m: i for i, m in enumerate(df["month"])}
    spike_months: set = set()
    cols: dict[str, list] = {c: [] for c in
                             ("baseline_months", "baseline_n", "baseline_mean", "baseline_std", "threshold", "status")}

    for row in df.itertuples(index=False):
        target = pd.Period(row.month, "M")
        window_months = [str(target - lag) for lag in range(window, 0, -1)]
        has_history = all(m in by_month and not df.at[by_month[m], "partial"] for m in window_months)
        eligible = [m for m in window_months if m in by_month
                    and not df.at[by_month[m], "partial"]
                    and not (exclude_spikes and m in spike_months)]
        mean = std = threshold = float("nan")
        if len(eligible) >= 2:
            base = df.loc[[by_month[m] for m in eligible], share_col]
            mean, std = float(base.mean()), float(base.std(ddof=1))

        share, count = getattr(row, share_col), getattr(row, count_col)
        if row.partial:
            status = STATUS_PARTIAL
        elif not has_history:
            status = STATUS_NO_HISTORY
        elif len(eligible) < min_baseline:
            status = STATUS_NO_BASELINE
        else:
            threshold = mean + k * std
            if share <= threshold:
                status = STATUS_NORMAL
            elif count < min_count:
                status = STATUS_LOW_COUNT
            else:
                status = STATUS_SPIKE
                spike_months.add(row.month)  # 이후 달의 기준선에서만 빠진다

        cols["baseline_months"].append(";".join(eligible))
        cols["baseline_n"].append(len(eligible))
        cols["baseline_mean"].append(mean)
        cols["baseline_std"].append(std)
        cols["threshold"].append(threshold)
        cols["status"].append(status)

    for name, values in cols.items():
        df[name] = values
    df["is_spike"] = df["status"] == STATUS_SPIKE
    return df


def group_issues(flags: pd.DataFrame, tech_tag: str = TECH_TAG, method: str = METHOD,
                 share_col: str = "share", count_col: str = "hbm") -> pd.DataFrame:
    """연속된 급증 달을 구간으로 묶어 issues 테이블 형식으로 만든다 (summary는 비워 둔다)."""
    rows = []
    run: list = []
    spikes = flags.reset_index(drop=True)
    for i, row in spikes.iterrows():
        if row["is_spike"]:
            run.append(i)
        if run and (not row["is_spike"] or i == len(spikes) - 1):
            part = spikes.loc[run]
            peak = part.loc[part[share_col].idxmax()]
            start, end = pd.Period(part["month"].iloc[0], "M"), pd.Period(part["month"].iloc[-1], "M")
            rows.append({
                "issue_id": f"{tech_tag}-{start}",
                "tech_tag": tech_tag,
                "start_date": start.start_time.strftime("%Y-%m-%d"),
                "end_date": end.end_time.strftime("%Y-%m-%d"),
                "peak_date": pd.Period(peak["month"], "M").start_time.strftime("%Y-%m-%d"),
                "peak_share": float(peak[share_col]),
                "baseline_share": float(peak["baseline_mean"]),
                "article_count": int(part[count_col].sum()),
                "method": method,
                "summary": None,
            })
            run = []
    return pd.DataFrame(rows, columns=ISSUE_COLUMNS)


def compare_options(monthly: pd.DataFrame, share_col: str = "share", count_col: str = "hbm",
                    min_counts=(0, 5, 10, 15), min_baselines=(2, 3, 4)) -> pd.DataFrame:
    """방식 A·B × 최소 기사 수 × 최소 기준선 개수별 급증 달 비교 (결정 근거·재현용)."""
    rows = []
    for excl in (False, True):
        for mb in min_baselines:
            for mc in min_counts:
                f = flag_months(monthly, min_count=mc, share_col=share_col, count_col=count_col,
                                exclude_spikes=excl, min_baseline=mb)
                months = f.loc[f["is_spike"], "month"].tolist()
                rows.append({
                    "series": share_col, "method": method_id(min_count=mc, exclude_spikes=excl),
                    "exclude_spikes": excl, "min_count": mc, "min_baseline": mb,
                    "spike_months": ", ".join(months), "n_months": len(months),
                    "n_issues": len(group_issues(f, share_col=share_col, count_col=count_col)),
                })
    return pd.DataFrame(rows)


def persist_issues(conn: sqlite3.Connection, issues: pd.DataFrame, tech_tag: str = TECH_TAG) -> dict:
    """issues 테이블의 tech_tag 행을 이번 결과와 같게 만든다 (다시 실행해도 같은 결과, 다른 tech_tag는 그대로).

    Returns:
        {"upserted": n, "deleted": [issue_id...]}
    Raises:
        RuntimeError: 지울 예전 구간을 issue_evidence가 참조하고 있을 때 (아무것도 바꾸지 않는다)
    """
    new_ids = set(issues["issue_id"])
    old_ids = {r[0] for r in conn.execute("SELECT issue_id FROM issues WHERE tech_tag = ?", (tech_tag,))}
    stale = sorted(old_ids - new_ids)
    if stale:
        placeholders = ",".join("?" for _ in stale)
        referenced = conn.execute(
            f"SELECT DISTINCT issue_id FROM issue_evidence WHERE issue_id IN ({placeholders})", stale).fetchall()
        if referenced:
            raise RuntimeError(f"issue_evidence가 참조 중인 예전 구간이 있어 멈춥니다: {[r[0] for r in referenced]}")
    with conn:
        if stale:
            conn.execute(f"DELETE FROM issues WHERE issue_id IN ({','.join('?' for _ in stale)})", stale)
    db.write_table(conn, "issues", issues, mode="upsert")
    return {"upserted": len(issues), "deleted": stale}


def run(monthly: pd.DataFrame, min_count: int = MIN_COUNT, exclude_spikes: bool = EXCLUDE_SPIKES):
    """월별 표로 판정·구간·비교표를 만든다. Returns (flags, core_flags, issues, options)."""
    method = method_id(min_count=min_count, exclude_spikes=exclude_spikes)
    flags = flag_months(monthly, min_count=min_count, exclude_spikes=exclude_spikes)
    # '핵심'만 센 보수적 시계열로 같은 판정을 돌려 결과가 겹치는지 본다 (기사 수가 적어 최소 수는 절반)
    core = flag_months(monthly, min_count=max(1, min_count // 2), share_col="share_core", count_col="hbm_core",
                       exclude_spikes=exclude_spikes)
    issues = group_issues(flags, method=method)
    options = pd.concat([
        compare_options(monthly),
        compare_options(monthly, share_col="share_core", count_col="hbm_core", min_counts=(0, 3, 5, 8)),
    ], ignore_index=True)
    return flags, core, issues, options


def main(db_path: Path = config.DB_PATH, min_count: int = MIN_COUNT, write_db: bool = True,
         exclude_spikes: bool = EXCLUDE_SPIKES) -> pd.DataFrame:
    from src.eda import news_trend

    monthly = news_trend.monthly_hbm(news_trend.load_articles(db_path))
    flags, core, issues, options = run(monthly, min_count, exclude_spikes)

    MONTHS_PATH.parent.mkdir(parents=True, exist_ok=True)
    flags.assign(status_core=core["status"], threshold_core=core["threshold"], is_spike_core=core["is_spike"]).to_csv(
        MONTHS_PATH, index=False, encoding="utf-8-sig")
    options.to_csv(OPTIONS_PATH, index=False, encoding="utf-8-sig")

    result = None
    if write_db:
        conn = db.connect(db_path)
        try:
            result = persist_issues(conn, issues)
        finally:
            conn.close()
    print(f"기준: {issues['method'].iloc[0] if len(issues) else method_id(min_count=min_count, exclude_spikes=exclude_spikes)}")
    print(issues[["issue_id", "start_date", "end_date", "peak_date", "peak_share", "baseline_share", "article_count"]]
          .to_string(index=False))
    print("월별 상태: " + ", ".join(f"{s} {n}" for s, n in flags["status"].value_counts().items()))
    print("핵심만 기준 급증 달: " + ", ".join(core.loc[core["is_spike"], "month"]))
    if result is not None:
        print(f"issues 반영: upsert {result['upserted']}건, 삭제 {len(result['deleted'])}건 {result['deleted']}")
    print(f"저장: {MONTHS_PATH}, {OPTIONS_PATH}")
    return issues


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="월별 HBM 비중 급증 구간 탐지 (방식 B)")
    parser.add_argument("--min-count", type=int, default=MIN_COUNT)
    parser.add_argument("--dry-run", action="store_true", help="DB issues 테이블에 쓰지 않는다")
    parser.add_argument("--method-a", action="store_true", help="비교용: 급증 달을 기준선에 포함 (방식 A)")
    args = parser.parse_args()
    main(min_count=args.min_count, write_db=not args.dry_run, exclude_spikes=not args.method_a)
