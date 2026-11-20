"""
이슈 분석 화면의 차트(Plotly)와 카드(HTML) 조립. 데이터는 data_access/issue_loader가 읽어 온 표를 받기만 한다.

차트 원칙 (dataviz 가이드):
- 축은 하나만 쓴다. 기사 수와 비중처럼 단위가 다르면 차트를 나눈다 (이중 축 금지).
- 기업 색은 기업에 고정한다: SK하이닉스 주황, 삼성전자 파랑. 기업 필터로 한쪽을 빼도 남은 기업 색은 바뀌지 않는다.
  두 색은 어두운 배경(#181818)에서 색각 이상 시뮬레이션까지 구분되는지 검증 스크립트로 확인했다 (ΔE 26.8).
- 기업이 없는 단일 지표(HBM 비중)는 기업 색과 헷갈리지 않게 밝은 회색 선으로 그린다.
- 급증 구간은 배경 띠로 표시한다: 확정 구간은 진하게, 제외 구간(공시로 확인되지 않음)은 옅은 띠 + 점선 테두리.
- 범례는 계열이 2개 이상일 때만, 마우스를 올리면 값이 나온다 (hover).
배경·글자색은 탭 2(qa_view)의 어두운 테마와 맞춘다.

담당: 김한승 (이슈 분석)
일정: Day 6
"""

import json

import pandas as pd
import plotly.graph_objects as go

from dashboard.components.qa_view import esc

COMPANY_COLORS = {"SK하이닉스": "#d95926", "삼성전자": "#3987e5"}
COMPANY_SHORT = {"SK하이닉스": "SK", "삼성전자": "삼성"}
INK, INK_2, MUTED = "#f0efec", "#c3c2b7", "#898781"
GRID, AXIS = "#2c2c2a", "#383835"
BAND = {"확정": "rgba(255,255,255,0.10)", "검토 전": "rgba(255,255,255,0.06)", "제외": "rgba(255,255,255,0.035)"}
FONT = "Pretendard, Noto Sans KR, Helvetica Neue, Arial, sans-serif"
X_RANGE = ["2023-10-01", "2026-11-01"]  # 분석 기간 월 축 — 세 시계열 차트의 가로축을 맞춘다
MIN_ARTICLES_3M = 3                     # 3개월 기사 수가 이보다 적으면 순감성을 그리지 않는다 (몇 건에 흔들림)


def _layout(fig: go.Figure, height: int, y_title: str, y_format: str = "") -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=64, r=12, t=36, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, color=INK_2, size=12), hovermode="x unified",
        hoverlabel=dict(bgcolor="#252525", bordercolor="#4d4d4d", font=dict(color=INK, family=FONT)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(color=INK_2), bgcolor="rgba(0,0,0,0)"),
        barcornerradius=4, bargap=0.25,
    )
    fig.update_xaxes(showgrid=False, linecolor=AXIS, tickcolor=AXIS, tickfont=dict(color=MUTED))
    fig.update_yaxes(automargin=False)
    fig.update_yaxes(title=dict(text=y_title, font=dict(color=MUTED, size=11)), gridcolor=GRID, zerolinecolor=AXIS,
                     tickfont=dict(color=MUTED), tickformat=y_format)
    return fig


def _month_end(month: str) -> str:
    return (pd.Period(month, "M").end_time + pd.Timedelta(days=1)).strftime("%Y-%m-%d")


def add_issue_bands(fig: go.Figure, issues: pd.DataFrame, legend: bool = True) -> go.Figure:
    """급증 구간 배경 띠 (월 단위 막대·선 위치와 맞도록 구간 첫 달 1일 ~ 마지막 달 다음 달 1일).

    띠 위에 글자를 달면 붙은 구간끼리 겹치므로 대신 범례에 띠 종류(확정/제외)를 넣는다. 구간 이름은 아래 선택 버튼에 있다.
    """
    for r in issues.itertuples(index=False):
        status = r.status
        fig.add_vrect(
            x0=f"{r.start_date[:7]}-01", x1=_month_end(r.end_date[:7]), fillcolor=BAND.get(status, BAND["검토 전"]),
            line=dict(color="rgba(255,255,255,0.25)", width=1, dash="dot") if status == "제외" else dict(width=0),
            layer="below",
        )
    if legend:
        for status, name in (("확정", "급증 구간 (공시로 확인)"), ("제외", "급증 구간 (제외)")):
            if (issues["status"] == status).any():
                fig.add_trace(go.Scatter(
                    x=[None], y=[None], mode="markers", name=name, hoverinfo="skip",
                    marker=dict(symbol="square", size=12, color=BAND[status].replace("0.035", "0.12"),
                                line=dict(color="rgba(255,255,255,0.35)", width=1))))
    return fig


def month_range(start: str, end: str) -> list[str]:
    """가로축 범위: 시작 달 1일 ~ 끝 달 다음 달 1일 (기간 필터와 축을 맞춘다)."""
    return [f"{start}-01", _month_end(end)]


def _x(months: pd.Series) -> pd.Series:
    return pd.to_datetime(months + "-15")  # 막대·점을 달 가운데에 둔다


def share_figure(monthly: pd.DataFrame, issues: pd.DataFrame, height: int = 340, x_range: list[str] | None = None) -> go.Figure:
    """월별 HBM 비중 선 + 급증 달 점 + 급증 구간 띠. 문턱(직전 6개월 평균 + 2σ)은 점선."""
    m = monthly.copy()
    x = _x(m["month"])
    hover = [f"전체 {t:,}건 중 HBM {h}건" + (" · 부분 월" if p else "") for t, h, p in zip(m["total"], m["hbm"], m["partial"])]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=m["threshold"], name="급증 문턱", mode="lines", connectgaps=False,
                             line=dict(color=MUTED, width=1, dash="dot"), hovertemplate="문턱 %{y:.1%}<extra></extra>"))
    fig.add_trace(go.Scatter(x=x, y=m["share"], name="HBM 비중", mode="lines", line=dict(color=INK, width=2),
                             customdata=hover, hovertemplate="HBM 비중 %{y:.1%}<br>%{customdata}<extra></extra>"))
    s = m[m["is_spike"]]
    fig.add_trace(go.Scatter(x=_x(s["month"]), y=s["share"], name="급증 달", mode="markers",
                             marker=dict(size=9, color=INK, line=dict(color="#181818", width=2)),
                             hoverinfo="skip"))
    add_issue_bands(fig, issues)
    fig = _layout(fig, height, "HBM 기사 비중", ".0%")
    fig.update_xaxes(range=x_range or X_RANGE, tickformat="%Y-%m")
    return fig


def count_figure(monthly: pd.DataFrame, height: int = 180, x_range: list[str] | None = None,
                 company_counts: pd.DataFrame | None = None, companies: list[str] | None = None) -> go.Figure:
    """월별 HBM 기사 수 (비중과 단위가 달라 차트를 나눈다).

    기업을 하나 고르면 그 기업이 나온 HBM 기사 수를 기업 색으로 그린다 (기업 필터 반영). 전체면 회색 한 막대.
    """
    fig = go.Figure()
    if company_counts is not None and companies and len(companies) == 1:
        comp = companies[0]
        c = company_counts[company_counts["month"].isin(set(monthly["month"]))]
        col = "skh" if comp == "SK하이닉스" else "sec"
        fig.add_trace(go.Bar(x=_x(c["month"]), y=c[col], name=comp, marker=dict(color=COMPANY_COLORS[comp]),
                             hovertemplate=f"{comp} HBM 기사 %{{y}}건<extra></extra>"))
        title = f"{COMPANY_SHORT[comp]} HBM 기사 수 (건)"
    else:
        fig.add_trace(go.Bar(x=_x(monthly["month"]), y=monthly["hbm"], name="HBM 기사 수", marker=dict(color="#7c7c7c"),
                             hovertemplate="HBM 기사 %{y}건<extra></extra>"))
        title = "HBM 기사 수 (건)"
    fig.update_layout(showlegend=False)
    fig = _layout(fig, height, title)
    fig.update_xaxes(range=x_range or X_RANGE, tickformat="%Y-%m")
    return fig


def coverage_figure(coverage: pd.DataFrame, issues: pd.DataFrame, companies: list[str], height: int = 320) -> go.Figure:
    """급증 구간별 HBM 기사 중 기업 태그 비율 (가로 막대, 기업별 묶음). 마지막 줄 = 급증 구간 밖."""
    label = issues.set_index("issue_id")
    c = coverage.copy()
    c["name"] = [f"{label.loc[p, 'label']}" + (" (제외)" if label.loc[p, "status"] == "제외" else "")
                 if p in label.index else "급증 구간 밖" for p in c["period"]]
    order = [n for n in [*(f"{r.label}" + (" (제외)" if r.status == "제외" else "") for r in issues.itertuples())]
             if n in set(c["name"])] + (["급증 구간 밖"] if "급증 구간 밖" in set(c["name"]) else [])
    c = c.set_index("name").loc[order].reset_index()
    fig = go.Figure()
    for comp in companies:
        key = "skh" if comp == "SK하이닉스" else "sec"
        fig.add_trace(go.Bar(
            y=c["name"], x=c[f"{key}_share"], name=comp, orientation="h", marker=dict(color=COMPANY_COLORS[comp]),
            customdata=list(zip(c[f"{key}_articles"], c["hbm_articles"])),
            text=[f"{v:.0%}" for v in c[f"{key}_share"]], textposition="outside", textfont=dict(color=INK_2, size=11),
            hovertemplate=f"{comp} %{{x:.0%}} (%{{customdata[0]}} / %{{customdata[1]}}건)<extra></extra>"))
    fig.update_layout(barmode="group", hovermode="y unified")
    fig = _layout(fig, height, "")
    fig.update_yaxes(type="category", autorange="reversed", automargin=True)  # '2024-10'을 날짜로 읽지 않게
    fig.update_xaxes(tickformat=".0%", range=[0, 1.12], gridcolor=GRID, showgrid=True)
    return fig


def sentiment_figure(sentiment: pd.DataFrame, issues: pd.DataFrame, companies: list[str], height: int = 320,
                     x_range: list[str] | None = None) -> go.Figure:
    """기업별 3개월 순감성 (−1 ~ 1, 0 = 긍정·부정 같음) + 급증 구간 띠. 월 순감성·기사 수는 hover."""
    fig = go.Figure()
    for comp in companies:
        s = sentiment[(sentiment["company"] == comp) & (sentiment["partial"] == 0)].sort_values("month").copy()
        n3 = s["articles"].rolling(3, min_periods=1).sum()
        s["net_ma3"] = s["net_ma3"].where(n3 >= MIN_ARTICLES_3M)  # 기사가 너무 적은 달은 끊어서 그린다
        hover = [f"이번 달 {a}건 (긍정 {p}·중립 {n}·부정 {g})" for a, p, n, g in
                 zip(s["articles"], s["positive"], s["neutral"], s["negative"])]
        fig.add_trace(go.Scatter(x=_x(s["month"]), y=s["net_ma3"], name=comp, mode="lines",
                                 line=dict(color=COMPANY_COLORS[comp], width=2), customdata=hover,
                                 hovertemplate=f"{comp} 3개월 순감성 %{{y:+.2f}}<br>%{{customdata}}<extra></extra>"))
    fig.add_hline(y=0, line=dict(color=AXIS, width=1))
    add_issue_bands(fig, issues)
    fig = _layout(fig, height, "3개월 순감성")
    fig.update_yaxes(range=[-1.05, 1.05], tickformat="+.1f")
    fig.update_xaxes(range=x_range or X_RANGE, tickformat="%Y-%m")
    return fig


# ── 카드 (HTML) ──
SENT_CLASS = {"긍정": "ok", "부정": "no", "중립": ""}


def _net(v) -> str:
    return "-" if pd.isna(v) else f"{v:+.2f}"


def issue_card_html(issue, period_sent: pd.DataFrame) -> str:
    """선택한 급증 구간: 기간·상태·사건 요약(제외면 제외 이유)·구간 안 기업별 순감성."""
    status = issue["status"]
    badge = {"확정": "ok", "제외": "no"}.get(status, "")
    text = issue["summary"] if status != "제외" else (issue["note"] or issue["summary"])
    sent = "".join(
        f'<span class="qa-badge">{esc(COMPANY_SHORT[r.company])} 순감성 {_net(r.net)} · {r.articles}건</span>'
        for r in period_sent.itertuples(index=False))
    return (f'<div class="qa-answer"><div class="q">{esc(issue["label"])} · HBM 기사 {int(issue["article_count"])}건 · '
            f'최고 비중 {issue["peak_share"]:.1%} (기준선 {issue["baseline_share"]:.1%})</div>'
            f'<div class="a" style="font-size:15px">{esc(text) or "사건 요약 작성 전"}</div>'
            f'<div class="qa-meta"><span class="qa-badge {badge}">사건 요약 {esc(status)}</span>{sent}</div></div>')


def article_list_html(articles: pd.DataFrame) -> str:
    """구간 대표 기사: 제목(원문 링크)·매체·발행일·HBM 관련도·기업별 감성."""
    if articles.empty:
        return '<div class="qa-list"><div class="qa-empty">기사가 없습니다.</div></div>'
    rows = []
    for r in articles.itertuples(index=False):
        badges = [f'<span class="qa-badge">{esc(r.relevance)}</span>']
        for comp, label in (("SK하이닉스", r.sentiment_skh), ("삼성전자", r.sentiment_sec)):
            if isinstance(label, str) and label != "해당없음":
                badges.append(f'<span class="qa-badge {SENT_CLASS.get(label, "")}">{COMPANY_SHORT[comp]} {esc(label)}</span>')
        kw = ", ".join(json.loads(r.issue_keywords)) if isinstance(r.issue_keywords, str) else ""
        rows.append(
            f'<div class="qa-src"><div class="body"><div class="t"><a href="{esc(r.url)}" target="_blank" rel="noopener">'
            f'{esc(r.title)} ↗</a></div><div class="m">{esc(r.published_at)} · {esc(r.media or "")}'
            f'{" · " + esc(kw) if kw else ""}</div><div class="qa-meta">{"".join(badges)}</div></div></div>')
    return "".join(rows)


def evidence_html(evidence: pd.DataFrame) -> str:
    """사람이 확인한 근거 공시 카드: 공시명(DART 링크)·기업·제출일·확인 메모·연결 기사."""
    if evidence.empty:
        return '<div class="qa-list"><div class="qa-empty">사람이 확인한 근거 공시가 없습니다.</div></div>'
    cards = []
    for i, r in enumerate(evidence.itertuples(index=False), 1):
        news = (f'<div class="m">연결 기사: <a href="{esc(r.news_url)}" target="_blank" rel="noopener" '
                f'style="color:inherit">{esc(r.news_title)}</a></div>') if isinstance(r.news_title, str) else ""
        note = f'<div class="x">{esc(r.note)}</div>' if isinstance(r.note, str) and r.note else ""
        cards.append(
            f'<div class="qa-src"><div class="n">{i}</div><div class="body"><div class="t">'
            f'<a href="{esc(r.url)}" target="_blank" rel="noopener">{esc(r.report_nm)} ↗</a></div>'
            f'<div class="m">{esc(r.corp_name)} · {esc(r.rcept_dt)} · {esc(r.match_type)}</div>{news}{note}</div></div>')
    return "".join(cards)


def hero_html(o: dict, reference: str) -> str:
    return (
        '<div class="qa-hero"><div class="qa-eyebrow">이슈 분석 · 뉴스 보도 비중과 논조</div>'
        '<div class="qa-title">HBM 이슈 모니터링</div>'
        f'<div class="qa-sub">반도체 뉴스 <b>{o["articles"]:,}건</b>(중복 제외) 중 HBM 기사 <b>{o["hbm_articles"]}건</b>의 '
        f'보도 비중이 급증한 시기를 찾고, SK하이닉스·삼성전자 보도 점유와 논조를 비교합니다. '
        f'기간 {esc(reference)}</div></div>')


def stats_html(o: dict, ev: dict) -> str:
    def acc(c):
        e = ev.get(c)
        return f'{e["accuracy"]:.2f}' if e else "-"
    n = int(next(iter(ev.values()))["n"]) if ev else 0
    items = [
        (f'{o["hbm_articles"] / o["articles"]:.1%}' if o["articles"] else "-", "전체 기사 중 HBM 비중"),
        (f'{o["confirmed"]} / {o["issues"]}', "급증 구간 (공시로 확인 / 전체)"),
        (f'{acc("SK하이닉스")} · {acc("삼성전자")}', f"감성 4분류 정확도 SK·삼성 (기업별 사람 라벨 {n}건)"),
        (o["verified_evidence"], "사람이 확인한 근거 공시"),
    ]
    cells = "".join(f'<div class="qa-stat"><div class="v">{esc(v)}</div><div class="l">{esc(l)}</div></div>' for v, l in items)
    return f'<div class="qa-stats">{cells}</div>'
