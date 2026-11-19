"""
공시 Q&A 화면. 저장된 벡터 DB를 조회하고 근거 공시를 함께 보여준다.

- 예시 질문: 미리 저장한 답변(outputs/reports/qa_samples.json)을 바로 보여 준다. API를 부르지 않는다.
- 직접 입력한 질문: src.rag.qa_chain.ask (하이브리드 검색 + LLM config.LLM_MODEL)로 실시간 답변. 근거가 없으면 거절한다.
  (대시보드는 저장된 결과만 읽는 것이 원칙이지만, 자유 질문은 미리 만들어 둘 수 없어 이 경우만 예외로 둔다. 리포트 5.5)
- 정밀 검색(선택): 재정렬 모델(requirements/rerank.txt)이 설치돼 있으면 켤 수 있다. CPU에서 질문당 약 1분이라 기본은 끔 (리포트 5.4)
- 답변 아래에 근거 공시(공시명·제출일·위치·DART 링크·발췌)를 보인다.
- 벡터 DB·API 키가 없으면 직접 질문은 막고 준비 방법을 안내한다. 예시 답변과 공시 목록은 그대로 보인다.
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

saved = loader.load_saved_answers()
saved_answers = saved["answers"] if saved else {}
saved_note = (f"저장된 답변 · {saved['created_at'][:10]} 생성" + (" · 정밀 검색" if saved.get("reranker") else "")
              if saved else None)
problems = loader.readiness(manifest)
for p in problems:
    st.warning(p + (" 예시 질문은 저장된 답변으로 볼 수 있습니다." if saved_answers else ""))

# ── 질문 ──
state = st.session_state
state.setdefault("qa_history", [])
state.setdefault("qa_question", "")


def push(result, texts, note=None):
    state["qa_history"] = [(result, texts, note)] + state["qa_history"][: HISTORY_LIMIT - 1]


def pick_example():
    q = state.get("qa_example")
    if q:
        state["qa_question"] = q
        if q in saved_answers:  # 저장된 답변은 누르자마자 보인다 (API 호출 없음)
            push(*saved_answers[q], saved_note)


# 처음 보는 사람이 바로 누를 수 있게 기본은 펼쳐 두고, 필요 없으면 접는다
with st.expander(f"예시 질문 ({len(qa_chain.SAMPLE_QUESTIONS)}개)", expanded=True):
    st.caption("예시 질문은 미리 만들어 둔 답변을 바로 보여 주고, 직접 입력한 질문은 실시간으로 답합니다.")
    st.pills("예시 질문", [q for q, _ in qa_chain.SAMPLE_QUESTIONS], key="qa_example", on_change=pick_example,
             label_visibility="collapsed")

with st.form("qa_form", border=False):
    col_q, col_b = st.columns([4, 1], vertical_alignment="bottom")
    question = col_q.text_input("질문", key="qa_question", placeholder="예: SK하이닉스 청주 M15X 신규 시설투자 금액은?",
                                label_visibility="collapsed")
    submitted = col_b.form_submit_button("질문하기", type="primary", use_container_width=True, disabled=bool(problems) and not saved_answers)

use_rerank = loader.reranker_available() and st.toggle(
    "정밀 검색 (재정렬 모델, 직접 입력한 질문에만 적용, 질문당 약 1분)", value=False, key="qa_rerank",
    help="후보 40개를 질문과 함께 다시 채점합니다. 평가 질문에서 검색 적중이 16/19 → 19/19로 올랐지만 CPU에서 느립니다.")

if submitted and question.strip() in saved_answers:
    push(*saved_answers[question.strip()], saved_note)
elif submitted and question.strip() and problems:
    st.info("지금은 실시간 질문을 쓸 수 없습니다. 위의 예시 질문을 눌러 저장된 답변을 확인해 주세요.")
elif submitted and question.strip():
    try:
        with st.spinner("공시에서 근거를 찾는 중…" + (" (정밀 검색: 약 1분)" if use_rerank else "")):
            store = loader.get_store()
            reranker = loader.get_reranker() if use_rerank else None
            result = qa_chain.ask(question.strip(), store, loader.get_llm(), reranker=reranker)
            texts = loader.chunk_texts(store, [s["chunk_id"] for s in result.sources])
        push(result, texts)
    except Exception as e:  # API 오류 등: 키·내용은 보이지 않고 종류만 알린다
        st.error(f"답변을 만들지 못했습니다 ({type(e).__name__}). 네트워크와 API 키를 확인해 주세요.")
elif submitted:
    st.info("질문을 입력해 주세요.")

if state["qa_history"]:
    qa_view.render_result(*state["qa_history"][0])
    if len(state["qa_history"]) > 1:
        with st.expander(f"이전 질문 {len(state['qa_history']) - 1}개"):
            for item in state["qa_history"][1:]:
                qa_view.render_result(*item)

# ── RAG 대상 공시 ──
qa_view.render_html('<div class="qa-section">검색 대상 공시</div>')
disclosures = loader.load_rag_disclosures()
# 목록이 길어(101건) 기본은 접어 두고, 눌러서 열고 닫는다
with st.expander(f"공시 목록 보기 ({len(disclosures)}건)", expanded=False):
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
