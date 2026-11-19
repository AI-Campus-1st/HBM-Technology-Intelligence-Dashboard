"""
공시 Q&A 평가(src/rag/evaluate.py) 테스트. 가짜 벡터 DB·가짜 LLM으로 확인한다 (API 호출 없음).

담당: 한도윤 (공시 분석)
일정: Day 5
"""

from types import SimpleNamespace

import pandas as pd

from src.rag import evaluate as ev
from src.rag import qa_chain
from tests.test_qa_chain import CHUNKS, FakeLLM, FixedStore


def docs():
    from src.rag import chunking

    return {d.id: d for d in chunking.to_documents(CHUNKS)}


def test_parse_gold_and_groups_hit():
    groups = ev.parse_gold("s1;s2|m1")
    assert groups == [{"s1", "s2"}, {"m1"}]
    assert ev.groups_hit(["s2", "m1"], groups)
    assert not ev.groups_hit(["s1", "s2"], groups)  # 두 번째 그룹(다른 회사)이 없다
    assert ev.parse_gold("") == [] and not ev.groups_hit(["s1"], [])


def test_first_rank():
    assert ev.first_rank(["x", "m1", "s1"], [{"s1"}, {"m1"}]) == 2
    assert ev.first_rank(["x"], [{"s1"}]) is None


def row(**kw):
    base = {"qid": "Q1", "category": "c", "question": "SK하이닉스 HBM 매출 증가율은?", "expected": "답변",
            "gold_groups": "s1", "answer_pattern": "70"}
    return SimpleNamespace(**{**base, **kw})


def test_evaluate_one_correct_answer():
    d = docs()
    store = FixedStore([(d["s1_a1p05_000"], 0.41), (d["s2_00_000"], 0.5)])
    llm = FakeLLM(qa_chain.Answer(answerable=True, answer="70% 이상 늘었다 [1]", used_sources=[1]))
    r = ev.evaluate_one(row(), store, llm)
    assert (r["correct"], r["error"], r["hit_hybrid"], r["hit_vector"], r["rank_hybrid"]) == (1, "", 1, 1, 1)
    assert (r["pattern_ok"], r["cited_ok"], r["top_distance"], r["d_chunks"]) == (1, 1, 0.41, 0)


def test_evaluate_one_error_types():
    d = docs()
    store = FixedStore([(d["s1_a1p05_000"], 0.41), (d["s2_00_000"], 0.5)])
    wrong_fact = FakeLLM(qa_chain.Answer(answerable=True, answer="50% 늘었다 [1]", used_sources=[1]))
    assert ev.evaluate_one(row(), store, wrong_fact)["error"] == "핵심 사실 없음"
    wrong_src = FakeLLM(qa_chain.Answer(answerable=True, answer="70% [2]", used_sources=[2]))
    assert ev.evaluate_one(row(), store, wrong_src)["error"] == "출처에 정답 근거 없음"
    refused = FakeLLM(qa_chain.Answer(answerable=False, answer="", used_sources=[]))
    assert ev.evaluate_one(row(), store, refused)["error"] == "잘못 거절"
    # 거절 질문에 답하면 '잘못 답변', 거절하면 정답
    r = ev.evaluate_one(row(expected="거절", gold_groups="", answer_pattern=""), store, wrong_fact)
    assert (r["correct"], r["error"], r["hit_hybrid"]) == (0, "잘못 답변", None)
    assert ev.evaluate_one(row(expected="거절", gold_groups="", answer_pattern=""), store, refused)["correct"] == 1


def test_summarize_counts():
    df = pd.DataFrame([
        {"expected": "답변", "correct": 1, "error": "", "hit_hybrid": 1, "hit_vector": 0, "rank_hybrid": 1,
         "rank_vector": None, "d_chunks": 1, "retrieved": 6, "top_distance": 0.4},
        {"expected": "답변", "correct": 0, "error": "잘못 거절", "hit_hybrid": 0, "hit_vector": 0, "rank_hybrid": None,
         "rank_vector": None, "d_chunks": 0, "retrieved": 6, "top_distance": 0.5},
        {"expected": "거절", "correct": 1, "error": "", "hit_hybrid": None, "hit_vector": None, "rank_hybrid": None,
         "rank_vector": None, "d_chunks": 0, "retrieved": 0, "top_distance": 0.76},
    ])
    s = dict(ev.summarize(df).values)
    assert s["검색 적중 hit@6 (하이브리드)"] == "1/2" and s["검색 적중 hit@6 (벡터만)"] == "0/2"
    assert s["MRR (하이브리드)"] == 0.5 and s["전체 정확"] == "2/3" and s["잘못 거절"] == 1
    assert s["검색 청크 중 위임장(D) 비율"] == "1/12"


def test_eval_set_is_well_formed():
    df = ev.load_eval()
    assert df["qid"].is_unique and set(df["expected"]) == {"답변", "거절"}
    ans = df[df["expected"] == "답변"]
    assert (ans["gold_groups"] != "").all() and (ans["answer_pattern"] != "").all()
    assert (df.loc[df["expected"] == "거절", "gold_groups"] == "").all()


def test_retrieval_one_reports_pool_rank():
    d = docs()
    store = FixedStore([(d["s2_00_000"], 0.4)] * 7 + [(d["s1_a1p05_000"], 0.5)])
    r = ev.retrieval_one(row(question="SK하이닉스 무엇?"), store)  # 키워드가 안 맞아 벡터 순서 그대로
    assert (r["hit_hybrid"], r["rank_hybrid"], r["rank_pool"]) == (0, None, 8)
    s = ev.summarize_retrieval(pd.DataFrame([{"qid": "Q1", "expected": "답변", **r}]))
    assert s["hit@K"] == "0/1" and s["K 밖 정답 순위"] == "Q1:8"


def test_paths_by_version():
    e, r, s = ev.paths("qa_eval_v2")
    assert e.name == "qa_eval_v2.csv" and r.name == "qa_eval_v2.csv" and s.name == "qa_eval_v2_summary.csv"


def test_evaluate_one_reranks_once_per_company():
    from tests.test_qa_chain import FakeReranker

    d = docs()
    store = FixedStore([(d["s1_a1p05_000"], 0.41), (d["s2_00_000"], 0.5), (d["m1_a1p08_000"], 0.45)])
    llm = FakeLLM(qa_chain.Answer(answerable=True, answer="70% [1]", used_sources=[1]))
    rr = FakeReranker("70")
    r = ev.evaluate_one(row(), store, llm, reranker=rr)
    assert len(rr.calls) == 1 and r["correct"] == 1  # 검색 지표와 답변이 재정렬 결과 하나를 같이 쓴다
    rr2 = FakeReranker("70")
    ev.evaluate_one(row(question="SK하이닉스와 삼성전자 HBM 비교"), store, llm, reranker=rr2)
    assert len(rr2.calls) == 2  # 기업별 한 번씩
