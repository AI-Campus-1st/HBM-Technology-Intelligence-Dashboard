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

평가 질문 v2 (qa_eval_v2, 12문항: 답변 10 + 거절 2, 2026-11-18): 검색 개선(토큰·재정렬) 전에 따로 만든 확인용 질문.
v1의 틀린 질문만 보고 고치면 v1에 맞춘 개선이 되므로, 개선 효과는 v1과 v2 양쪽에서 본다 (리포트 5.4).

실행: python -m src.rag.evaluate                       (v1, qa_chain 다음. 질문마다 임베딩 호출과 LLM 호출 1회)
      python -m src.rag.evaluate --version qa_eval_v2
      python -m src.rag.evaluate --retrieval-only        (LLM 없이 검색 지표만, 저장 안 함. 개선 실험용)
      python -m src.rag.evaluate --rerank                (교차 인코더 재정렬 사용, requirements/rerank.txt 필요)
저장: outputs/reports/<버전>.csv (질문별), outputs/reports/<버전>_summary.csv (요약)

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


def paths(version: str = EVAL_VERSION) -> tuple[Path, Path, Path]:
    """(평가 질문, 질문별 결과, 요약) 경로."""
    reports = config.OUTPUTS_DIR / "reports"
    return config.LABELS_DIR / f"{version}.csv", reports / f"{version}.csv", reports / f"{version}_summary.csv"


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


def retrieval_one(row, store, reranker=None, ranked_groups=None) -> dict:
    """검색 지표만 (LLM 없음). rank_pool: 후보 전체(POOL개)를 재정렬한 순서에서 정답 첫 순위.
    ranked_groups(qa_chain.retrieve_ranked 결과)를 넘기면 검색·재정렬을 다시 하지 않는다."""
    groups = parse_gold(row.gold_groups)
    if ranked_groups is None:
        ranked_groups = qa_chain.retrieve_ranked(row.question, store, qa_chain.POOL, reranker=reranker)
    ranked = qa_chain.merge_ranked(ranked_groups, qa_chain.POOL)
    hybrid = qa_chain.merge_ranked(ranked_groups, qa_chain.K)  # ask()가 LLM에 넘기는 근거와 같다
    vector = vector_only(row.question, store)
    h_ids = [d.metadata["rcept_no"] for d, _ in hybrid]
    v_ids = [d.metadata["rcept_no"] for d, _ in vector]
    top = vector[0][1] if vector else None
    return {
        "hit_hybrid": int(groups_hit(h_ids, groups)) if groups else None,
        "hit_vector": int(groups_hit(v_ids, groups)) if groups else None,
        "rank_hybrid": first_rank(h_ids, groups), "rank_vector": first_rank(v_ids, groups),
        "rank_pool": first_rank([d.metadata["rcept_no"] for d, _ in ranked], groups),
        "d_chunks": sum(d.metadata["pblntf_ty"] == "D" for d, _ in hybrid), "retrieved": len(hybrid),
        "top_distance": None if top is None else round(float(top), 3),
    }


def evaluate_one(row, store, llm, reranker=None) -> dict:
    groups = parse_gold(row.gold_groups)
    # 검색·재정렬은 질문마다 한 번만 하고, 검색 지표와 답변에 같이 쓴다 (재정렬은 CPU에서 질문당 약 40초)
    ranked_groups = qa_chain.retrieve_ranked(row.question, store, qa_chain.POOL, reranker=reranker)
    ret = retrieval_one(row, store, reranker, ranked_groups)

    result = qa_chain.ask(row.question, store, llm, reranker=reranker,
                          results=qa_chain.merge_ranked(ranked_groups, qa_chain.K))
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
        **ret,
        "pattern_ok": int(pattern_ok) if row.expected == "답변" else None,
        "cited_ok": None if cited_ok is None else int(cited_ok),
        "company_filter": result.company_filter or "", "refusal_reason": result.refusal_reason or "",
        "answer": result.answer, "cited": " ".join(cited),
        "sources": " ; ".join(f"[{s['n']}] {s['corp_name']} {s['report_nm']} {s['rcept_dt']} {s['location']}"
                              for s in result.sources),
        "model": config.LLM_MODEL, "reranker": "" if reranker is None else qa_chain.RERANK_MODEL,
    }


def mrr(values: pd.Series) -> float:
    return round(values.map(lambda r: 0 if pd.isna(r) else 1 / r).mean(), 3)


def summarize_retrieval(df: pd.DataFrame) -> dict:
    """검색 지표 요약: hit@K, MRR, 상위 K개 밖에 있는 정답의 후보 순위 ('-'는 후보에도 없음)."""
    ans = df[df["expected"] == "답변"]
    missed = " ".join(f"{q}:{'-' if pd.isna(r) else int(r)}" for q, r in zip(ans["qid"], ans["rank_pool"])
                      if pd.isna(r) or r > qa_chain.K)
    return {"hit@K": f"{int(ans['hit_hybrid'].sum())}/{len(ans)}", "MRR": mrr(ans["rank_hybrid"]),
            "K 밖 정답 순위": missed or "없음"}


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    ans, ref = df[df["expected"] == "답변"], df[df["expected"] == "거절"]

    rows = [
        ("답변 질문 수", len(ans)), ("거절 질문 수", len(ref)),
        ("검색 적중 hit@6 (하이브리드)", f"{int(ans['hit_hybrid'].sum())}/{len(ans)}"),
        ("검색 적중 hit@6 (벡터만)", f"{int(ans['hit_vector'].sum())}/{len(ans)}"),
        ("MRR (하이브리드)", mrr(ans["rank_hybrid"])), ("MRR (벡터만)", mrr(ans["rank_vector"])),
        ("답변 정확", f"{int(ans['correct'].sum())}/{len(ans)}"),
        ("거절 정확", f"{int(ref['correct'].sum())}/{len(ref)}"),
        ("전체 정확", f"{int(df['correct'].sum())}/{len(df)}"),
        ("잘못 거절", int((ans["error"] == "잘못 거절").sum())),
        ("잘못 답변", int((ref["error"] == "잘못 답변").sum())),
        ("검색 청크 중 위임장(D) 비율", f"{df['d_chunks'].sum()}/{df['retrieved'].sum()}"),
        ("최근접 거리 범위 (답변 질문)", f"{ans['top_distance'].min()}~{ans['top_distance'].max()}"),
        ("최근접 거리 범위 (거절 질문)", f"{ref['top_distance'].min()}~{ref['top_distance'].max()}"),
        ("거리 기준 MAX_DISTANCE", qa_chain.MAX_DISTANCE), ("LLM", config.LLM_MODEL),
        ("재정렬 모델", (df["reranker"].iloc[0] or "없음") if "reranker" in df and len(df) else "없음"),
    ]
    return pd.DataFrame(rows, columns=["지표", "값"])


def load_eval(path: Path | None = None) -> pd.DataFrame:
    return pd.read_csv(path or EVAL_PATH, dtype=str, keep_default_na=False)


def run_retrieval(version: str = EVAL_VERSION, store=None, reranker=None) -> pd.DataFrame:
    """LLM 없이 검색 지표만 (저장하지 않는다). 개선 실험을 빠르게 비교할 때 쓴다."""
    questions = load_eval(paths(version)[0])
    store = store if store is not None else build_index.open_store()
    df = pd.DataFrame([{"qid": row.qid, "expected": row.expected, **retrieval_one(row, store, reranker)}
                       for row in questions.itertuples(index=False)])
    print(version, summarize_retrieval(df))
    return df


def main(store=None, llm=None, version: str = EVAL_VERSION, reranker=None) -> pd.DataFrame:
    eval_path, result_path, summary_path = paths(version)
    if reranker is not None:  # 재정렬 결과는 따로 저장해 기본 결과와 나란히 비교한다
        result_path, summary_path = paths(f"{version}_rerank")[1:]
    questions = load_eval(eval_path)
    store = store if store is not None else build_index.open_store()
    llm = llm if llm is not None else qa_chain.make_llm()
    rows = []
    for row in questions.itertuples(index=False):
        r = evaluate_one(row, store, llm, reranker)
        mark = "O" if r["correct"] else "X"
        print(f"{mark} {r['qid']} [{r['category']}] 기대 {r['expected']} → {r['result']}"
              f" | 검색 하이브리드 {r['hit_hybrid']} 벡터 {r['hit_vector']} | {r['error']}")
        rows.append(r)
    df = pd.DataFrame(rows)
    summary = summarize(df)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(result_path, index=False, encoding="utf-8-sig")
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    print(summary.to_string(index=False))
    print(f"저장: {result_path}, {summary_path}")
    return df


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="공시 Q&A 평가")
    parser.add_argument("--version", default=EVAL_VERSION, help="평가 질문 파일 이름 (qa_eval_v1, qa_eval_v2)")
    parser.add_argument("--retrieval-only", action="store_true", help="LLM 없이 검색 지표만 (저장 안 함)")
    parser.add_argument("--rerank", action="store_true", help="교차 인코더 재정렬 사용")
    args = parser.parse_args()
    rr = qa_chain.load_reranker() if args.rerank else None
    if args.rerank and rr is None:
        parser.error("재정렬 모델을 불러오지 못했습니다: pip install -r requirements/rerank.txt")
    if args.retrieval_only:
        run_retrieval(args.version, reranker=rr)
    else:
        main(version=args.version, reranker=rr)
