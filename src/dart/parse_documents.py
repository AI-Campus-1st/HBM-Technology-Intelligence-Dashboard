"""
원문 zip(data/raw/dart/documents)에서 텍스트를 추출·정제해 DB disclosure 테이블에 적재한다.

- zip 안의 본 문서(<rcept_no>.xml)만 읽는다. 첨부(<rcept_no>_<번호>.xml, 감사보고서 등)는 쓰지 않는다.
- 원문 형식은 DART XML(dart3.xsd)과 HTML 두 가지다. 태그를 지우고 문단·표 행 단위로 줄을 나눈다.
- 결과: text_status='확보'와 text, 또는 '실패'와 filter_reason(추출오류·본문없음)
- RAG 대상(rag_target): A·B·D·I는 확보하면 1. J 공정위공시는 본문에 J_KEYWORDS가 있을 때만 1
  (없으면 filter_reason='J_본문키워드없음'). 근거: 리포트 2.3 원문 표본 확인

실행: python -m src.dart.parse_documents   (collect_documents 다음. 다시 실행하면 같은 결과)

담당: 한도윤 (공시 분석)
일정: Day 2
"""

import html
import re
import zipfile
from pathlib import Path

import pandas as pd

from src.common import config, db
from src.dart.collect_documents import DOC_DIR, zip_path

SUMMARY_PATH = config.OUTPUTS_DIR / "reports" / "disclosure_text_summary.csv"

# J 공정위공시 RAG 대상: 설비투자·생산 관련 거래만 남긴다 (항공기·퇴직연금·급식·보험 거래 등 제외).
# 2026-11-16 검수 (J 207건, 리포트 2.3):
# - '반도체'·'장비'는 대규모기업집단현황공시의 계열사 업종 목록(예: "반도체 소자 제조업")에만 걸려 뺐다.
# - 대규모기업집단현황공시(계열사·임원 현황)와 부동산임대(수처리센터 운영설비 임대 등)는 공시명으로 뺀다.
# - 남는 것: SK하이닉스 "신규 FAB 구축" 건설 매입, 삼성전자 "사업장 건설 공사", 천안 생산 부속시설 부지 양수
J_KEYWORDS = re.compile(r"FAB|팹|건설|설비|생산|패키징|웨이퍼|HBM")
J_EXCLUDE_NAMES = ("대규모기업집단현황공시", "부동산임대")
MIN_TEXT_LEN = 50  # 이보다 짧으면 본문을 못 뽑은 것으로 본다

_DROP_BLOCKS = re.compile(r"<(style|script|head)\b.*?</\1\s*>", re.S | re.I)
_LINE_BREAK = re.compile(r"<\s*(br\s*/?|/p|/tr|/title|/h\d|/div|/li|/table)\s*>|<\s*(p|tr|title|table)\b[^>]*/>", re.I)
_CELL_BREAK = re.compile(r"<\s*/(td|th|te|tu)\s*>", re.I)
_TAG = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t 　]+")


def decode(raw: bytes) -> str:
    """UTF-8로 읽고, 안 되면 CP949로 읽는다 (일부 HTML 원문은 EUC-KR)."""
    for enc in ("utf-8", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def markup_to_text(markup: str) -> str:
    """DART XML/HTML을 사람이 읽는 텍스트로 바꾼다. 표는 셀을 ' | '로, 행·문단은 줄바꿈으로 구분한다."""
    s = _DROP_BLOCKS.sub(" ", markup)
    s = _LINE_BREAK.sub("\n", s)
    s = _CELL_BREAK.sub(" | ", s)
    s = html.unescape(_TAG.sub(" ", s))
    lines = (_SPACES.sub(" ", line).strip(" |") for line in s.splitlines())
    return "\n".join(line.strip() for line in lines if line.strip())


def main_document(path: Path, rcept_no: str) -> str:
    """zip에서 본 문서를 읽는다. 이름이 정확히 맞는 파일이 없으면 첫 파일을 쓴다."""
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        name = f"{rcept_no}.xml" if f"{rcept_no}.xml" in names else sorted(names)[0]
        return decode(zf.read(name))


def parse_one(rcept_no: str, pblntf_ty: str, doc_dir: Path = DOC_DIR, report_nm: str = "") -> dict:
    """공시 한 건의 원문 처리 결과 (text, text_status, rag_target, filter_reason)."""
    try:
        text = markup_to_text(main_document(zip_path(rcept_no, doc_dir), rcept_no))
    except (zipfile.BadZipFile, OSError, KeyError, IndexError) as e:
        return {"text": None, "text_status": "실패", "rag_target": 0, "filter_reason": f"추출오류: {e}"[:200]}
    if len(text) < MIN_TEXT_LEN:
        return {"text": None, "text_status": "실패", "rag_target": 0, "filter_reason": "본문없음"}
    if pblntf_ty == "J" and any(name in report_nm for name in J_EXCLUDE_NAMES):
        return {"text": text, "text_status": "확보", "rag_target": 0, "filter_reason": "J_공시명"}
    if pblntf_ty == "J" and not J_KEYWORDS.search(text):
        return {"text": text, "text_status": "확보", "rag_target": 0, "filter_reason": "J_본문키워드없음"}
    return {"text": text, "text_status": "확보", "rag_target": 1, "filter_reason": None}


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    """유형별 목록·원문 대상·확보·실패·RAG 대상 건수와 원문 확보율."""
    g = df.groupby("pblntf_ty")
    out = pd.DataFrame({
        "목록": g.size(),
        "대상아님": g["text_status"].apply(lambda s: int((s == "대상아님").sum())),
        "확보": g["text_status"].apply(lambda s: int((s == "확보").sum())),
        "실패": g["text_status"].apply(lambda s: int((s == "실패").sum())),
        "대기": g["text_status"].apply(lambda s: int((s == "대기").sum())),
        "RAG대상": g["rag_target"].sum().astype(int),
    })
    out.loc["합계"] = out.sum()
    attempted = out["확보"] + out["실패"]
    out["확보율"] = (out["확보"] / attempted.where(attempted > 0)).round(3)
    return out.reset_index().rename(columns={"index": "pblntf_ty"})


def main(db_path: Path = config.DB_PATH, doc_dir: Path = DOC_DIR) -> pd.DataFrame:
    conn = db.connect(db_path)
    try:
        df = db.read_table(conn, "disclosure", columns=["rcept_no", "pblntf_ty", "report_nm", "text_status"])
        # 원문 대상 중 zip이 있는 공시만 처리한다. 다운로드 실패·대상아님은 collect_documents의 기록을 둔다.
        has_zip = df["rcept_no"].map(lambda r: zip_path(r, doc_dir).exists()).astype(bool)
        todo = df[(df["text_status"] != "대상아님") & has_zip]
        results = [
            (parse_one(r, t, doc_dir, nm), r)
            for r, t, nm in zip(todo["rcept_no"], todo["pblntf_ty"], todo["report_nm"])
        ]
        with conn:
            conn.executemany(
                "UPDATE disclosure SET text=?, text_status=?, rag_target=?, filter_reason=? WHERE rcept_no=?",
                [(res["text"], res["text_status"], res["rag_target"], res["filter_reason"], r) for res, r in results],
            )
        final = db.read_table(conn, "disclosure", columns=["rcept_no", "pblntf_ty", "text_status", "rag_target", "text"])
    finally:
        conn.close()

    summary = summarize(final)
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(SUMMARY_PATH, index=False, encoding="utf-8-sig")
    lengths = final["text"].dropna().str.len()
    print(f"처리 {len(results)}건, 본문 길이 중앙값 {int(lengths.median()) if len(lengths) else 0:,}자, 합계 {int(lengths.sum()):,}자")
    print(summary.to_string(index=False))
    print(f"저장: {SUMMARY_PATH}")
    return summary


if __name__ == "__main__":
    main()
