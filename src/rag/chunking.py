"""
공시 텍스트를 청크로 나누고 메타데이터(공시명, 제출일, 링크, 섹션)를 붙인다. build_index(Day 5)의 입력.

- 대상: DB disclosure 중 원문을 확보했고 RAG 대상(rag_target=1)인 공시.
  RAG 대상 기준은 parse_documents(또는 이후 바뀐 기준)가 DB에 적은 값을 그대로 따른다.
- 정기보고서(A)는 본문 전체(건당 20만~70만 자, 대부분 재무제표·주석)를 쓰지 않는다.
  parse_documents.split_sections로 사업·제품·투자·연구개발 섹션만 꺼내 쓴다 (리포트 3.3).
  삼성전자 연구개발실적(상세)은 DX(TV·모바일 등)가 대부분이라 DS 부문 부분만 남긴다.
- 그 밖의 공시(B·D·I·J)는 본문 전체를 섹션 '본문' 하나로 본다.
- DART 표는 텍스트로 바뀌면 칸마다 줄이 나뉜다. 짧은 줄이 이어지면 ' | '로 묶어 한 줄로 만든 뒤 자른다.
  ('연구개발비용 합계 | 6,732,527 | 4,954,447 | ...'처럼 항목과 값이 같은 청크에 남게 하려는 것)
- 청크 앞에 머리말 '[기업 | 공시명 | 제출일 | 섹션]'을 붙인다. 본문에 회사명·시점이 없어도 검색되도록.
- chunk_id = <rcept_no>_<섹션 순번 2자리>_<청크 순번 3자리>. 같은 입력이면 같은 id가 나온다.

실행: python -m src.rag.chunking   (parse_documents 다음. DB만 읽는다)

저장:
- data/processed/disclosure_chunks.jsonl : 청크 한 줄에 하나 (text + 메타데이터). git에 올리지 않는다
- outputs/reports/disclosure_chunk_summary.csv : 기업 × 유형 × 섹션별 공시 수·청크 수·글자 수·HBM 청크 수

담당: 한도윤 (공시 분석)
일정: Day 3 (청킹), Day 5 (build_index에서 사용)
"""

import json
import re
from pathlib import Path

import pandas as pd
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.common import config, db
from src.dart import parse_documents
from src.eda.disclosure_trend import categorize

CHUNKS_PATH = config.PROCESSED_DIR / "disclosure_chunks.jsonl"
SUMMARY_PATH = config.OUTPUTS_DIR / "reports" / "disclosure_chunk_summary.csv"

# 청크 크기 (글자 수, 머리말 제외). 한국어는 대략 1글자 ≈ 1토큰 안팎이라 임베딩 한도(8k 토큰)보다 한참 작다.
# 표 한두 개나 문단 몇 개가 들어가는 크기. 겹침은 문장·표 행이 경계에서 끊길 때를 대비한 것.
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
MIN_CHUNK_CHARS = 30  # 이보다 짧은 조각(쪽 번호, '-' 등)은 버린다

# 표 칸으로 보는 짧은 줄. 단 '가. 주요 계약', '(1) 생산실적', '2. 연구개발비용' 같은 소제목은 묶지 않고 새 줄로 시작한다.
TABLE_CELL_MAX = 30
_SUBHEADING = re.compile(r"^([가-하]\.|\d{1,2}\.\s|\(\d{1,2}\)|[①-⑳]|□|※|\[)")

BODY_SECTION = "본문"
DETAIL_KEEP_FROM = re.compile(r"^DS\s*부문$")  # 삼성전자 연구개발실적(상세)에서 남길 부문의 시작 줄
DETAIL_STOP_AT = re.compile(r"^(SDC|Harman|하만)$")  # DS 다음 부문


def join_table_cells(text: str) -> str:
    """짧은 줄(표 칸)이 이어지면 ' | '로 묶는다. 긴 줄과 소제목은 그대로 둔다."""
    out: list[str] = []
    cells: list[str] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if len(line) <= TABLE_CELL_MAX and not _SUBHEADING.match(line):
            cells.append(line)
            continue
        if cells:
            out.append(" | ".join(cells))
            cells = []
        out.append(line)
    if cells:
        out.append(" | ".join(cells))
    return "\n".join(out)


def ds_only(detail: str) -> str:
    """삼성전자 연구개발실적(상세)에서 'DS 부문'부터 다음 부문(SDC 등) 앞까지만. DS 줄이 없으면 그대로."""
    lines = detail.split("\n")
    start = next((i for i, line in enumerate(lines) if DETAIL_KEEP_FROM.match(line.strip())), None)
    if start is None:
        return detail
    stop = next((i for i in range(start + 1, len(lines)) if DETAIL_STOP_AT.match(lines[i].strip())), len(lines))
    return "\n".join(lines[start:stop])


def document_sections(rec) -> list[tuple[str, str, str]]:
    """공시 한 건을 (섹션, 섹션 성격, 본문) 목록으로. 정기보고서에서 섹션을 못 찾으면 빈 목록."""
    if rec.pblntf_ty != "A":
        return [(BODY_SECTION, categorize(rec.report_nm), rec.text)]
    out = []
    for title, kind, body in parse_documents.tagged_sections(parse_documents.split_sections(rec.text)):
        if title == parse_documents.DETAIL_RND:
            body = ds_only(body)
        out.append((title, kind, body))
    return out


def header(rec, section: str) -> str:
    return f"[{rec.corp_name} | {rec.report_nm} | 제출일 {rec.rcept_dt} | {section}]"


def make_splitter(size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> RecursiveCharacterTextSplitter:
    # 줄 → 표 칸 구분(' | ') → 문장 → 공백 순으로 자를 곳을 찾는다
    return RecursiveCharacterTextSplitter(
        chunk_size=size, chunk_overlap=overlap, separators=["\n", " | ", ". ", " ", ""], keep_separator=False
    )


def chunk_disclosures(df: pd.DataFrame, splitter: RecursiveCharacterTextSplitter | None = None) -> list[dict]:
    """공시 DataFrame(rcept_no·corp_code·corp_name·report_nm·rcept_dt·pblntf_ty·url·text)을 청크 dict 목록으로."""
    splitter = splitter or make_splitter()
    chunks = []
    docs = df[df["text"].notna()].sort_values(["rcept_dt", "rcept_no"])
    for rec in docs.itertuples(index=False):
        sections = document_sections(rec)
        if not sections:
            print(f"경고: 섹션을 찾지 못해 건너뜀 {rec.rcept_no} {rec.report_nm}")
            continue
        for s_idx, (section, section_type, body) in enumerate(sections):
            pieces = [p.strip() for p in splitter.split_text(join_table_cells(body))]
            pieces = [p for p in pieces if len(p) >= MIN_CHUNK_CHARS]
            for c_idx, piece in enumerate(pieces):
                chunks.append({
                    "chunk_id": f"{rec.rcept_no}_{s_idx:02d}_{c_idx:03d}",
                    "rcept_no": rec.rcept_no,
                    "corp_code": rec.corp_code,
                    "corp_name": rec.corp_name,
                    "report_nm": rec.report_nm,
                    "rcept_dt": rec.rcept_dt,
                    "pblntf_ty": rec.pblntf_ty,
                    "url": rec.url,
                    "section": section,
                    "section_type": section_type,
                    "chunk_index": c_idx,
                    "n_chars": len(piece),
                    "has_hbm": bool(parse_documents.HBM_PATTERN.search(piece)),
                    "text": f"{header(rec, section)}\n{piece}",
                })
    return chunks


def summarize(chunks: list[dict]) -> pd.DataFrame:
    """기업 × 유형 × 섹션별 공시 수·청크 수·글자 수·HBM 청크 수."""
    if not chunks:
        return pd.DataFrame(columns=["corp_name", "pblntf_ty", "section", "n_docs", "n_chunks", "n_chars", "hbm_chunks"])
    df = pd.DataFrame(chunks)
    out = df.groupby(["corp_name", "pblntf_ty", "section"]).agg(
        n_docs=("rcept_no", "nunique"), n_chunks=("chunk_id", "size"),
        n_chars=("n_chars", "sum"), hbm_chunks=("has_hbm", "sum"),
    ).reset_index()
    return out


def save_chunks(chunks: list[dict], path: Path | None = None) -> None:
    path = path or CHUNKS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")


def load_chunks(path: Path | None = None) -> list[dict]:
    with open(path or CHUNKS_PATH, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def to_documents(chunks: list[dict]):
    """LangChain Document 목록 (build_index용). 메타데이터는 text를 뺀 나머지 전부 (Chroma는 스칼라 값만 받는다)."""
    from langchain_core.documents import Document

    return [Document(page_content=c["text"], metadata={k: v for k, v in c.items() if k != "text"}, id=c["chunk_id"])
            for c in chunks]


def load_targets(db_path: Path = config.DB_PATH) -> pd.DataFrame:
    """RAG 대상이고 원문을 확보한 공시."""
    conn = db.connect(db_path)
    try:
        df = db.read_table(conn, "disclosure", columns=[
            "rcept_no", "corp_code", "corp_name", "report_nm", "rcept_dt", "pblntf_ty", "url", "text",
            "text_status", "rag_target",
        ])
    finally:
        conn.close()
    return df[(df["rag_target"] == 1) & (df["text_status"] == "확보")].drop(columns=["text_status", "rag_target"])


def main(db_path: Path = config.DB_PATH) -> list[dict]:
    targets = load_targets(db_path)
    chunks = chunk_disclosures(targets)
    save_chunks(chunks)
    summary = summarize(chunks)
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(SUMMARY_PATH, index=False, encoding="utf-8-sig")

    lengths = pd.Series([c["n_chars"] for c in chunks], dtype=int)
    print(f"RAG 대상 공시 {len(targets)}건 → 청크 {len(chunks):,}개 "
          f"(글자 수 중앙값 {int(lengths.median()) if len(lengths) else 0}, 합계 {int(lengths.sum()):,}자, "
          f"HBM 포함 {sum(c['has_hbm'] for c in chunks)}개)")
    print(summary.groupby(["pblntf_ty", "section"])[["n_docs", "n_chunks", "n_chars", "hbm_chunks"]].sum().to_string())
    print(f"저장: {CHUNKS_PATH}, {SUMMARY_PATH}")
    return chunks


if __name__ == "__main__":
    main()
