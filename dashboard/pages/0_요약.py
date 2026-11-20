"""
요약 (첫 화면). "이 산업에서 지금 무슨 일이 일어나고 있으며, 그 판단의 근거는 무엇인가"에 한 화면으로 답한다.
저장된 분석 결과만 읽고 LLM·API를 부르지 않는다.

화면: ① 질문 → ② 한 줄 답 → ③ 근거 카드 3장 → ④ 애널리스트에게 권하는 다음 단계 → 한계 → 근거 자세히 보기(이슈 분석·공시 Q&A로 이동)
결론은 전체 분석 기간 기준이라 필터가 없다. 기간·기업을 바꿔 보는 것은 이슈 분석에서 한다.
숫자: components/conclusion.compute_facts (김한승 초안), 화면 조각: components/summary (리포트 6.5)
실행: streamlit run dashboard/app.py → 첫 화면

담당: 공동
일정: Day 7
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # streamlit은 dashboard/만 경로에 넣으므로 프로젝트 루트를 더한다
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from dashboard.components import conclusion as cc  # noqa: E402
from dashboard.components import qa_view  # noqa: E402
from dashboard.components import summary as sm  # noqa: E402
from dashboard.data_access import issue_loader as il  # noqa: E402
from src.common import config  # noqa: E402

st.set_page_config(page_title="요약 · HBM 대시보드", page_icon="🧭", layout="wide")
qa_view.apply_theme()  # 공통 테마 + 카드·지표 모양(.qa-*)
st.markdown(sm.SUMMARY_CSS, unsafe_allow_html=True)

if not config.DB_PATH.exists():
    st.error("DB가 없습니다. README 실행 순서(1~9)대로 분석 결과를 만든 뒤 다시 여세요.")
    st.stop()
DB_KEY = config.DB_PATH.stat().st_mtime  # DB가 바뀌면 캐시를 새로 만든다


@st.cache_data(show_spinner=False)
def load_summary(_key: float) -> dict:
    return {
        "monthly": il.monthly_share(), "issues": il.issue_table(), "coverage": il.company_coverage(),
        "sentiment": il.sentiment_monthly(), "eval": il.eval_summary(),
        "links": il.disclosure_links(config.DB_PATH, [h["rcept_no"] for h in cc.EVIDENCE_HIGHLIGHTS]),
    }


data = load_summary(DB_KEY)
facts = cc.compute_facts(data["monthly"], data["issues"], data["coverage"], data["sentiment"], data["eval"])

qa_view.render_html(sm.hero_html(facts))
qa_view.render_html(sm.cards_html(facts, data["monthly"], data["links"]))
qa_view.render_html(sm.recommend_html(facts))
qa_view.render_html(sm.limits_html(facts))

qa_view.render_html('<div class="qa-section">근거 자세히 보기</div>')
c1, c2 = st.columns(2)
c1.page_link("pages/1_이슈_분석.py", label="이슈 분석 — 보도 비중·급증 구간·기업 점유·감성 추이 (기간·기업 필터)", icon="📈")
c2.page_link("pages/2_공시_QA.py", label="공시 Q&A — 공시 101건에서 근거를 찾아 답하기", icon="📄")
