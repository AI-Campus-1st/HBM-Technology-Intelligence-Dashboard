"""
공시 Q&A 화면. 저장된 벡터 DB를 조회하고 근거 공시를 함께 보여준다.

- 질문 → src.rag.qa_chain.ask (하이브리드 검색 + LLM config.LLM_MODEL). 근거가 없으면 거절한다.
- 답변 아래에 근거 공시(공시명·제출일·위치·DART 링크·발췌)를 보인다.
- 벡터 DB·API 키가 없으면 질문 대신 준비 방법을 안내한다. 아래쪽 RAG 대상 공시 목록은 DB만 있으면 보인다.
실행: streamlit run dashboard/app.py → 왼쪽 메뉴 '공시 QA'

담당: 한도윤 (공시 분석)
일정: Day 6
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # streamlit은 dashboard/만 경로에 넣으므로 프로젝트 루트를 더한다
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from dashboard.components import qa_view  # noqa: E402
from dashboard.data_access import disclosure_loader as loader  # noqa: E402
from src.common import config  # noqa: E402
from src.rag import build_index, qa_chain  # noqa: E402

HISTORY_LIMIT = 10

st.set_page_config(page_title="공시 Q&A · HBM 대시보드", page_icon="📄", layout="wide")
qa_view.apply_theme()

manifest = loader.load_manifest()
summary = loader.load_eval_summary()
qa_view.render_html(qa_view.hero_html(manifest, f"{config.REFERENCE_DATE:{config.DATE_FORMAT}}"))
qa_view.render_html(qa_view.stats_html(manifest, summary))

problems = loader.readiness(manifest)
for p in problems:
    st.warning(p)

# ── 질문 ──
state = st.session_state
state.setdefault("qa_history", [])
state.setdefault("qa_question", "")


def pick_example():
    if state.get("qa_example"):
        state["qa_question"] = state["qa_example"]


st.pills("예시 질문", [q for q, _ in qa_chain.SAMPLE_QUESTIONS], key="qa_example", on_change=pick_example)

with st.form("qa_form", border=False):
    col_q, col_b = st.columns([4, 1],vertical_alignment="bottom")
    question = col_q.text_input("질문", key="qa_question", placeholder="예: SK하이닉스 청주 M15X 신규 시설투자 금액은?",
                                label_visibility="collapsed")
    submitted = col_b.form_submit_button("질문하기", type="primary", use_container_width=True, disabled=bool(problems))

if submitted and question.strip():
    try:
        with st.spinner("공시에서 근거를 찾는 중…"):
            store = loader.get_store()
            result = qa_chain.ask(question.strip(), store, loader.get_llm())
            texts = loader.chunk_texts(store, [s["chunk_id"] for s in result.sources])
        state["qa_history"] = [(result, texts)] + state["qa_history"][: HISTORY_LIMIT - 1]
    except Exception as e:  # API 오류 등: 키·내용은 보이지 않고 종류만 알린다
        st.error(f"답변을 만들지 못했습니다 ({type(e).__name__}). 네트워크와 API 키를 확인해 주세요.")
elif submitted:
    st.info("질문을 입력해 주세요.")

if state["qa_history"]:
    latest, texts = state["qa_history"][0]
    qa_view.render_result(latest, texts)
    if len(state["qa_history"]) > 1:
        with st.expander(f"이전 질문 {len(state['qa_history']) - 1}개"):
            for old, old_texts in state["qa_history"][1:]:
                qa_view.render_result(old, old_texts)

# ── RAG 대상 공시 ──
qa_view.render_html('<div class="qa-section">검색 대상 공시</div>')
disclosures = loader.load_rag_disclosures()
corp = st.pills("기업", ["전체", *config.TARGET_COMPANIES], default="전체", key="qa_corp")
types = st.pills("공시 유형", list(loader.TYPE_NAMES.values()), selection_mode="multi", key="qa_types")
view = disclosures
if corp and corp != "전체":
    view = view[view["corp_name"] == corp]
if types:
    view = view[view["type_name"].isin(types)]
st.caption(f"{len(view)}건 / 전체 {len(disclosures)}건 · 공시명을 누르면 DART 원문이 열립니다.")
qa_view.render_html(qa_view.disclosure_list_html(view))

st.caption(
    f"LLM {config.LLM_MODEL} · 임베딩 {build_index.EMBEDDING_MODEL} · 검색 상위 {qa_chain.K}개(벡터+키워드 RRF) · "
    f"거리 기준 {qa_chain.MAX_DISTANCE}"
    + (f" · 벡터 DB 지문 {manifest['chunks_fingerprint']}" if manifest else "")
    + " · 답변은 공시 근거만 쓰며, 평가에서 놓친 질문이 있어 원문 확인을 권합니다 (리포트 5.4)."
)
