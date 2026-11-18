"""
청크를 임베딩해 벡터 DB(data/vectordb)에 저장한다. 미리 생성해 두고 대시보드·qa_chain은 조회만 한다.

- 입력: chunking이 만든 data/processed/disclosure_chunks.jsonl (RAG 대상 101건, 청크 2,191개. 리포트 5.1)
- 임베딩: OpenAI text-embedding-3-small (1536차원). 한국어 검색에 쓸 만하고 가장 싸다.
  전체 약 167만 자 ≈ 수백만 토큰 이하라 비용은 수 센트 수준이다 (실행 시 토큰 수를 출력한다)
- 저장: Chroma (langchain-chroma), 컬렉션 COLLECTION, 거리 cosine. 문서 id = chunk_id라 다시 실행해도 같은 id다.
  다시 실행하면 컬렉션을 지우고 처음부터 다시 만든다 (청크 기준이 바뀌면 남은 옛 청크가 섞이지 않도록).
- 메타데이터: 청크의 text를 뺀 나머지 전부 (공시명·제출일·링크·섹션·첨부 파일명·쪽 번호 등, chunking.to_documents)
- manifest.json: 모델·청크 수·청크 파일 지문·만든 시각. 공유받은 벡터 DB가 지금 청크와 같은 것인지 맞춰 볼 때 쓴다.

공유: 임베딩은 비용이 들고 API 결과가 조금씩 달라질 수 있어, 한도윤이 만든 data/vectordb를 zip으로 공유 드라이브에 올린다.
김한승은 풀기만 하면 된다 (OpenAI 키는 질문 임베딩에만 필요). docs/conventions.md §5

실행: python -m src.rag.build_index             (chunking 다음. 임베딩 API 호출)
      python -m src.rag.build_index --dry-run   (청크 수·토큰 수만 확인, API 호출 없음)
      python -m src.rag.build_index --query "SK하이닉스 HBM 매출 증가율"   (만든 DB로 검색만 해 본다)

담당: 한도윤 (공시 분석)
일정: Day 5
"""

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from src.common import config
from src.rag import chunking

EMBEDDING_MODEL = "text-embedding-3-small"
COLLECTION = "disclosure_chunks"
BATCH_SIZE = 100  # 한 번에 넣는 청크 수 (청크 ≤ 1,000자라 OpenAI 요청당 토큰 한도보다 한참 작다)
MANIFEST_PATH = config.VECTORDB_DIR / "manifest.json"


def chunks_fingerprint(chunks: list[dict]) -> str:
    """청크 id와 본문으로 만든 지문 (앞 12자리). 같은 청크 파일이면 같은 값."""
    h = hashlib.sha256()
    for c in sorted(chunks, key=lambda c: c["chunk_id"]):
        h.update(c["chunk_id"].encode("utf-8"))
        h.update(c["text"].encode("utf-8"))
    return h.hexdigest()[:12]


def count_tokens(chunks: list[dict]) -> int:
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")  # text-embedding-3-* 토크나이저
    return sum(len(enc.encode(c["text"])) for c in chunks)


def make_embeddings():
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(model=EMBEDDING_MODEL, api_key=config.require_env("OPENAI_API_KEY"), chunk_size=BATCH_SIZE)


def open_store(embeddings=None, persist_dir: Path | None = None):
    """벡터 DB를 연다 (qa_chain·대시보드에서도 이 함수로 연다)."""
    from langchain_chroma import Chroma

    return Chroma(
        collection_name=COLLECTION,
        embedding_function=embeddings if embeddings is not None else make_embeddings(),
        persist_directory=str(persist_dir or config.VECTORDB_DIR),
        collection_metadata={"hnsw:space": "cosine"},
    )


def build(chunks: list[dict], embeddings=None, persist_dir: Path | None = None, batch_size: int = BATCH_SIZE):
    """컬렉션을 비우고 청크를 모두 넣는다. Returns Chroma."""
    persist_dir = persist_dir or config.VECTORDB_DIR
    persist_dir.mkdir(parents=True, exist_ok=True)
    store = open_store(embeddings, persist_dir)
    store.delete_collection()  # 다시 실행하면 처음부터 (옛 청크가 남지 않게)
    store = open_store(embeddings, persist_dir)
    docs = chunking.to_documents(chunks)
    for i in range(0, len(docs), batch_size):
        batch = docs[i:i + batch_size]
        store.add_documents(batch, ids=[d.id for d in batch])
        print(f"  {min(i + batch_size, len(docs)):,}/{len(docs):,}")
    return store


def write_manifest(chunks: list[dict], n_tokens: int, path: Path | None = None) -> dict:
    manifest = {
        "embedding_model": EMBEDDING_MODEL,
        "collection": COLLECTION,
        "n_chunks": len(chunks),
        "n_disclosures": len({c["rcept_no"] for c in chunks}),
        "n_attachment_chunks": sum(c.get("section") == chunking.ATTACHMENT_SECTION for c in chunks),
        "n_tokens": n_tokens,
        "chunks_fingerprint": chunks_fingerprint(chunks),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    path = path or MANIFEST_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def search(query: str, k: int = 5, store=None) -> list[tuple]:
    """질문과 가까운 청크 k개 (Document, 거리). 거리는 cosine 거리라 작을수록 가깝다."""
    store = store or open_store()
    return store.similarity_search_with_score(query, k=k)


def print_results(query: str, results: list[tuple]) -> None:
    print(f"\n질문: {query}")
    for doc, score in results:
        m = doc.metadata
        where = f"{m['file_name']} p.{m['page']}" if m.get("page") else m["section"]
        print(f"  {score:.3f} | {m['corp_name']} | {m['report_nm']} | {m['rcept_dt']} | {where}")


def main(dry_run: bool = False) -> dict | None:
    chunks = chunking.load_chunks()
    n_tokens = count_tokens(chunks)
    print(f"청크 {len(chunks):,}개 (공시 {len({c['rcept_no'] for c in chunks})}건), 토큰 {n_tokens:,}개, "
          f"지문 {chunks_fingerprint(chunks)}, 모델 {EMBEDDING_MODEL}")
    if dry_run:
        print("미리보기 (API 호출 없음)")
        return None
    store = build(chunks)
    stored = store._collection.count()
    if stored != len(chunks):
        raise SystemExit(f"저장된 청크 수가 다릅니다: {stored} != {len(chunks)}")
    manifest = write_manifest(chunks, n_tokens)
    print(f"저장: {config.VECTORDB_DIR} (컬렉션 {COLLECTION}, {stored:,}개)")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="공시 청크 임베딩 → Chroma 벡터 DB")
    parser.add_argument("--dry-run", action="store_true", help="청크·토큰 수만 확인 (API 호출 없음)")
    parser.add_argument("--query", help="만든 벡터 DB로 검색만 해 본다")
    parser.add_argument("-k", type=int, default=5)
    args = parser.parse_args()
    if args.query:
        print_results(args.query, search(args.query, args.k))
    else:
        main(dry_run=args.dry_run)
