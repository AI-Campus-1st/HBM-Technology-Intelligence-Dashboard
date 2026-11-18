"""
벡터 DB 생성(src/rag/build_index.py) 테스트. 가짜 임베딩으로 확인한다 (OpenAI API 호출 없음).

담당: 한도윤 (공시 분석)
일정: Day 5
"""

import json

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from src.rag import build_index


def make_chunk(chunk_id, text, **meta):
    base = {"rcept_no": chunk_id.split("_")[0], "corp_code": "00164779", "corp_name": "SK하이닉스",
            "report_nm": "연결재무제표기준영업(잠정)실적(공정공시)", "rcept_dt": "2024-10-24", "pblntf_ty": "I",
            "url": "https://dart.fss.or.kr/x", "section": "본문", "section_type": "실적", "file_name": "", "page": 0,
            "chunk_index": 0, "n_chars": len(text), "has_hbm": "HBM" in text}
    return {**base, **meta, "chunk_id": chunk_id, "text": text}


CHUNKS = [
    make_chunk("r1_00_000", "[SK하이닉스 | 실적 | 본문]\n매출액 17,573"),
    make_chunk("r1_a1p05_000", "[SK하이닉스 | 실적 | 첨부 KOR.pdf p.5]\nHBM 매출 QoQ +70% 이상",
               section="첨부", section_type="IR자료", file_name="KOR.pdf", page=5),
    make_chunk("r2_00_000", "[삼성전자 | 신규시설투자 | 본문]\n평택 증설", corp_name="삼성전자"),
]


@pytest.fixture
def emb():
    return DeterministicFakeEmbedding(size=16)


def test_fingerprint_is_order_independent_and_text_sensitive():
    fp = build_index.chunks_fingerprint(CHUNKS)
    assert fp == build_index.chunks_fingerprint(list(reversed(CHUNKS))) and len(fp) == 12
    changed = [{**CHUNKS[0], "text": "다른 본문"}] + CHUNKS[1:]
    assert build_index.chunks_fingerprint(changed) != fp


def test_build_stores_all_chunks_with_metadata_and_rebuilds_cleanly(tmp_path, emb):
    store = build_index.build(CHUNKS, embeddings=emb, persist_dir=tmp_path, batch_size=2)
    got = store.get(ids=["r1_a1p05_000"])
    assert store._collection.count() == 3
    assert got["documents"] == [CHUNKS[1]["text"]]
    meta = got["metadatas"][0]
    assert (meta["page"], meta["file_name"], meta["corp_name"]) == (5, "KOR.pdf", "SK하이닉스")
    assert "text" not in meta

    # 청크가 줄어든 채로 다시 만들면 옛 청크가 남지 않는다
    store = build_index.build(CHUNKS[:1], embeddings=emb, persist_dir=tmp_path)
    assert store._collection.count() == 1


def test_search_returns_exact_text_first_and_supports_filter(tmp_path, emb):
    store = build_index.build(CHUNKS, embeddings=emb, persist_dir=tmp_path)
    doc, score = build_index.search(CHUNKS[2]["text"], k=1, store=store)[0]  # 같은 텍스트 = 같은 가짜 벡터
    assert doc.id == "r2_00_000" and score == pytest.approx(0, abs=1e-6)
    filtered = store.similarity_search(CHUNKS[2]["text"], k=3, filter={"corp_name": "SK하이닉스"})
    assert {d.metadata["corp_name"] for d in filtered} == {"SK하이닉스"}


def test_write_manifest(tmp_path):
    m = build_index.write_manifest(CHUNKS, n_tokens=42, path=tmp_path / "manifest.json")
    assert (m["n_chunks"], m["n_disclosures"], m["n_attachment_chunks"], m["n_tokens"]) == (3, 2, 1, 42)
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8")) == m


def test_count_tokens_counts_header_too():
    assert build_index.count_tokens(CHUNKS[:1]) > build_index.count_tokens([{**CHUNKS[0], "text": "매출액"}])
