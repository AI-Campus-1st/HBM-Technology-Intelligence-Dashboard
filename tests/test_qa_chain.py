"""
공시 질의응답(src/rag/qa_chain.py) 테스트. 가짜 임베딩과 가짜 LLM으로 확인한다 (OpenAI API 호출 없음).

담당: 한도윤 (공시 분석)
일정: Day 5
"""

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from src.rag import build_index, qa_chain
from tests.test_build_index import make_chunk

CHUNKS = [
    make_chunk("s1_a1p05_000", "[SK하이닉스 | 실적 | 첨부 KOR.pdf p.5]\nHBM 매출 QoQ +70% 이상",
               section="첨부", section_type="IR자료", file_name="KOR.pdf", page=5),
    make_chunk("s2_00_000", "[SK하이닉스 | 신규시설투자등 | 본문]\n청주 M15X 건설 5,296,200,000,000"),
    make_chunk("m1_a1p08_000", "[삼성전자 | 실적 | 첨부 S.pdf p.8]\n수출 통제 영향 등에 따른 HBM 판매 감소",
               corp_name="삼성전자", section="첨부", file_name="S.pdf", page=8),
    make_chunk("m3_00_000", "[삼성전자 | 사업보고서 | 연구개발]\nHBM 샘플 출하", corp_name="삼성전자"),
    make_chunk("m2_00_000", "[삼성전자 | 사업보고서 | 기타 참고사항]\nDRAM 시장점유율 42.2%", corp_name="삼성전자"),
]


class FakeLLM:
    """구조화 출력 LLM 흉내. 받은 메시지를 기록하고 정해 둔 Answer를 돌려준다."""

    def __init__(self, answer: qa_chain.Answer):
        self.answer, self.calls = answer, []

    def invoke(self, messages):
        self.calls.append(messages)
        return self.answer


class FixedStore:
    """정해 둔 (Document, 거리)를 돌려주는 벡터 DB 흉내. filter가 있으면 그 기업만."""

    def __init__(self, results):
        self.results, self.filters = results, []

    def similarity_search_with_score(self, query, k, filter=None):
        self.filters.append(filter)
        rows = [r for r in self.results if not filter or r[0].metadata["corp_name"] == filter["corp_name"]]
        return rows[:k]


@pytest.fixture
def docs():
    from src.rag import chunking

    return {d.id: d for d in chunking.to_documents(CHUNKS)}


@pytest.mark.parametrize("question, expected", [
    ("SK하이닉스 HBM 매출은?", ["SK하이닉스"]),
    ("하이닉스 청주 공장", ["SK하이닉스"]),
    ("삼성 HBM 판매", ["삼성전자"]),
    ("SK하이닉스와 삼성전자 비교", ["SK하이닉스", "삼성전자"]),
    ("HBM 시장 전망은?", []),
])
def test_detect_companies(question, expected):
    assert qa_chain.detect_companies(question) == expected
    assert qa_chain.detect_company(question) == (expected[0] if len(expected) == 1 else None)


def test_keyword_tokens_use_bigrams_and_skip_header():
    assert qa_chain.keyword_tokens("[삼성전자 | 본문]\nHBM 판매가 감소") == ["hbm", "판매", "매가", "감소"]


def test_rrf_lifts_keyword_match(docs):
    # 벡터 순서: m2(점유율), m1(판매 감소), m3(HBM만). 키워드가 가장 잘 맞는 m1이 맨 위로 온다
    texts = [docs[i].page_content for i in ("m2_00_000", "m1_a1p08_000", "m3_00_000")]
    scores = qa_chain.bm25_scores("HBM 판매 감소 이유", texts)
    assert scores[1] > scores[2] > scores[0] == 0
    assert qa_chain.rrf_order(scores) == [1, 0, 2]


def test_retrieve_filters_distance_and_reranks(docs):
    store = FixedStore([(docs["m2_00_000"], 0.40), (docs["s2_00_000"], 0.41), (docs["m1_a1p08_000"], 0.45),
                        (docs["m3_00_000"], 0.50), (docs["m2_00_000"], 0.90)])
    got = qa_chain.retrieve("HBM 판매 감소", store, k=2, company="삼성전자")
    assert [d.id for d, _ in got] == ["m1_a1p08_000", "m2_00_000"]  # 다른 기업·먼 청크(0.9) 제외, 키워드로 재정렬
    assert store.filters == [{"corp_name": "삼성전자"}]


def test_comparison_question_retrieves_each_company(docs):
    store = FixedStore([(docs[i], 0.4) for i in ("s1_a1p05_000", "s2_00_000", "m1_a1p08_000", "m2_00_000")])
    got = qa_chain.retrieve_for_question("SK하이닉스와 삼성전자 HBM 비교", store, k=4)
    assert [d.metadata["corp_name"] for d, _ in got] == ["SK하이닉스", "삼성전자", "SK하이닉스", "삼성전자"]
    assert store.filters == [{"corp_name": "SK하이닉스"}, {"corp_name": "삼성전자"}]


def test_ask_refuses_without_llm_when_nothing_is_close(docs):
    llm = FakeLLM(qa_chain.Answer(answerable=True, answer="x", used_sources=[1]))
    r = qa_chain.ask("오늘 날씨는?", FixedStore([(docs["m2_00_000"], 0.8)]), llm)
    assert (r.answerable, r.answer, r.retrieved) == (False, qa_chain.REFUSAL, 0)
    assert "거리" in r.refusal_reason and llm.calls == []  # LLM을 부르지 않는다


def test_ask_refuses_when_llm_says_unanswerable(docs):
    llm = FakeLLM(qa_chain.Answer(answerable=False, answer="", used_sources=[]))
    r = qa_chain.ask("마이크론 점유율은?", FixedStore([(docs["m2_00_000"], 0.5)]), llm)
    assert (r.answerable, r.answer, r.sources) == (False, qa_chain.REFUSAL, [])
    assert "LLM" in r.refusal_reason


def test_ask_answers_with_used_sources_only(docs):
    store = FixedStore([(docs["s1_a1p05_000"], 0.41), (docs["s2_00_000"], 0.55)])
    llm = FakeLLM(qa_chain.Answer(answerable=True, answer="HBM 매출이 70% 이상 늘었다.[1]", used_sources=[1, 1, 9]))
    r = qa_chain.ask("SK하이닉스 HBM 매출 증가율은?", store, llm)
    assert r.answerable and r.company_filter == "SK하이닉스" and r.retrieved == 2
    assert [s["chunk_id"] for s in r.sources] == ["s1_a1p05_000"]  # 중복·범위 밖 번호는 버린다
    src = r.sources[0]
    assert (src["location"], src["distance"], src["url"]) == ("첨부 KOR.pdf p.5", 0.41, "https://dart.fss.or.kr/x")
    human = llm.calls[0][1][1]
    assert human.startswith("근거:\n[1] [SK하이닉스 | 실적 | 첨부 KOR.pdf p.5]") and "질문: SK하이닉스" in human


def test_ask_with_real_chroma_and_fake_embeddings(tmp_path):
    emb = DeterministicFakeEmbedding(size=16)
    store = build_index.build(CHUNKS, embeddings=emb, persist_dir=tmp_path)
    llm = FakeLLM(qa_chain.Answer(answerable=True, answer="답 [1]", used_sources=[1]))
    r = qa_chain.ask(CHUNKS[2]["text"], store, llm, max_distance=2.0)  # 가짜 임베딩이라 거리 상한을 넓힌다
    assert r.answerable and r.company_filter == "삼성전자"
    assert {s["corp_name"] for s in r.sources} == {"삼성전자"}


def test_format_result_shows_refusal_and_sources():
    r = qa_chain.QAResult("q", qa_chain.REFUSAL, False, "관련 공시 없음", None, 0)
    assert "거절 이유: 관련 공시 없음" in qa_chain.format_result(r)
    src = {"n": 1, "corp_name": "SK하이닉스", "report_nm": "실적", "rcept_dt": "2024-10-24",
           "location": "첨부 KOR.pdf p.5", "distance": 0.41, "url": "u"}
    r = qa_chain.QAResult("q", "답 [1]", True, None, "SK하이닉스", 1, [src])
    assert "[1] SK하이닉스 | 실적 | 2024-10-24 | 첨부 KOR.pdf p.5" in qa_chain.format_result(r)


def test_save_and_load_samples_json(tmp_path):
    src = {"n": 1, "corp_name": "SK하이닉스", "report_nm": "실적", "rcept_dt": "2024-10-24", "url": "u",
           "location": "첨부 KOR.pdf p.5", "distance": 0.41, "chunk_id": "s1_a1p05_000"}
    results = [qa_chain.QAResult("q1", "70% [1]", True, None, "SK하이닉스", 6, [src]),
               qa_chain.QAResult("q2", qa_chain.REFUSAL, False, "관련 공시 없음 (검색 거리 기준)", None, 0)]
    path = tmp_path / "s.json"
    qa_chain.save_samples_json(results, {"s1_a1p05_000": "본문", "other": "x"}, path)
    data = qa_chain.load_samples_json(path)
    assert data["results"] == results and data["texts"] == {"s1_a1p05_000": "본문"}  # 출처 청크만 저장
    assert data["model"] == qa_chain.config.LLM_MODEL and qa_chain.load_samples_json(tmp_path / "none.json") is None


def test_source_texts_uses_store_get_when_available():
    class Store:
        def get(self, ids):
            return {"ids": ids, "documents": [i.upper() for i in ids]}

    r = qa_chain.QAResult("q", "a", True, sources=[{"chunk_id": "a"}, {"chunk_id": "b"}])
    assert qa_chain.source_texts(Store(), [r, r]) == {"a": "A", "b": "B"}
    assert qa_chain.source_texts(object(), [r]) == {}


def test_keyword_tokens_keep_number_with_unit():
    toks = qa_chain.keyword_tokens("[머리말]\nHBM3E 16단을 2025년 3분기 12H")
    assert {"16단", "16단을", "2025년", "3분기", "12h"} <= set(toks)
    assert "3e" not in toks  # 'HBM3E' 안의 숫자는 숫자+단위로 보지 않는다


class FakeReranker:
    """정해 둔 단어가 들어 있는 청크에 높은 점수를 주는 재정렬 흉내."""

    def __init__(self, word):
        self.word, self.calls = word, []

    def scores(self, query, texts):
        self.calls.append(len(texts))
        return [1.0 if self.word in t else 0.0 for t in texts]


def test_retrieve_with_reranker_reorders_whole_pool(docs):
    store = FixedStore([(docs["m2_00_000"], 0.40), (docs["m1_a1p08_000"], 0.45), (docs["m3_00_000"], 0.50)])
    rr = FakeReranker("샘플")
    got = qa_chain.retrieve("HBM 판매 감소", store, k=2, company="삼성전자", reranker=rr)
    assert [d.id for d, _ in got] == ["m3_00_000", "m1_a1p08_000"]  # 재정렬 1위, 나머지는 RRF 순서
    assert rr.calls == [3]  # 후보 전체를 채점한다


def test_ask_passes_reranker(docs):
    store = FixedStore([(docs["m2_00_000"], 0.40), (docs["m3_00_000"], 0.50)])
    llm = FakeLLM(qa_chain.Answer(answerable=True, answer="샘플 [1]", used_sources=[1]))
    r = qa_chain.ask("삼성전자 HBM", store, llm, reranker=FakeReranker("샘플"))
    assert r.sources[0]["chunk_id"] == "m3_00_000"


def test_load_reranker_returns_none_without_package(monkeypatch):
    import builtins

    real = builtins.__import__

    def fake(name, *a, **kw):
        if name.startswith("sentence_transformers"):
            raise ImportError
        return real(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake)
    assert qa_chain.load_reranker() is None


def test_retrieve_ranked_matches_retrieve_for_question_at_any_k(docs):
    # 한 번 정렬한 결과를 k마다 잘라 써도 k마다 따로 검색한 결과와 같다 (평가의 재정렬 1회 근거)
    store = FixedStore([(docs[i], 0.4) for i in ("s1_a1p05_000", "s2_00_000", "m1_a1p08_000",
                                                  "m3_00_000", "m2_00_000")])
    for q in ("SK하이닉스와 삼성전자 HBM 비교", "삼성전자 HBM 판매", "HBM 전망"):
        groups = qa_chain.retrieve_ranked(q, store, qa_chain.POOL, reranker=FakeReranker("샘플"))
        for k in (1, 2, 3, 6, qa_chain.POOL):
            want = qa_chain.retrieve_for_question(q, store, k, reranker=FakeReranker("샘플"))
            assert [d.id for d, _ in qa_chain.merge_ranked(groups, k)] == [d.id for d, _ in want]


def test_ask_uses_given_results_without_searching(docs):
    store = FixedStore([])
    llm = FakeLLM(qa_chain.Answer(answerable=True, answer="샘플 [1]", used_sources=[1]))
    r = qa_chain.ask("삼성전자 HBM", store, llm, results=[(docs["m3_00_000"], 0.5)])
    assert r.sources[0]["chunk_id"] == "m3_00_000" and store.filters == []
