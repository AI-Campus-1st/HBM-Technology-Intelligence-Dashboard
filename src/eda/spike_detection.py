"""
월별 HBM 기사 비중에서 이슈 급증 구간을 찾아 issues 테이블에 저장한다 (Day 3, 리포트 3장).

기준 (초안 v1.2 §4.3, 결정 로그 2026-11-13 '급증 기준'):
    어떤 달의 HBM 비중이 직전 WINDOW개월(일부 기간 달 제외) 평균 + K × 표준편차를 넘고,
    그 달 HBM 기사 수가 MIN_COUNT건 이상이면 급증 달. 연속된 급증 달은 하나의 구간으로 묶는다.
- 일부 기간 달(첫 달 2023-10, 마지막 달 2026-10)은 기준선에도 넣지 않고 판정도 하지 않는다.
- 직전 WINDOW개월이 모자란 초기 달은 판정하지 않는다 (데이터 시작 직후는 기준선이 없다).
- 최소 기사 수 조건: 월 기사 수가 적은 달(예: 2024-08, 전체 68건)은 몇 건만으로 비중이 튄다.
  후보별 결과를 compare_min_counts()로 비교해 근거를 남긴다 (outputs/reports/hbm_spike_options.csv).
- 입력 비중은 news_trend.monthly_hbm()의 share(핵심+관련)를 쓰고, share_core(핵심만)로 같은 판정을 돌려
  두 결과가 겹치는지 확인한다.

실행: python -m src.eda.spike_detection   (preprocess 다음. issues 테이블을 다시 채운다)

저장:
- DB issues 테이블 (replace) — issue_evidence가 참조하므로, 근거 연결 후 다시 돌리면 FK 오류가 날 수 있다
- outputs/reports/hbm_spike_months.csv  : 월별 기준선·임계값·판정 (핵심+관련, 핵심만)
- outputs/reports/hbm_spike_options.csv : 최소 기사 수 후보별 급증 달

담당: 공동 (뉴스 부분 김한승)
일정: Day 3
"""

import argparse
from pathlib import Path

import pandas as pd

from src.common import config, db, schema

WINDOW = 6       # 기준선 개월 수
K = 2.0          # 표준편차 배수
MIN_COUNT = 10   # 급증 달의 최소 HBM 기사 수 (2026-11-17 후보 비교 후 결정, 리포트 3장)
# 급증으로 판정한 달을 이후 기준선에서 뺄지. 빼지 않으면 큰 급증(예: 2024-12) 뒤 6개월 동안 임계값이 높아져
# 그 사이 사건(2025-04 삼성 실적 등)을 놓친다. 팀 결정 전이라 기본은 기존 합의(빼지 않음)로 둔다.
EXCLUDE_SPIKES = False
METHOD_FMT = "rolling{window}m_{k:g}sigma_min{min_count}{excl}_v1"

MONTHS_PATH = config.OUTPUTS_DIR / "reports" / "hbm_spike_months.csv"
OPTIONS_PATH = config.OUTPUTS_DIR / "reports" / "hbm_spike_options.csv"
ISSUE_COLUMNS = [c.name for c in schema.TABLES["issues"].columns]


def flag_months(monthly: pd.DataFrame, window: int = WINDOW, k: float = K, min_count: int = MIN_COUNT,
                share_col: str = "share", count_col: str = "hbm", exclude_spikes: bool = EXCLUDE_SPIKES) -> pd.DataFrame:
    """월별 기준선(직전 window개월 평균·표준편차)과 급증 여부를 붙인다.

    Args:
        monthly: month, partial, share_col, count_col 열을 가진 월별 표 (월 순서대로)
        exclude_spikes: True면 급증으로 판정한 달은 이후 기준선 계산에서 뺀다
    Returns:
        입력 + baseline_mean, baseline_std, threshold, is_spike
    """
    df = monthly.reset_index(drop=True).copy()
    means, stds, thresholds, spikes = [], [], [], []
    base_months: list = []  # 기준선 후보: 일부 기간이 아닌 달의 비중 (exclude_spikes면 급증 달 제외)
    for row in df.itertuples(index=False):
        share, count = getattr(row, share_col), getattr(row, count_col)
        if len(base_months) >= window:
            base = pd.Series(base_months[-window:])
            mean, std = base.mean(), base.std(ddof=1)
            threshold = mean + k * std
        else:
            mean = std = threshold = float("nan")
        is_spike = bool(not row.partial and pd.notna(threshold) and share > threshold and count >= min_count)
        means.append(mean)
        stds.append(std)
        thresholds.append(threshold)
        spikes.append(is_spike)
        if not row.partial and not (exclude_spikes and is_spike):
            base_months.append(share)
    df["baseline_mean"] = means
    df["baseline_std"] = stds
    df["threshold"] = thresholds
    df["is_spike"] = spikes
    return df


def group_issues(flags: pd.DataFrame, tech_tag: str = "HBM", method: str = "",
                 share_col: str = "share", count_col: str = "hbm") -> pd.DataFrame:
    """연속된 급증 달을 구간으로 묶어 issues 테이블 형식으로 만든다."""
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


def compare_min_counts(monthly: pd.DataFrame, candidates=(0, 5, 10, 15), window: int = WINDOW, k: float = K,
                       share_col: str = "share", count_col: str = "hbm") -> pd.DataFrame:
    """최소 기사 수 후보별로 급증 달 목록을 비교한다 (결정 근거용)."""
    rows = []
    for excl in (False, True):
        for c in candidates:
            f = flag_months(monthly, window, k, c, share_col, count_col, exclude_spikes=excl)
            months = f.loc[f["is_spike"], "month"].tolist()
            rows.append({"series": share_col, "exclude_spikes": excl, "min_count": c,
                         "spike_months": ", ".join(months), "n_months": len(months),
                         "n_issues": len(group_issues(f, share_col=share_col, count_col=count_col))})
    return pd.DataFrame(rows)


def main(db_path: Path = config.DB_PATH, min_count: int = MIN_COUNT, write_db: bool = True,
         exclude_spikes: bool = EXCLUDE_SPIKES) -> pd.DataFrame:
    from src.eda import news_trend

    monthly = news_trend.monthly_hbm(news_trend.load_articles(db_path))
    method = METHOD_FMT.format(window=WINDOW, k=K, min_count=min_count, excl="_exclspike" if exclude_spikes else "")
    flags = flag_months(monthly, min_count=min_count, exclude_spikes=exclude_spikes)
    core = flag_months(monthly, min_count=max(1, min_count // 2), share_col="share_core", count_col="hbm_core",
                       exclude_spikes=exclude_spikes)
    issues = group_issues(flags, method=method)

    MONTHS_PATH.parent.mkdir(parents=True, exist_ok=True)
    flags.assign(is_spike_core=core["is_spike"], threshold_core=core["threshold"]).to_csv(
        MONTHS_PATH, index=False, encoding="utf-8-sig")
    pd.concat([compare_min_counts(monthly),
               compare_min_counts(monthly, candidates=(0, 3, 5, 8), share_col="share_core", count_col="hbm_core")]
              ).to_csv(OPTIONS_PATH, index=False, encoding="utf-8-sig")

    if write_db:
        conn = db.connect(db_path)
        try:
            db.write_table(conn, "issues", issues, mode="replace")
        finally:
            conn.close()
    print(f"기준: {method} (일부 기간 달 제외)")
    print(issues[["issue_id", "start_date", "end_date", "peak_date", "peak_share", "baseline_share", "article_count"]]
          .to_string(index=False))
    print("핵심만 기준 급증 달: " + ", ".join(core.loc[core["is_spike"], "month"]))
    print(f"저장: issues {len(issues)}건{' (DB)' if write_db else ''}, {MONTHS_PATH}, {OPTIONS_PATH}")
    return issues


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="월별 HBM 비중 급증 구간 탐지")
    parser.add_argument("--min-count", type=int, default=MIN_COUNT)
    parser.add_argument("--dry-run", action="store_true", help="DB issues 테이블에 쓰지 않는다")
    parser.add_argument("--exclude-spikes", action="store_true", help="급증 달을 이후 기준선에서 뺀다")
    args = parser.parse_args()
    main(min_count=args.min_count, write_db=not args.dry_run, exclude_spikes=args.exclude_spikes or EXCLUDE_SPIKES)
