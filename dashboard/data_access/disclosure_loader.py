"""
DB에서 공시 목록·건수를 조회하고 벡터 DB를 로드한다.

- 저장된 결과만 읽는다: SQLite(disclosure), 벡터 DB 매니페스트(data/vectordb/manifest.json),
  평가 요약(outputs/reports/qa_eval_v1_summary.csv). 없으면 None·빈 표를 돌려주고 화면이 안내한다.
- 예시 질문 9개는 미리 저장한 답변(outputs/reports/qa_samples.json, `qa_chain --samples`로 생성)을 보여 준다.
  API를 부르지 않으므로 키·벡터 DB가 없어도, 발표 중 네트워크가 끊겨도 예시 답변은 보인다.
- 직접 입력한 질문만 실시간으로 답한다 (질문 임베딩 + LLM). 질문이 미리 정해져 있지 않아 저장해 둘 수 없기 때문이다.
- 벡터 DB·LLM 객체는 한 번만 만들어 재사용한다 (st.cache_resource). 질문 답변은 qa_chain.ask가 한다.

담당: 한도윤 (공시 분석)
일정: Day 6
"""

import json
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

from src.common import config
from src.rag import build_index, qa_chain

TYPE_NAMES = {"A": "정기공시", "B": "주요사항보고", "D": "지분공시", "I": "거래소공시", "J": "공정위공시"}
MANIFEST_PATH = config.VECTORDB_DIR / "manifest.json"
EVAL_SUMMARY_PATH = config.OUTPUTS_DIR / "reports" / "qa_eval_v1_summary.csv"


def read_manifest(path: Path | None = None) -> dict | None:
    """벡터 DB 매니페스트(청크 수·지문·임베딩 모델). 파일이 없으면 None."""
    path = path or MANIFEST_PATH
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_eval_summary(path: Path | None = None) -> dict:
    """평가 요약 표를 {지표: 값}으로. 파일이 없으면 빈 dict."""
    path = path or EVAL_SUMMARY_PATH
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    return dict(zip(df["지표"], df["값"]))


def read_rag_disclosures(db_path: Path | None = None) -> pd.DataFrame:
    """RAG 대상 공시 목록 (rag_target=1), 최근 제출일 순. DB가 없으면 빈 표."""
    cols = ["rcept_no", "corp_name", "report_nm", "rcept_dt", "pblntf_ty", "url"]
    db_path = db_path or config.DB_PATH
    if not Path(db_path).exists():
        return pd.DataFrame(columns=cols + ["type_name"])
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(
            f"SELECT {', '.join(cols)} FROM disclosure WHERE rag_target = 1 ORDER BY rcept_dt DESC, rcept_no DESC",
            conn,
        )
    df["type_name"] = df["pblntf_ty"].map(TYPE_NAMES).fillna(df["pblntf_ty"])
    return df


def readiness(manifest: dict | None, api_key: str | None = None) -> list[str]:
    """Q&A를 쓸 수 없는 이유 목록. 비어 있으면 질문할 수 있다 (키 값은 보이지 않는다)."""
    api_key = config.OPENAI_API_KEY if api_key is None else api_key
    problems = []
    if manifest is None:
        problems.append("벡터 DB가 없습니다. 드라이브의 vectordb zip을 프로젝트 루트에 풀어 주세요.")
    if not api_key:
        problems.append("OPENAI_API_KEY가 비어 있습니다. .env에 키를 넣어 주세요.")
    return problems


def read_saved_answers(path: Path | None = None) -> dict | None:
    """저장된 예시 답변: {"created_at", "model", "answers": {질문: (QAResult, {chunk_id: 본문})}}. 없으면 None."""
    data = qa_chain.load_samples_json(path)
    if data is None:
        return None
    answers = {r.question: (r, {s["chunk_id"]: data["texts"].get(s["chunk_id"], "") for s in r.sources})
               for r in data["results"]}
    return {"created_at": data["created_at"], "model": data["model"], "answers": answers}


def chunk_texts(store, ids: list[str]) -> dict[str, str]:
    """청크 id → 본문. 근거 발췌를 보여 줄 때 쓴다."""
    if not ids:
        return {}
    got = store.get(ids=list(dict.fromkeys(ids)))
    return dict(zip(got["ids"], got["documents"]))


# ── Streamlit 캐시 래퍼 ──
@st.cache_data(show_spinner=False)
def load_manifest() -> dict | None:
    return read_manifest()


@st.cache_data(show_spinner=False)
def load_eval_summary() -> dict:
    return read_eval_summary()


@st.cache_data(show_spinner=False)
def load_rag_disclosures() -> pd.DataFrame:
    return read_rag_disclosures()


@st.cache_data(show_spinner=False)
def load_saved_answers() -> dict | None:
    return read_saved_answers()


@st.cache_resource(show_spinner=False)
def get_store():
    return build_index.open_store()


@st.cache_resource(show_spinner=False)
def get_llm():
    return qa_chain.make_llm()
