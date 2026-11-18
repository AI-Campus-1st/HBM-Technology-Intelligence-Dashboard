"""
공시 Q&A(검색·답변·거절) 평가. 사람이 정한 평가 질문과 정답 근거(data/labels/qa_eval_v1.csv)로 잰다.

평가 질문 (qa_eval_v1, 24문항): 답변 19 + 거절 5
- 답변 질문은 첨부 IR 자료·본문 수치·정기보고서·풍문/조회공시·위임장(D)·비교·기업 없는 질문을 섞었다.
- gold_groups: 정답 근거 공시(rcept_no). ';'는 "이 중 하나", '|'는 "그룹마다 하나씩 모두"(비교 질문: 두 회사 근거 모두)
- answer_pattern: 답변에 들어 있어야 할 핵심 사실(정규식). 예: SK '24.3Q HBM 매출 증가율 → '70'

지표:
- 검색 적중(hit@K): 검색된 K개 청크에 정답 근거가 있는가 (그룹마다). 하이브리드(qa_chain.retrieve_for_question)와
  벡터만(같은 기업 필터, 재정렬 없음)을 함께 재서 재정렬 효과를 본다. 첫 정답 순위로 MRR도 낸다.
- 답변 정확: 답변 질문에 답했고(answerable), 핵심 사실(answer_pattern)이 있고, 붙인 출처에 정답 근거가 있다.
- 거절 정확: 거절 질문을 거절했다. 답변 질문을 거절하면 '잘못 거절', 거절 질문에 답하면 '잘못 답변'.
- 위임장(D) 비중: 검색된 청크 중 D 청크 비율 (청크의 20%가 D라 검색이 쏠리는지 확인, 리포트 5.1)
- 최근접 거리: 기업 필터를 건 벡터 검색 1위의 cosine 거리. 거리 기준(qa_chain.MAX_DISTANCE)이 맞는지 본다.

실행: python -m src.rag.evaluate   (qa_chain 다음. 질문마다 임베딩 호출과 LLM 호출 1회)
저장: outputs/reports/qa_eval_v1.csv (질문별), outputs/reports/qa_eval_v1_summary.csv (요약)

담당: 한도윤 (공시 분석)
일정: Day 5
"""

import re
from pathlib import Path

import pandas as pd

from src.common import config
from src.rag import build_index, qa_chain

EVAL_VERSION = "qa_eval_v1"
EVAL_PATH = config.LABELS_DIR / f"{EVAL_VERSION}.csv"
RESULT_PATH = config.OUTPUTS_DIR / "reports" / f"{EVAL_VERSION}.csv"
SUMMARY_PATH = config.OUTPUTS_DIR / "reports" / f"{EVAL_VERSION}_summary.csv"


def parse_gold(gold: str) -> list[set[str]]:
    """'a;b|c' → [{'a','b'}, {'c'}]. 빈 값이면 빈 목록(거절 질문)."""
    if not isinstance(gold, str) or not gold.strip():
        return []
    return [set(g.split(";")) for g in gold.split("|")]


def groups_hit(rcept_nos: list[str], groups: list[set[str]]) -> bool:
    """그룹마다 정답 근거가 하나 이상 있으면 True. 그룹이 없으면 False."""
    return bool(groups) and all(any(r in g for r in rcept_nos) for g in groups)


def first_rank(rcept_nos: list[str], groups: list[set[str]]) -> int | None:
    """정답 근거가 처음 나온 순위(1부터). 없으면 None."""
    gold = set().union(*groups) if groups else set()
    return next((i for i, r in enumerate(rcept_nos, 1) if r in gold), None)


def vector_only(question: str, store, k: int = qa_chain.K) -> list[tuple]:
    """비교용: 기업 필터만 건 벡터 검색 상위 k개 (재정렬·기업별 검색 없음)."""
    company = qa_chain.detect_company(question)
    return store.similarity_search_with_score(question, k=k, filter={"corp_name": company} if company else None)


def evaluate_one(row, store, llm) -> dict:
    groups = parse_gold(row.gold_groups)
    hybrid = qa_chain.retrieve_for_question(row.question, store)
    vector = vector_only(row.question, store)
    h_ids = [d.metadata["rcept_no"] for d, _ in hybrid]
    v_ids = [d.metadata["rcept_no"] for d, _ in vector]
    top = vector[0][1] if vector else None

    result = qa_chain.ask(row.question, store, llm)
    cited = [s["chunk_id"].split("_")[0] for s in result.sources]
    pattern_ok = bool(row.answer_pattern) and bool(re.search(row.answer_pattern, result.answer))
    if row.expected == "답변":
        cited_ok = groups_hit(cited, groups)
        correct = result.answerable and pattern_ok and cited_ok
        error = "" if correct else ("잘못 거절" if not result.answerable else
                                    "핵심 사실 없음" if not pattern_ok else "출처에 정답 근거 없음")
    else:
        cited_ok = None
        correct = not result.answerable
        error = "" if correct else "잘못 답변"
    return {
        "qid": row.qid, "category": row.category, "question": row.question, "expected": row.expected,
        "result": "답변" if result.answerable else "거절", "correct": int(correct), "error": error,
        "hit_hybrid": int(groups_hit(h_ids, groups)) if groups else None,
        "hit_vector": int(groups_hit(v_ids, groups)) if groups else None,
        "rank_hybrid": first_rank(h_ids, groups), "rank_vector": first_rank(v_ids, groups),
        "pattern_ok": int(pattern_ok) if row.expected == "답변" else None,
        "cited_ok": None if cited_ok is None else int(cited_ok),
        "d_chunks": sum(d.metadata["pblntf_ty"] == "D" for d, _ in hybrid), "retrieved": len(hybrid),
        "top_distance": None if top is None else round(float(top), 3),
        "company_filter": result.company_filter or "", "refusal_reason": result.refusal_reason or "",
        "answer": result.answer,
        "sources": " ; ".join(f"[{s['n']}] {s['corp_name']} {s['report_nm']} {s['rcept_dt']} {s['location']}"
                              for s in result.sources),
        "model": config.LLM_MODEL,
    }


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    ans, ref = df[df["expected"] == "답변"], df[df["expected"] == "거절"]

    def mrr(col):
        return round(ans[col].map(lambda r: 0 if pd.isna(r) else 1 / r).mean(), 3)

    rows = [
        ("답변 질문 수", len(ans)), ("거절 질문 수", len(ref)),
        ("검색 적중 hit@6 (하이브리드)", f"{int(ans['hit_hybrid'].sum())}/{len(ans)}"),
        ("검색 적중 hit@6 (벡터만)", f"{int(ans['hit_vector'].sum())}/{len(ans)}"),
        ("MRR (하이브리드)", mrr("rank_hybrid")), ("MRR (벡터만)", mrr("rank_vector")),
        ("답변 정확", f"{int(ans['correct'].sum())}/{len(ans)}"),
        ("거절 정확", f"{int(ref['correct'].sum())}/{len(ref)}"),
        ("전체 정확", f"{int(df['correct'].sum())}/{len(df)}"),
        ("잘못 거절", int((ans["error"] == "잘못 거절").sum())),
        ("잘못 답변", int((ref["error"] == "잘못 답변").sum())),
        ("검색 청크 중 위임장(D) 비율", f"{df['d_chunks'].sum()}/{df['retrieved'].sum()}"),
        ("최근접 거리 범위 (답변 질문)", f"{ans['top_distance'].min()}~{ans['top_distance'].max()}"),
        ("최근접 거리 범위 (거절 질문)", f"{ref['top_distance'].min()}~{ref['top_distance'].max()}"),
        ("거리 기준 MAX_DISTANCE", qa_chain.MAX_DISTANCE), ("LLM", config.LLM_MODEL),
    ]
    return pd.DataFrame(rows, columns=["지표", "값"])


def load_eval(path: Path | None = None) -> pd.DataFrame:
    return pd.read_csv(path or EVAL_PATH, dtype=str, keep_default_na=False)


def main(store=None, llm=None) -> pd.DataFrame:
    questions = load_eval()
    store = store if store is not None else build_index.open_store()
    llm = llm if llm is not None else qa_chain.make_llm()
    rows = []
    for row in questions.itertuples(index=False):
        r = evaluate_one(row, store, llm)
        mark = "O" if r["correct"] else "X"
        print(f"{mark} {r['qid']} [{r['category']}] 기대 {r['expected']} → {r['result']}"
              f" | 검색 하이브리드 {r['hit_hybrid']} 벡터 {r['hit_vector']} | {r['error']}")
        rows.append(r)
    df = pd.DataFrame(rows)
    summary = summarize(df)
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(RESULT_PATH, index=False, encoding="utf-8-sig")
    summary.to_csv(SUMMARY_PATH, index=False, encoding="utf-8-sig")
    print(summary.to_string(index=False))
    print(f"저장: {RESULT_PATH}, {SUMMARY_PATH}")
    return df


if __name__ == "__main__":
    main()
