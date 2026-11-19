"""
공시 질의응답 체인. 벡터 DB(build_index)에서 근거 청크를 찾아 LLM이 답하고, 답변에 근거 공시
(공시명·제출일·링크·섹션 또는 첨부 쪽)를 붙인다. 근거가 없으면 답변을 거절한다.

흐름 (ask):
1. 기업 필터: 질문에 한 기업만 나오면(SK하이닉스/하이닉스, 삼성전자/삼성) 그 기업 청크만 검색한다.
   임베딩만으로는 두 회사 자료가 섞인다 (리포트 5.2: "삼성전자 HBM 판매 감소 이유" → SK 자료 1위).
   두 기업이 다 나오면(비교 질문) 기업마다 따로 K/2개씩 검색해 번갈아 합친다. 한 번에 검색하면 한쪽 자료만
   나온다 ("SK하이닉스와 삼성전자의 HBM 전략을 비교하면?" → SK 청크 6개). 기업이 없으면 필터 없이 검색한다.
2. 검색 (하이브리드): 벡터 검색으로 후보 POOL개를 뽑고(MAX_DISTANCE보다 먼 청크는 버림), 후보 안에서
   키워드 점수(BM25, 한글은 2글자 단위)로 한 번 더 순위를 매겨 두 순위를 RRF로 합친 뒤 상위 K개를 쓴다.
   벡터만 쓰면 표현이 다른 슬라이드 문장이 밀린다: "삼성전자가 HBM 판매가 줄었다고 밝힌 이유는?"의 근거
   ('25.1Q 경영설명회 p.8 "수출 통제 영향 등에 따른 HBM 판매 감소")가 벡터 15위 → 하이브리드 3위 (리포트 5.3).
3. 1차 거절: 남은 청크가 없으면 LLM을 부르지 않고 거절한다 (공시와 무관한 질문, 비용 0).
4. 답변: LLM(config.LLM_MODEL)에 근거 청크를 [1]..[K] 번호로 주고, 근거 안의 내용으로만 답하게 한다.
   구조화 출력(answerable, answer, used_sources)으로 받는다.
5. 2차 거절: LLM이 근거로 답할 수 없다고 하면(answerable=False) 거절 문구를 돌려준다.
   답할 수 있으면 LLM이 실제로 쓴 번호의 출처만 붙인다.

결과(QAResult): question, answer, answerable, refusal_reason, company_filter, sources(번호·기업·공시명·제출일·
링크·위치·거리·chunk_id), retrieved(검색된 청크 수). 대시보드는 이 결과를 그대로 보여 준다.

실행: python -m src.rag.qa_chain "SK하이닉스 2024년 3분기 HBM 매출 증가율은?"
      python -m src.rag.qa_chain --samples   (예시 질문 묶음 실행 → outputs/reports/qa_samples.csv,
                                             대시보드용 qa_samples.json: 답변·출처·근거 발췌)
      (build_index 다음. 질문 임베딩과 답변에 OpenAI API 호출)

담당: 한도윤 (공시 분석)
일정: Day 5
"""

import argparse
import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime

import pandas as pd
from pydantic import BaseModel, Field

from src.common import config
from src.rag import build_index

K = 6
POOL = 40  # 벡터 검색 후보 수 (이 안에서 키워드 점수로 다시 순위를 매긴다)
RRF_K = 60  # Reciprocal Rank Fusion 상수 (관례값)
# 교차 인코더 재정렬 (선택, requirements/rerank.txt). 후보 POOL개를 질문과 한 쌍씩 다시 채점한다 (리포트 5.4)
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
RERANK_MAX_LENGTH = 512
# cosine 거리 상한. 공시 질문의 관련 청크는 0.3~0.6, 공시와 무관한 질문은 이보다 멀다 (2026-11-18 표본 확인, 리포트 5.3)
MAX_DISTANCE = 0.65
REFUSAL = "제공된 공시 자료에서 근거를 찾을 수 없어 답변할 수 없습니다."
SAMPLES_PATH = config.OUTPUTS_DIR / "reports" / "qa_samples.csv"
# 대시보드가 API 없이 보여 줄 예시 답변 (답변·출처·근거 발췌 전체). 질문 묶음을 다시 돌리면 갱신된다
SAMPLES_JSON_PATH = config.OUTPUTS_DIR / "reports" / "qa_samples.json"

COMPANY_PATTERNS = {
    "SK하이닉스": re.compile(r"SK\s*하이닉스|하이닉스|SK\s*hynix|\bSK\b", re.I),
    "삼성전자": re.compile(r"삼성", re.I),
}

SYSTEM_PROMPT = """당신은 SK하이닉스·삼성전자의 DART 공시를 근거로 답하는 분석 보조입니다.
규칙:
- 아래 [번호] 근거 안에 있는 내용만 사용합니다. 근거에 없는 사실·수치·추측을 더하지 않습니다.
- 문장마다 근거 번호를 [1]처럼 붙입니다. 수치는 근거에 적힌 그대로(단위 포함) 씁니다.
- 질문한 기업·시점과 근거의 기업·제출일이 맞는지 확인합니다. 다른 기업·시점의 자료로 대신 답하지 않습니다.
- 근거로 답할 수 없으면 answerable=false로 하고 answer는 비워 둡니다. 일부만 답할 수 있으면 답할 수 있는 부분만
  답하고, 근거에 없는 부분은 "공시에서 확인되지 않음"이라고 밝힙니다.
- 공시 내용은 회사의 주장·전망일 수 있습니다. 전망·계획은 "회사는 ~라고 밝혔다"처럼 출처의 말로 씁니다.
- 한국어로 간결하게(5문장 이내) 답합니다."""


class Answer(BaseModel):
    answerable: bool = Field(description="근거만으로 질문에 답할 수 있으면 true")
    answer: str = Field(description="근거 번호를 붙인 답변. answerable=false면 빈 문자열")
    used_sources: list[int] = Field(description="답변에 실제로 쓴 근거 번호 목록")


@dataclass
class QAResult:
    question: str
    answer: str
    answerable: bool
    refusal_reason: str | None = None
    company_filter: str | None = None
    retrieved: int = 0
    sources: list[dict] = field(default_factory=list)


def detect_companies(question: str) -> list[str]:
    """질문에 나오는 기업 이름(DB corp_name) 목록 (COMPANY_PATTERNS 순서)."""
    return [name for name, pat in COMPANY_PATTERNS.items() if pat.search(question)]


def detect_company(question: str) -> str | None:
    """질문에 한 기업만 나오면 그 기업 이름. 둘 다 또는 없으면 None."""
    found = detect_companies(question)
    return found[0] if len(found) == 1 else None


def location(meta: dict) -> str:
    """청크 위치 표시: 첨부는 '첨부 <파일명> p.N', 본문은 섹션 이름."""
    if meta.get("page"):
        return f"첨부 {meta['file_name']} p.{meta['page']}"
    return meta.get("section", "")


def source_info(n: int, doc, distance: float) -> dict:
    m = doc.metadata
    return {
        "n": n, "corp_name": m.get("corp_name"), "report_nm": m.get("report_nm"), "rcept_dt": m.get("rcept_dt"),
        "url": m.get("url"), "location": location(m), "distance": round(float(distance), 3),
        "chunk_id": doc.id or m.get("chunk_id"),
    }


_HEADER = re.compile(r"^\[[^\]]*\]\n")
_WORD = re.compile(r"[0-9A-Za-z]+|[가-힣]+")
# 숫자+단위 ('16단', '2025년', '3분기', '12H'): 숫자와 단위를 떼면 '16'·'단'만 남아 핵심 단서가 사라진다
_NUM_UNIT = re.compile(r"(?<![0-9A-Za-z.])(\d+(?:\.\d+)?)([가-힣]{1,2}|[A-Za-z]{1,4})")


def keyword_tokens(text: str) -> list[str]:
    """키워드 점수용 토큰. 청크 머리말은 빼고, 한글 단어는 2글자씩 겹쳐 자른다 ('판매가' → 판매·매가).
    조사가 붙어도('판매가'·'판매') 같은 2글자가 남아 맞는다. 영문·숫자는 소문자 단어 그대로.
    숫자+단위('16단', '2025년', '12H')는 붙은 채로 토큰을 하나 더 넣는다 (2026-11-18, 리포트 5.4)."""
    body = _HEADER.sub("", text)
    out: list[str] = []
    for w in _WORD.findall(body):
        if "가" <= w[0] <= "힣":
            out += [w] if len(w) == 1 else [w[i:i + 2] for i in range(len(w) - 1)]
        else:
            out.append(w.lower())
    for num, unit in _NUM_UNIT.findall(body):
        if "가" <= unit[0] <= "힣":  # 한글 단위는 1글자·2글자 둘 다 ('16단을' → 16단·16단을, '3분기' → 3분·3분기)
            out += [num + unit[:1]] + ([num + unit] if len(unit) == 2 else [])
        else:
            out.append((num + unit).lower())
    return out


def bm25_scores(query: str, texts: list[str], k1: float = 1.2, b: float = 0.75) -> list[float]:
    """후보 문서들 안에서 계산한 BM25 점수."""
    docs = [keyword_tokens(t) for t in texts]
    if not docs:
        return []
    n, avg = len(docs), (sum(map(len, docs)) / len(docs)) or 1
    df = Counter(g for d in docs for g in set(d))
    terms = set(keyword_tokens(query))
    scores = []
    for d in docs:
        tf = Counter(d)
        s = 0.0
        for g in terms:
            if tf[g]:
                idf = math.log(1 + (n - df[g] + 0.5) / (df[g] + 0.5))
                s += idf * tf[g] * (k1 + 1) / (tf[g] + k1 * (1 - b + b * len(d) / avg))
        scores.append(s)
    return scores


def rrf_order(vector_rank_scores: list[float]) -> list[int]:
    """후보(벡터 순서대로)의 키워드 점수를 받아, 벡터 순위와 키워드 순위를 RRF로 합친 순서(후보 인덱스)."""
    kw_order = sorted(range(len(vector_rank_scores)), key=lambda i: (-vector_rank_scores[i], i))
    kw_rank = {i: r for r, i in enumerate(kw_order, 1)}
    fused = {i: 1 / (RRF_K + i + 1) + 1 / (RRF_K + kw_rank[i]) for i in range(len(vector_rank_scores))}
    return sorted(fused, key=lambda i: (-fused[i], i))


class CrossEncoderReranker:
    """질문·청크 쌍을 함께 읽고 관련도를 채점하는 교차 인코더 (sentence-transformers CrossEncoder)."""

    def __init__(self, model: str = RERANK_MODEL, max_length: int = RERANK_MAX_LENGTH):
        from sentence_transformers import CrossEncoder

        self.model = CrossEncoder(model, max_length=max_length)

    def scores(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        return [float(s) for s in self.model.predict([(query, t) for t in texts], batch_size=8)]


def load_reranker():
    """재정렬 모델. 패키지가 없으면 None (그때는 RRF 순서를 그대로 쓴다)."""
    try:
        return CrossEncoderReranker()
    except ImportError:
        return None


def retrieve_for_question(question: str, store, k: int = K, max_distance: float = MAX_DISTANCE,
                          reranker=None) -> list[tuple]:
    """질문의 기업 수에 따라 검색한다: 한 기업 → 그 기업만, 두 기업 → 기업별 k/2개씩 번갈아, 없음 → 전체."""
    return merge_ranked(retrieve_ranked(question, store, k, max_distance, reranker), k)


def retrieve_ranked(question: str, store, k: int = K, max_distance: float = MAX_DISTANCE,
                    reranker=None) -> list[list[tuple]]:
    """검색 대상(기업)별로 후보 전체를 순위대로 정렬한 목록. 후보 수가 같으면 결과가 k와 무관하므로,
    한 번 재정렬한 결과를 여러 k에 나눠 쓸 수 있다 (평가: 검색 지표 POOL개와 답변 K개, 리포트 5.4)."""
    companies = detect_companies(question)
    targets = companies if len(companies) >= 2 else [detect_company(question)]
    pool = max(POOL, math.ceil(k / len(targets)))
    return [retrieve(question, store, pool, c, max_distance, pool=pool, reranker=reranker) for c in targets]


def merge_ranked(groups: list[list[tuple]], k: int = K) -> list[tuple]:
    """retrieve_ranked 결과에서 상위 k개. 여러 기업이면 기업별 k/n개씩 번갈아 놓는다."""
    if len(groups) == 1:
        return groups[0][:k]
    per = [g[:math.ceil(k / len(groups))] for g in groups]
    merged = [r for group in zip(*[p + [None] * (k - len(p)) for p in per]) for r in group if r is not None]
    return merged[:k]


def retrieve(question: str, store, k: int = K, company: str | None = None,
             max_distance: float = MAX_DISTANCE, pool: int = POOL, reranker=None) -> list[tuple]:
    """(Document, 벡터 거리) 목록 k개. 기업 필터 → 벡터 후보 pool개(거리 상한 적용) → 키워드 점수와 RRF로 재정렬.
    reranker가 있으면 후보 전체를 교차 인코더 점수로 다시 정렬한다 (동점이면 RRF 순서)."""
    flt = {"corp_name": company} if company else None
    results = store.similarity_search_with_score(question, k=max(pool, k), filter=flt)
    results = [(doc, dist) for doc, dist in results if dist <= max_distance]
    order = rrf_order(bm25_scores(question, [doc.page_content for doc, _ in results]))
    if reranker is not None and order:
        ce = reranker.scores(question, [results[i][0].page_content for i in order])
        order = [i for _, _, i in sorted(zip(ce, range(len(order)), order), key=lambda x: (-x[0], x[1]))]
    return [results[i] for i in order[:k]]


def format_context(results: list[tuple]) -> str:
    """LLM에 넘길 근거. 청크 본문 앞의 머리말에 기업·공시명·제출일·섹션이 이미 들어 있다."""
    return "\n\n".join(f"[{i}] {doc.page_content}" for i, (doc, _) in enumerate(results, 1))


def make_llm():
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(model=config.LLM_MODEL, api_key=config.require_env("OPENAI_API_KEY"))
    return llm.with_structured_output(Answer)


def generate(question: str, results: list[tuple], llm) -> Answer:
    messages = [
        ("system", SYSTEM_PROMPT),
        ("human", f"근거:\n{format_context(results)}\n\n질문: {question}"),
    ]
    return llm.invoke(messages)


def ask(question: str, store=None, llm=None, k: int = K, max_distance: float = MAX_DISTANCE,
        reranker=None, results: list[tuple] | None = None) -> QAResult:
    """질문 하나에 답한다. store·llm을 넘기면 그것을 쓴다 (테스트·대시보드에서 재사용).
    results(검색 결과)를 넘기면 검색을 건너뛴다 (평가에서 같은 재정렬을 두 번 하지 않으려고)."""
    company = " · ".join(detect_companies(question)) or None
    if results is None:
        store = store if store is not None else build_index.open_store()
        results = retrieve_for_question(question, store, k, max_distance, reranker=reranker)
    if not results:
        return QAResult(question, REFUSAL, False, "관련 공시 없음 (검색 거리 기준)", company, 0)

    out = generate(question, results, llm if llm is not None else make_llm())
    if not out.answerable or not out.answer.strip():
        return QAResult(question, REFUSAL, False, "근거로 답할 수 없음 (LLM 판단)", company, len(results))

    used = [n for n in dict.fromkeys(out.used_sources) if 1 <= n <= len(results)]
    used = used or list(range(1, len(results) + 1))  # 번호를 안 돌려주면 검색된 근거 전부를 보인다
    sources = [source_info(n, *results[n - 1]) for n in used]
    return QAResult(question, out.answer.strip(), True, None, company, len(results), sources)


def format_result(r: QAResult) -> str:
    lines = [f"질문: {r.question}"]
    if r.company_filter:
        lines.append(f"(기업 필터: {r.company_filter})")
    lines.append(f"답변: {r.answer}")
    if not r.answerable:
        lines.append(f"(거절 이유: {r.refusal_reason}, 검색된 근거 {r.retrieved}개)")
    for s in r.sources:
        lines.append(f"  [{s['n']}] {s['corp_name']} | {s['report_nm']} | {s['rcept_dt']} | {s['location']} "
                     f"| 거리 {s['distance']} | {s['url']}")
    return "\n".join(lines)


# 예시 질문: 답할 수 있어야 하는 질문과 거절해야 하는 질문을 섞는다 (리포트 5.3)
SAMPLE_QUESTIONS = [
    ("SK하이닉스 2024년 3분기 HBM 매출은 전 분기 대비 얼마나 늘었나?", "답변"),
    ("삼성전자가 HBM 판매가 줄었다고 밝힌 이유는?", "답변"),
    ("SK하이닉스 청주 M15X 신규 시설투자 금액은?", "답변"),
    ("삼성전자의 HBM 관련 연구개발 실적은?", "답변"),
    ("SK하이닉스 인디애나 패키징 공장 계획은?", "답변"),
    ("SK하이닉스와 삼성전자의 HBM 전략을 비교하면?", "답변"),
    ("마이크론의 HBM 시장 점유율은?", "거절"),          # 공시 대상 기업이 아님
    ("삼성전자 2027년 HBM 매출 실적은?", "거절"),        # 기간 밖
    ("오늘 서울 날씨는?", "거절"),                       # 공시와 무관
]


def source_texts(store, results: list[QAResult]) -> dict[str, str]:
    """출처 청크 id → 본문 (예시 답변 저장용). store에 get이 없으면 빈 dict."""
    ids = list(dict.fromkeys(s["chunk_id"] for r in results for s in r.sources))
    if not ids or not hasattr(store, "get"):
        return {}
    got = store.get(ids=ids)
    return dict(zip(got["ids"], got["documents"]))


def save_samples_json(results: list[QAResult], texts: dict[str, str], path=None, reranker: str | None = None) -> dict:
    """예시 답변을 JSON으로 저장한다. 대시보드는 이 파일을 읽어 API 호출 없이 예시 답변을 보여 준다."""
    manifest = build_index.MANIFEST_PATH
    fingerprint = json.loads(manifest.read_text(encoding="utf-8")).get("chunks_fingerprint") if manifest.exists() else None
    data = {
        "created_at": datetime.now().isoformat(timespec="seconds"), "model": config.LLM_MODEL,
        "embedding_model": build_index.EMBEDDING_MODEL, "chunks_fingerprint": fingerprint, "reranker": reranker,
        "results": [asdict(r) for r in results],
        "texts": {cid: texts[cid] for r in results for cid in (s["chunk_id"] for s in r.sources) if cid in texts},
    }
    path = path or SAMPLES_JSON_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def load_samples_json(path=None) -> dict | None:
    """저장된 예시 답변. 없으면 None. results는 QAResult로 바꿔 돌려준다."""
    path = path or SAMPLES_JSON_PATH
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    data["results"] = [QAResult(**r) for r in data["results"]]
    return data


def run_samples(store=None, llm=None, json_path=None, reranker=None) -> pd.DataFrame:
    store = store if store is not None else build_index.open_store()
    llm = llm if llm is not None else make_llm()
    rows, results = [], []
    for q, expected in SAMPLE_QUESTIONS:
        r = ask(q, store, llm, reranker=reranker)
        results.append(r)
        print(format_result(r) + "\n")
        rows.append({
            "question": q, "expected": expected, "result": "답변" if r.answerable else "거절",
            "company_filter": r.company_filter or "", "retrieved": r.retrieved,
            "refusal_reason": r.refusal_reason or "", "answer": r.answer,
            "sources": " ; ".join(f"[{s['n']}] {s['corp_name']} {s['report_nm']} {s['rcept_dt']} {s['location']}"
                                  for s in r.sources),
            "min_distance": min((s["distance"] for s in r.sources), default=None),
            "model": config.LLM_MODEL,
        })
    df = pd.DataFrame(rows)
    SAMPLES_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(SAMPLES_PATH, index=False, encoding="utf-8-sig")
    save_samples_json(results, source_texts(store, results), json_path,
                      RERANK_MODEL if reranker is not None else None)
    print(f"기대와 같음 {int((df['expected'] == df['result']).sum())}/{len(df)}  "
          f"저장: {SAMPLES_PATH}, {json_path or SAMPLES_JSON_PATH}")
    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="공시 근거 질의응답")
    parser.add_argument("question", nargs="?", help="질문")
    parser.add_argument("--samples", action="store_true", help="예시 질문 묶음 실행 → qa_samples.csv·qa_samples.json")
    parser.add_argument("-k", type=int, default=K)
    parser.add_argument("--rerank", action="store_true", help="교차 인코더 재정렬 사용 (requirements/rerank.txt)")
    args = parser.parse_args()
    rr = load_reranker() if args.rerank else None
    if args.rerank and rr is None:
        parser.error("재정렬 모델을 불러오지 못했습니다: pip install -r requirements/rerank.txt")
    if args.samples:
        run_samples(reranker=rr)
    elif args.question:
        print(format_result(ask(args.question, k=args.k, reranker=rr)))
    else:
        parser.error("질문을 입력하거나 --samples를 쓰세요")
