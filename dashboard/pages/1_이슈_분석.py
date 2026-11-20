"""
이슈 트렌드·감성 추이 화면 (탭 1). 저장된 분석 결과만 읽고 LLM을 부르지 않는다 (초안 §6 구현 원칙).

화면 구성 (초안 §6 탭 1):
1. 요약: 분석 기사·HBM 비중·급증 구간(공시로 확인/전체)·감성 분류 정확도·확인된 근거 공시 수
2. HBM 보도 비중 추이 + 급증 구간 띠(확정/제외) + 월별 HBM 기사 수 (단위가 달라 차트를 나눔)
3. 급증 구간 살펴보기: 사건 요약(확정/제외 이유), 구간 기업별 순감성, 대표 기사(원문 링크·기업별 감성), 사람이 확인한 근거 공시
4. 기업별 보도 점유 (급증 구간별 vs 구간 밖)
5. 기업별 감성 추이 (3개월 순감성) + 검수 정확도·한계 안내
각 차트 아래 '표로 보기'로 숫자를 확인할 수 있다.

필터 (Day 6 종료 조건: 필터가 모든 차트에 반영):
- 기간(월 범위): 요약 지표·비중·기사 수·급증 구간 띠와 선택지·기업 점유·감성 추이·표 전부에 적용
- 기업(전체/SK하이닉스/삼성전자): 기사 수 막대(그 기업 기사 수), 구간 대표 기사·근거 공시(그 기업 것만), 기업 점유·감성 추이(그 기업만)
  HBM 비중 선은 '전체 기사 중 HBM 기사' 지표라 기업과 무관해 그대로 둔다 (캡션에 명시)
- 카테고리: HBM 단독 분석(초안 §11 결정 로그 2026-11-16)이라 기술 카테고리 필터는 두지 않는다

데이터 흐름: data_access/issue_loader(DB·CSV 읽기) → components/issue_charts(차트·카드 조립) → 이 파일(배치·필터)
캐시: DB 파일 수정 시각을 키로 st.cache_data에 둔다 → 분석을 다시 돌려 DB가 바뀌면 자동으로 새로 읽는다.
실행: streamlit run dashboard/app.py → 왼쪽 메뉴 '이슈 분석'

담당: 김한승 (이슈 분석)
일정: Day 6
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # streamlit은 dashboard/만 경로에 넣으므로 프로젝트 루트를 더한다
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from dashboard.components import issue_charts as ic  # noqa: E402
from dashboard.components import qa_view  # noqa: E402
from dashboard.data_access import issue_loader as il  # noqa: E402
from src.common import config  # noqa: E402
from src.llm import prompts  # noqa: E402

st.set_page_config(page_title="이슈 분석 · HBM 대시보드", page_icon="📈", layout="wide")
qa_view.apply_theme()  # 공통 테마(theme.apply_theme, 리포트 6.1) + 카드·지표 모양은 탭 2의 .qa-* CSS를 재사용
PLOT_CONFIG = {"displayModeBar": False}

if not config.DB_PATH.exists():
    st.error("DB가 없습니다. README 실행 순서(6단계)대로 분석 결과를 만든 뒤 다시 여세요.")
    st.stop()
DB_KEY = config.DB_PATH.stat().st_mtime  # DB가 바뀌면 캐시를 새로 만든다


@st.cache_data(show_spinner=False)
def load_all(_key: float) -> dict:
    return {
        "monthly": il.monthly_share(), "issues": il.issue_table(),
        "sentiment": il.sentiment_monthly(), "eval": il.eval_summary(),
        "company_monthly": il.company_monthly(), "evidence_counts": il.evidence_counts(),
    }


@st.cache_data(show_spinner=False)
def load_coverage(_key: float, start: str, end: str):
    return il.coverage_in_range(config.DB_PATH, start, end)


@st.cache_data(show_spinner=False)
def load_issue(_key: float, issue_id: str, start: str, end: str, company: str | None) -> dict:
    return {"articles": il.issue_articles(config.DB_PATH, start, end, company=company),
            "evidence": il.issue_evidence(config.DB_PATH, issue_id, company=company),
            "sentiment": il.period_sentiment(config.DB_PATH, start, end)}


data = load_all(DB_KEY)
all_months = il.month_options(data["monthly"])

hero_slot = st.empty()  # 제목 영역은 맨 위에 두고, 숫자는 필터를 읽은 뒤 채운다

# ── 필터: 기간(월 범위) · 기업 — 아래 모든 차트·카드·표에 같은 기준으로 적용 ──
f1, f2 = st.columns([3, 2], gap="large")
with f1:
    start, end = st.select_slider("기간", options=all_months, value=(all_months[0], all_months[-1]), key="issue_period")
with f2:
    pick = st.segmented_control("기업", ["전체", "SK하이닉스", "삼성전자"], default="전체", key="issue_company")
companies = list(il.COMPANIES) if pick in (None, "전체") else [pick]
company = None if len(companies) > 1 else companies[0]

monthly = il.in_months(data["monthly"], start, end)
issues = il.issues_in_range(data["issues"], start, end)
x_range = ic.month_range(start, end)
overview = il.range_overview(monthly, issues, data["evidence_counts"])
hero_slot.markdown(ic.hero_html(overview, f"{start} ~ {end}"), unsafe_allow_html=True)
qa_view.render_html(ic.stats_html(overview, data["eval"]))

# ── 1. HBM 보도 비중과 급증 구간 ──
qa_view.render_html('<div class="qa-section">HBM 보도 비중과 급증 구간</div>')
st.plotly_chart(ic.share_figure(monthly, issues, x_range=x_range), width="stretch", config=PLOT_CONFIG)
st.plotly_chart(ic.count_figure(monthly, x_range=x_range, company_counts=data["company_monthly"], companies=companies),
                width="stretch", config=PLOT_CONFIG)
st.caption(
    "비중 = HBM 기사(제목 포함 또는 본문 5회 이상, 중복 제외) / 그달 전체 기사. 급증 = 직전 6개월(급증 달·부분 월 제외) "
    "평균 + 2σ 초과이면서 HBM 기사 10건 이상 (`rolling6m_2sigma_exclude_spikes_min10_v1`). 진한 띠 = 같은 시기 공시로 "
    "중심 보도를 확인한 구간, 점선 띠 = 공시로 확인되지 않아 분석에서 뺀 구간. 2023-10·2026-10은 일부 기간만 수집된 달. "
    "HBM 비중은 기업과 무관한 지표라 기업 필터와 상관없이 같고, 아래 막대는 기업을 고르면 그 기업이 나온 HBM 기사 수다.")
with st.expander("표로 보기 — 월별 비중"):
    st.dataframe(monthly[["month", "total", "hbm", "share", "threshold", "status"]].rename(columns={
        "month": "월", "total": "전체 기사", "hbm": "HBM 기사", "share": "HBM 비중", "threshold": "급증 문턱", "status": "판정"}),
        hide_index=True, width="stretch")

# ── 2. 급증 구간 살펴보기 ──
qa_view.render_html('<div class="qa-section">급증 구간 살펴보기</div>')
labels = {f'{r.label}{" (제외)" if r.status == "제외" else ""}': r.issue_id for r in issues.itertuples()}
if not labels:
    st.info("선택한 기간에 급증 구간이 없습니다. 기간을 넓혀 보세요.")
chosen = st.segmented_control("급증 구간", list(labels), default=next(iter(labels), None), key=f"issue_pick_{start}_{end}") \
    if labels else None
if chosen:
    issue = issues.set_index("issue_id").loc[labels[chosen]]
    detail = load_issue(DB_KEY, labels[chosen], issue["start_date"], issue["end_date"], company)
    qa_view.render_html(ic.issue_card_html(issue, detail["sentiment"]))
    left, right = st.columns(2, gap="large")
    with left:
        qa_view.render_html(f'<div class="qa-section" style="font-size:18px">대표 기사 {len(detail["articles"])}건</div>')
        qa_view.render_html(ic.article_list_html(detail["articles"]))
        st.caption("제목에 HBM이 있는 기사 먼저, 발행일 순. 감성은 LLM 판정(검수 정확도는 아래 '기업별 감성 추이')."
                   + (f" 기업 필터: {company}이(가) 나온 기사만." if company else ""))
    with right:
        qa_view.render_html(f'<div class="qa-section" style="font-size:18px">확인된 근거 공시 {len(detail["evidence"])}건</div>')
        qa_view.render_html(ic.evidence_html(detail["evidence"]))
        st.caption("자동으로 찾은 후보 중 사람이 원문을 보고 확인한 공시만 보인다. 같은 시기 공시 ≠ 보도의 원인."
                   + (f" 기업 필터: {company} 공시만." if company else ""))

# ── 3. 기업별 보도 점유 ──
qa_view.render_html('<div class="qa-section">기업별 보도 점유</div>')
coverage = load_coverage(DB_KEY, start, end)
st.plotly_chart(ic.coverage_figure(coverage, issues, companies), width="stretch", config=PLOT_CONFIG)
st.caption("선택 기간 안의 HBM 기사만 센다. 구간 HBM 기사 중 그 기업이 제목에 나오거나 본문에 5회 이상 나오는 기사 비율. 두 기업이 함께 나오면 양쪽에 센다. "
           "기업명 없이 인물만 나오는 기사(예: 'SK그룹 회장')는 잡히지 않는다. 보도 점유 ≠ 시장 점유율.")
with st.expander("표로 보기 — 기업 점유"):
    st.dataframe(coverage, hide_index=True, width="stretch")

# ── 4. 기업별 감성 추이 ──
qa_view.render_html('<div class="qa-section">기업별 감성 추이</div>')
sentiment = il.in_months(data["sentiment"], start, end)
st.plotly_chart(ic.sentiment_figure(sentiment, issues, companies, x_range=x_range), width="stretch", config=PLOT_CONFIG)
ev = data["eval"]
acc = " · ".join(f'{c} 정확도 {e["accuracy"]:.2f} (95% CI {e["ci_low"]:.2f}–{e["ci_high"]:.2f})' for c, e in ev.items())
st.caption(
    f"3개월 순감성 = 최근 3개월 (긍정 − 부정) / 그 기업이 나온 HBM 기사 수 (−1에서 +1, 3개월 기사 3건 미만이면 끊음). LLM `{config.LLM_MODEL}` · 프롬프트 "
    f"`{prompts.PROMPT_VERSION}`로 미리 분류해 저장한 결과다. 표본 검수: {acc or '결과 없음'}. 검수 규칙을 같은 표본에서 "
    "다듬어 정확도가 실제보다 높게 나왔을 수 있다. 보도 논조 ≠ 실제 사업 성과.")
with st.expander("표로 보기 — 월별 감성"):
    st.dataframe(sentiment[sentiment["company"].isin(companies)], hide_index=True, width="stretch")
