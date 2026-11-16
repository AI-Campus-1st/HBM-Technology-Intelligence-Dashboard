"""
기업·공시유형·일자별 공시 건수 추이 집계 (Day 3 EDA, 리포트 3장).

- 대상: DB disclosure 테이블의 공시 목록 전체 (568건). RAG 대상 여부(rag_target)와 관계없이 센다.
  "회사가 언제 무엇을 공시했나"를 보는 것이라, 원문·RAG 기준을 바꿔도 결과가 바뀌지 않는다.
- 기준 날짜: 제출일(rcept_dt). 뉴스 발행일과 같은 월(또는 분기) 축으로 맞춘다.
  첫 달(2023-10, 19일부터)과 마지막 달(2026-10, 19일까지)은 일부 기간만 있어 partial=True로 표시한다.
- 유형 합계만 보면 정기성 공시에 묻힌다. J 공정위공시는 분기마다 반복되고, I 거래소공시의 상당수는
  배당·IR·지분 변동이다. 그래서 공시명으로 성격(category)을 붙이고, 사건성 공시(EVENT_CATEGORIES)를 따로 센다.
- 집계 함수는 기간·기업·유형 필터를 인자로 받는다. Day 6 대시보드(disclosure_loader)가 그대로 부른다.

실행: python -m src.eda.disclosure_trend   (parse_documents 다음. DB만 읽고 쓰지 않는다)

저장:
- outputs/reports/disclosure_monthly_counts.csv  : 기업 × 월 × 유형 건수 (0건 달 포함)
- outputs/reports/disclosure_type_distribution.csv : 기업 × 유형 건수·비중
- outputs/reports/disclosure_category_counts.csv : 기업 × 공시 성격 건수
- outputs/reports/disclosure_event_timeline.csv : 사건성 공시 날짜순 목록 (급증 시점 근거 후보)
- outputs/figures/disclosure_monthly.html : 기업별 월별 공시 건수(유형별 누적) + 사건성 공시 (Plotly)

담당: 한도윤 (공시 분석)
일정: Day 3
"""

import re
from collections.abc import Iterable
from datetime import date
from pathlib import Path

import pandas as pd

from src.common import config, db, schema

REPORTS_DIR = config.OUTPUTS_DIR / "reports"
FIGURES_DIR = config.OUTPUTS_DIR / "figures"
MONTHLY_PATH = REPORTS_DIR / "disclosure_monthly_counts.csv"
TYPE_DIST_PATH = REPORTS_DIR / "disclosure_type_distribution.csv"
CATEGORY_PATH = REPORTS_DIR / "disclosure_category_counts.csv"
TIMELINE_PATH = REPORTS_DIR / "disclosure_event_timeline.csv"
FIGURE_PATH = FIGURES_DIR / "disclosure_monthly.html"

TYPE_NAMES = {"A": "정기공시", "B": "주요사항보고", "D": "지분공시", "I": "거래소공시", "J": "공정위공시"}
COLUMNS = ["rcept_no", "corp_name", "report_nm", "rcept_dt", "pblntf_ty", "url"]

# 공시명 → 공시 성격. 위에서부터 처음 맞는 것을 쓴다. 공시명 앞의 [기재정정] 등은 떼고 본다.
# 근거: 2026-11-16 공시명 분포 확인 (B 8종, I 43종, J 14종). 투자판단관련주요경영사항(2024-12-20)은
# 인디애나 HBM 패키징 공장 투자라 투자·설비로 본다. 기타경영사항(자율공시)는 내용이 섞여 기타로 둔다.
CATEGORY_RULES: list[tuple[str, str]] = [
    ("투자·설비", r"신규시설투자|투자판단관련|유형자산취득|타법인주식및출자증권취득|영업양수|영업양도"),
    ("실적", r"영업\(잠정\)실적|매출액또는손익구조"),
    ("사업계획", r"장래사업|기업가치제고계획"),
    ("풍문·해명", r"조회공시요구|풍문또는보도"),
    ("공급계약", r"단일판매|공급계약"),
    ("자본·주주환원", r"자기주식|주식소각|배당|주주명부|유상증자|증권예탁증권|해외증권시장|교환사채|전환가액|주식관련사채"),
    ("지배구조·주총", r"주주총회|대표이사|지배구조|의결권대리행사"),
    ("지분변동", r"최대주주등소유주식변동"),
    ("정기보고서", r"사업보고서|반기보고서|분기보고서|감사보고서제출"),
    ("공정위 거래", r"계열회사|특수관계인|대규모기업집단|지급수단별"),
]
OTHER_CATEGORY = "기타"
# 회사의 사업·투자·실적 변화를 알리는 공시. 이슈 급증 시점의 근거 후보로 본다.
EVENT_CATEGORIES = ("투자·설비", "실적", "사업계획", "풍문·해명", "공급계약")
CATEGORY_ORDER = [c for c, _ in CATEGORY_RULES] + [OTHER_CATEGORY]

_PREFIX = re.compile(r"^\s*(\[[^\]]*\]\s*)+")
_RULES = [(c, re.compile(p)) for c, p in CATEGORY_RULES]


def clean_name(report_nm: str) -> str:
    """공시명 앞의 [기재정정]·[분기별공시(...)] 같은 꼬리표를 뗀다."""
    return _PREFIX.sub("", report_nm).strip()


def categorize(report_nm: str) -> str:
    """공시명으로 공시 성격을 정한다. 규칙에 없으면 '기타'."""
    name = clean_name(report_nm)
    for category, pattern in _RULES:
        if pattern.search(name):
            return category
    return OTHER_CATEGORY


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """집계용 컬럼(date, month, quarter, category, is_event)을 붙인다."""
    out = df.copy()
    out["date"] = pd.to_datetime(out["rcept_dt"], format=config.DATE_FORMAT)
    out["month"] = out["date"].dt.to_period("M").astype(str)
    out["quarter"] = out["date"].dt.to_period("Q").astype(str)
    out["category"] = out["report_nm"].map(categorize)
    out["is_event"] = out["category"].isin(EVENT_CATEGORIES)
    return out


def load_disclosures(db_path: Path = config.DB_PATH) -> pd.DataFrame:
    """DB에서 공시 목록을 읽어 집계용 컬럼을 붙인다."""
    conn = db.connect(db_path)
    try:
        df = db.read_table(conn, "disclosure", columns=COLUMNS)
    finally:
        conn.close()
    return prepare(df)


def filter_disclosures(
    df: pd.DataFrame,
    start: date | str | None = None,
    end: date | str | None = None,
    companies: Iterable[str] | None = None,
    types: Iterable[str] | None = None,
) -> pd.DataFrame:
    """기간(양 끝 포함)·기업·유형 필터. None이면 그 조건은 걸지 않는다. 대시보드 공통 필터와 같은 인자."""
    mask = pd.Series(True, index=df.index)
    if start is not None:
        mask &= df["date"] >= pd.Timestamp(start)
    if end is not None:
        mask &= df["date"] <= pd.Timestamp(end)
    if companies is not None:
        mask &= df["corp_name"].isin(list(companies))
    if types is not None:
        mask &= df["pblntf_ty"].isin(list(types))
    return df[mask]


def period_range(start: date | str, end: date | str, freq: str = "M") -> list[str]:
    """start~end를 덮는 기간 목록 ('2023-10' 또는 '2023Q4'). 건수가 0인 달도 축에 남기려고 쓴다."""
    return [str(p) for p in pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq=freq)]


def is_partial(period: str, start: date | str, end: date | str, freq: str = "M") -> bool:
    """분석 기간이 그 달(분기) 전체를 덮지 못하면 True."""
    p = pd.Period(period, freq=freq)
    return p.start_time < pd.Timestamp(start) or p.end_time.normalize() > pd.Timestamp(end)


def period_counts(
    df: pd.DataFrame,
    freq: str = "M",
    by: str | None = "pblntf_ty",
    start: date | str = config.ANALYSIS_START,
    end: date | str = config.ANALYSIS_END,
) -> pd.DataFrame:
    """기업 × 기간 × by(유형 또는 category) 건수. 0건인 칸도 채운 긴 표 (corp_name, period, [by], count, partial).

    df는 prepare()를 거친 표(필터 후여도 됨). 기업은 df에 있는 기업만, by 값은 df에 나온 값만 쓴다.
    by=None이면 기업 × 기간 합계만 센다.
    """
    col = {"M": "month", "Q": "quarter"}[freq]
    levels = [sorted(df["corp_name"].unique()), period_range(start, end, freq)]
    names, group = ["corp_name", "period"], ["corp_name", col]
    if by is not None:
        levels.append(sorted(df[by].unique()))
        names.append(by)
        group.append(by)
    full = pd.MultiIndex.from_product(levels, names=names)
    counts = df.groupby(group).size().rename("count")
    counts.index = counts.index.set_names(names)
    out = counts.reindex(full, fill_value=0).reset_index()
    out["count"] = out["count"].astype(int)
    out["partial"] = out["period"].map(lambda p: is_partial(p, start, end, freq))
    return out


def monthly_counts(df: pd.DataFrame, **filters) -> pd.DataFrame:
    """필터 적용 후 기업 × 월 × 유형 건수 (대시보드용 진입점)."""
    period = {k: filters[k] for k in ("start", "end") if filters.get(k) is not None}
    return period_counts(filter_disclosures(df, **filters), "M", "pblntf_ty", **period)


def type_distribution(df: pd.DataFrame) -> pd.DataFrame:
    """기업 × 유형 건수와 기업 안 비중. 유형 이름(type_name)을 붙인다."""
    out = df.groupby(["corp_name", "pblntf_ty"]).size().rename("count").reset_index()
    out["share"] = (out["count"] / out.groupby("corp_name")["count"].transform("sum")).round(3)
    out.insert(2, "type_name", out["pblntf_ty"].map(TYPE_NAMES))
    return out


def category_counts(df: pd.DataFrame) -> pd.DataFrame:
    """기업 × 공시 성격 건수 (넓은 표, 성격 순서 고정). is_event 열로 사건성 여부를 표시한다."""
    out = df.pivot_table(index="category", columns="corp_name", values="rcept_no", aggfunc="count", fill_value=0)
    out = out.reindex([c for c in CATEGORY_ORDER if c in out.index])
    out["합계"] = out.sum(axis=1)
    out.insert(0, "is_event", out.index.isin(EVENT_CATEGORIES))
    return out.reset_index()


def event_timeline(df: pd.DataFrame) -> pd.DataFrame:
    """사건성 공시를 날짜순으로 (근거 후보: 공시명·제출일·링크)."""
    ev = df[df["is_event"]].sort_values(["rcept_dt", "corp_name", "rcept_no"])
    return ev[["rcept_dt", "corp_name", "category", "pblntf_ty", "report_nm", "rcept_no", "url"]].reset_index(drop=True)


def figure_monthly(df: pd.DataFrame, start=config.ANALYSIS_START, end=config.ANALYSIS_END):
    """기업별로 위아래 패널: 월별 유형 누적 막대 + 사건성 공시 건수 선. 일부 기간인 달은 제목에 적는다."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    counts = period_counts(df, "M", "pblntf_ty", start, end)
    events = period_counts(df[df["is_event"]], "M", None, start, end) if df["is_event"].any() else None
    corps = sorted(df["corp_name"].unique(), key=lambda c: c != config.PRIMARY_CORP_NAME)
    fig = make_subplots(rows=len(corps), cols=1, shared_xaxes=True, vertical_spacing=0.08, subplot_titles=corps)
    colors = {"A": "#4C78A8", "B": "#F58518", "D": "#54A24B", "I": "#B279A2", "J": "#9D9D9D"}
    for row, corp in enumerate(corps, start=1):
        c = counts[counts["corp_name"] == corp]
        for ty in schema.DISCLOSURE_TYPES:
            s = c[c["pblntf_ty"] == ty]
            if s.empty:
                continue
            fig.add_bar(x=s["period"], y=s["count"], name=f"{ty} {TYPE_NAMES[ty]}", marker_color=colors[ty],
                        legendgroup=ty, showlegend=row == 1, row=row, col=1)
        if events is not None:
            e = events[(events["corp_name"] == corp)]
            fig.add_scatter(x=e["period"], y=e["count"], name="사건성 공시", mode="lines+markers",
                            line=dict(color="#E45756", width=2), legendgroup="event", showlegend=row == 1,
                            row=row, col=1)
    partial = sorted(counts.loc[counts["partial"], "period"].unique())
    note = f"<br><sup>일부 기간만 포함된 달: {', '.join(partial)}</sup>" if partial else ""
    fig.update_layout(barmode="stack", height=320 * len(corps),
                      title="기업별 월별 공시 건수 (제출일 기준, 유형별 누적)" + note,
                      legend=dict(orientation="h", y=-0.12))
    fig.update_yaxes(title_text="건수")
    return fig


def main(db_path: Path = config.DB_PATH, save_figure: bool = True) -> dict[str, pd.DataFrame]:
    df = load_disclosures(db_path)
    monthly = period_counts(df, "M", "pblntf_ty")
    dist = type_distribution(df)
    cats = category_counts(df)
    timeline = event_timeline(df)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    for frame, path in ((monthly, MONTHLY_PATH), (dist, TYPE_DIST_PATH), (cats, CATEGORY_PATH), (timeline, TIMELINE_PATH)):
        frame.to_csv(path, index=False, encoding="utf-8-sig")
    if save_figure:
        FIGURES_DIR.mkdir(parents=True, exist_ok=True)
        figure_monthly(df).write_html(FIGURE_PATH, include_plotlyjs="cdn")

    print(f"공시 {len(df):,}건, 기간 {df['rcept_dt'].min()} ~ {df['rcept_dt'].max()}")
    print("\n[기업 × 유형]")
    print(dist.pivot(index=["pblntf_ty", "type_name"], columns="corp_name", values="count").fillna(0).astype(int).to_string())
    print("\n[공시 성격]")
    print(cats.to_string(index=False))
    q = period_counts(df[df["is_event"]], "Q", None)
    print("\n[분기별 사건성 공시]")
    print(q.pivot(index="period", columns="corp_name", values="count").to_string())
    print(f"\n저장: {MONTHLY_PATH.name}, {TYPE_DIST_PATH.name}, {CATEGORY_PATH.name}, {TIMELINE_PATH.name}"
          + (f", {FIGURE_PATH}" if save_figure else ""))
    return {"monthly": monthly, "type_distribution": dist, "category": cats, "timeline": timeline}


if __name__ == "__main__":
    main()
