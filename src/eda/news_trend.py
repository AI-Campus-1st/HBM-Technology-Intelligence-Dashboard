"""
뉴스 기사량·HBM 비중·기업 점유 추이와 카테고리별 무관 기사 비중 (Day 3 EDA, 리포트 3장).

대상: 중복이 아닌 기사(news.is_duplicate = 0, preprocess.py 결과) 7,177 − 224 = 6,953건.
태그: news_tag(regex_v3). 기사 1행 + HBM·SK하이닉스·삼성전자 관련도 열로 펼쳐서 쓴다.

정의 (초안 v1.2 §4.3, 결정 로그):
- HBM 기사: HBM 태그가 '핵심' 또는 '관련' (사람 검수 반영 추정 정밀도 0.83·재현율 0.85).
  '핵심'(제목 포함)만 센 열(hbm_core·share_core)을 같이 둔다. 정밀도가 높은 보수적 지표라 결과를 교차 확인한다.
- 관심도 = HBM 기사 수 / 같은 달 전체 기사 수 (비중). 월별 수집량 변동(68~657건)이 커서 절대량으로 비교하지 않는다.
- 기업 점유: HBM 기사 중 그 기업 태그가 '핵심'·'관련'인 기사 비율. 기업 태그는 HBM 기사 안에서만 쓴다
  (단독·'언급' 정밀도가 낮음). 두 기업이 함께 나오는 기사는 양쪽에 센다 (합이 1을 넘을 수 있다).
- 무관 기사: HBM 핵심·관련이 아닌 기사. 카테고리별 비율로 분석 범위를 판단한다.
- 월 축과 일부 기간 달(partial) 표시는 공시 추이(disclosure_trend)와 같은 함수를 써서 축을 맞춘다.

실행: python -m src.eda.news_trend   (preprocess 다음. DB만 읽고 쓰지 않는다)

저장:
- outputs/reports/news_monthly_volume.csv   : 월 × 카테고리 기사 수
- outputs/reports/news_hbm_monthly.csv      : 월별 전체·HBM 기사 수와 비중 (spike_detection 입력)
- outputs/reports/news_company_monthly.csv  : 월별 HBM 기사 중 기업별 기사 수·점유
- outputs/reports/news_category_relevance.csv : 카테고리별 HBM 기사·무관 기사 비율
- outputs/figures/news_hbm_monthly.html     : 월별 기사 수(막대)와 HBM 비중(선) (plotly가 있을 때)

담당: 김한승 (이슈 분석)
일정: Day 3
"""

from datetime import date
from pathlib import Path

import pandas as pd

from src.common import config, db
from src.eda.disclosure_trend import is_partial, period_range

REPORTS_DIR = config.OUTPUTS_DIR / "reports"
FIGURES_DIR = config.OUTPUTS_DIR / "figures"
VOLUME_PATH = REPORTS_DIR / "news_monthly_volume.csv"
HBM_PATH = REPORTS_DIR / "news_hbm_monthly.csv"
COMPANY_PATH = REPORTS_DIR / "news_company_monthly.csv"
CATEGORY_PATH = REPORTS_DIR / "news_category_relevance.csv"
FIGURE_PATH = FIGURES_DIR / "news_hbm_monthly.html"

ANALYSIS_LEVELS = ("핵심", "관련")  # HBM 기사·기업 언급으로 인정하는 관련도
CATEGORY_SEP = "; "
TAG_COLUMNS = {"HBM": "hbm", "SK하이닉스": "skh", "삼성전자": "sec"}


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """기사 표에 month(YYYY-MM) 열을 붙인다. 입력: news_id, published_at, category, hbm, skh, sec."""
    out = df.copy()
    out["month"] = out["published_at"].str[:7]
    return out


def load_articles(db_path: Path = config.DB_PATH) -> pd.DataFrame:
    """중복이 아닌 기사와 HBM·기업 태그 관련도를 기사 1행으로 읽는다."""
    conn = db.connect(db_path)
    try:
        news = db.read_table(conn, "news", columns=["news_id", "published_at", "category", "is_duplicate"])
        tags = db.read_table(conn, "news_tag", columns=["news_id", "tag", "relevance"])
    finally:
        conn.close()
    news = news[news["is_duplicate"] == 0].drop(columns="is_duplicate")
    wide = (tags[tags["tag"].isin(TAG_COLUMNS)]
            .pivot(index="news_id", columns="tag", values="relevance")
            .rename(columns=TAG_COLUMNS))
    for col in TAG_COLUMNS.values():
        if col not in wide:
            wide[col] = None
    out = news.merge(wide[list(TAG_COLUMNS.values())], left_on="news_id", right_index=True, how="left")
    return prepare(out.astype(object).where(out.notna(), None)).reset_index(drop=True)


def _month_frame(start: date, end: date) -> pd.DataFrame:
    months = period_range(start, end)
    return pd.DataFrame({"month": months, "partial": [is_partial(m, start, end) for m in months]})


def _counts(series: pd.Series, months: pd.DataFrame) -> pd.Series:
    """월별 건수를 전체 월 축에 맞춘다 (없는 달은 0)."""
    return months["month"].map(series.groupby(series).size()).fillna(0).astype(int)


def monthly_volume(articles: pd.DataFrame, start=config.ANALYSIS_START, end=config.ANALYSIS_END) -> pd.DataFrame:
    """월 × 카테고리 기사 수. 카테고리가 둘인 기사는 양쪽에 센다 (total은 기사 수)."""
    out = _month_frame(start, end)
    out["total"] = _counts(articles["month"], out)
    exploded = articles.assign(category=articles["category"].fillna("").str.split(CATEGORY_SEP)).explode("category")
    for name in sorted(c for c in exploded["category"].unique() if c):
        out[name] = _counts(exploded.loc[exploded["category"] == name, "month"], out)
    return out


def monthly_hbm(articles: pd.DataFrame, start=config.ANALYSIS_START, end=config.ANALYSIS_END,
                levels: tuple = ANALYSIS_LEVELS) -> pd.DataFrame:
    """월별 전체 기사 수, HBM 기사 수·비중, '핵심'만 센 수·비중. 기사가 없는 달의 비중은 0."""
    out = _month_frame(start, end)
    out["total"] = _counts(articles["month"], out)
    out["hbm"] = _counts(articles.loc[articles["hbm"].isin(levels), "month"], out)
    out["hbm_core"] = _counts(articles.loc[articles["hbm"] == "핵심", "month"], out)
    denom = out["total"].where(out["total"] > 0)
    out["share"] = (out["hbm"] / denom).fillna(0.0)
    out["share_core"] = (out["hbm_core"] / denom).fillna(0.0)
    return out


def company_monthly(articles: pd.DataFrame, start=config.ANALYSIS_START, end=config.ANALYSIS_END) -> pd.DataFrame:
    """월별 HBM 기사 중 기업 태그가 '핵심'·'관련'인 기사 수와 점유."""
    out = _month_frame(start, end)
    hbm = articles[articles["hbm"].isin(ANALYSIS_LEVELS)]
    out["hbm"] = _counts(hbm["month"], out)
    denom = out["hbm"].where(out["hbm"] > 0)
    for col in ("skh", "sec"):
        out[col] = _counts(hbm.loc[hbm[col].isin(ANALYSIS_LEVELS), "month"], out)
        out[f"{col}_share"] = (out[col] / denom).fillna(0.0)
    return out


def category_relevance(articles: pd.DataFrame) -> pd.DataFrame:
    """카테고리별 기사 수, HBM 기사 수·비율, 무관 기사 비율 (복수 카테고리 기사는 각각 센다)."""
    exploded = articles.assign(category=articles["category"].fillna("").str.split(CATEGORY_SEP)).explode("category")
    exploded = exploded[exploded["category"] != ""]
    g = exploded.groupby("category")
    out = pd.DataFrame({"total": g.size(), "hbm": g["hbm"].apply(lambda s: s.isin(ANALYSIS_LEVELS).sum())})
    out["hbm_share"] = out["hbm"] / out["total"]
    out["unrelated_share"] = 1 - out["hbm_share"]
    return out.reset_index().sort_values("total", ascending=False).reset_index(drop=True)


def figure_hbm(monthly: pd.DataFrame):
    """월별 기사 수(막대, 왼쪽 축)와 HBM 비중(선, 오른쪽 축). 일부 기간 달은 점선 표시."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=monthly["month"], y=monthly["total"], name="전체 기사 수", marker_color="#c9d3e0")
    fig.add_scatter(x=monthly["month"], y=monthly["share"] * 100, name="HBM 비중 (핵심+관련, %)",
                    mode="lines+markers", secondary_y=True)
    fig.add_scatter(x=monthly["month"], y=monthly["share_core"] * 100, name="HBM 비중 (핵심만, %)",
                    mode="lines", line={"dash": "dot"}, secondary_y=True)
    fig.update_yaxes(title_text="기사 수", secondary_y=False)
    fig.update_yaxes(title_text="HBM 비중 (%)", secondary_y=True)
    fig.update_layout(title="월별 기사 수와 HBM 기사 비중 (중복 제외)", hovermode="x unified")
    return fig


def main(db_path: Path = config.DB_PATH, save_figure: bool = True) -> dict[str, pd.DataFrame]:
    articles = load_articles(db_path)
    results = {
        VOLUME_PATH: monthly_volume(articles),
        HBM_PATH: monthly_hbm(articles),
        COMPANY_PATH: company_monthly(articles),
        CATEGORY_PATH: category_relevance(articles),
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    for path, frame in results.items():
        frame.to_csv(path, index=False, encoding="utf-8-sig")
    saved_figure = False
    if save_figure:
        try:
            FIGURES_DIR.mkdir(parents=True, exist_ok=True)
            figure_hbm(results[HBM_PATH]).write_html(FIGURE_PATH, include_plotlyjs="cdn")
            saved_figure = True
        except ModuleNotFoundError:
            print("plotly가 없어 그림은 건너뜁니다 (pip install -r requirements.txt).")
    m = results[HBM_PATH]
    print(f"기사 {len(articles):,}건 (중복 제외), HBM 기사 {int(m['hbm'].sum())}건 (핵심 {int(m['hbm_core'].sum())})")
    print(results[CATEGORY_PATH].to_string(index=False))
    print("저장: " + ", ".join(str(p) for p in results) + (f", {FIGURE_PATH}" if saved_figure else ""))
    return {p.stem: f for p, f in results.items()}


if __name__ == "__main__":
    main()
