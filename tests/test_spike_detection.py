"""
급증 구간 탐지(src/eda/spike_detection.py) 테스트. 인공 시계열로 확인한다.

담당: 공동
일정: Day 3
"""

import pandas as pd
import pytest

from src.common import schema
from src.eda import spike_detection as sd


def series(shares, counts=None, partial=None):
    months = pd.period_range("2024-01", periods=len(shares), freq="M").astype(str)
    counts = counts or [20] * len(shares)
    return pd.DataFrame({
        "month": months, "share": shares, "hbm": counts,
        "total": [200] * len(shares), "partial": partial or [False] * len(shares),
    })


BASE = [0.02, 0.03, 0.025, 0.02, 0.03, 0.025]  # 6개월 기준선


def test_detects_month_above_rolling_mean_plus_2sigma():
    flags = sd.flag_months(series(BASE + [0.20, 0.03]), window=6, k=2.0, min_count=0)
    assert flags["is_spike"].tolist() == [False] * 6 + [True, False]
    assert flags.loc[6, "baseline_mean"] == pytest.approx(sum(BASE) / 6)


def test_first_window_months_are_not_judged():
    flags = sd.flag_months(series([0.5] + BASE), window=6, k=2.0, min_count=0)
    assert not flags.loc[0, "is_spike"] and pd.isna(flags.loc[0, "threshold"])


def test_min_count_filters_small_months():
    flags = sd.flag_months(series(BASE + [0.20], counts=[20] * 6 + [3]), window=6, k=2.0, min_count=5)
    assert not flags.loc[6, "is_spike"]


def test_partial_months_are_skipped_in_baseline_and_judgment():
    shares = [0.9] + BASE + [0.20, 0.25]
    partial = [True] + [False] * 7 + [True]
    flags = sd.flag_months(series(shares, partial=partial), window=6, k=2.0, min_count=0)
    assert flags.loc[7, "baseline_mean"] == pytest.approx(sum(BASE) / 6)  # 일부 기간 첫 달은 기준선에서 제외
    assert flags.loc[7, "is_spike"] and not flags.loc[8, "is_spike"]     # 일부 기간 마지막 달은 판정 안 함


def test_consecutive_spike_months_become_one_issue():
    flags = sd.flag_months(series(BASE + [0.20, 0.30, 0.02]), window=6, k=2.0, min_count=0)
    issues = sd.group_issues(flags, tech_tag="HBM", method="m")
    assert len(issues) == 1
    row = issues.iloc[0]
    assert row["issue_id"] == "HBM-2024-07"
    assert (row["start_date"], row["end_date"], row["peak_date"]) == ("2024-07-01", "2024-08-31", "2024-08-01")
    assert row["peak_share"] == pytest.approx(0.30) and row["article_count"] == 40
    assert list(issues.columns) == [c.name for c in schema.TABLES["issues"].columns]


def test_no_spike_gives_empty_issue_table():
    issues = sd.group_issues(sd.flag_months(series(BASE * 2), window=6, k=2.0, min_count=0), tech_tag="HBM", method="m")
    assert issues.empty and list(issues.columns) == [c.name for c in schema.TABLES["issues"].columns]


def test_exclude_spikes_keeps_baseline_normal():
    # 큰 급증 달이 기준선에 들어가면 바로 다음 사건을 가린다 → 급증 달을 기준선에서 빼는 옵션
    shares = BASE + [0.40, 0.03, 0.15]
    kept = sd.flag_months(series(shares), window=6, k=2.0, min_count=0, exclude_spikes=False)
    excl = sd.flag_months(series(shares), window=6, k=2.0, min_count=0, exclude_spikes=True)
    assert not kept.loc[8, "is_spike"]  # 0.40이 기준선에 들어가 0.15를 놓침
    assert excl.loc[8, "is_spike"]
