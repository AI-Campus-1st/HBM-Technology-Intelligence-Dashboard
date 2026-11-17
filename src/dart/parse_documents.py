"""
원문 zip(data/raw/dart/documents)에서 텍스트를 추출·정제해 DB disclosure 테이블에 적재한다.

- zip 안의 본 문서(<rcept_no>.xml)만 읽는다. 첨부(<rcept_no>_<번호>.xml, 감사보고서 등)는 쓰지 않는다.
- 원문 형식은 DART XML(dart3.xsd)과 HTML 두 가지다. 태그를 지우고 문단·표 행 단위로 줄을 나눈다.
- 결과: text_status='확보'와 text, 또는 '실패'와 filter_reason(추출오류·본문없음)
- RAG 대상(rag_target): A·B·D·I는 확보하면 1. J 공정위공시는 본문에 J_KEYWORDS가 있을 때만 1
  (없으면 filter_reason='J_본문키워드없음'). 근거: 리포트 2.3 원문 표본 확인

정기보고서(A) 섹션 추출 (Day 3):
- 'II. 사업의 내용'을 소제목 7개로 나누고, 그중 사업·제품·투자·연구개발 섹션만 남긴다 (SECTIONS).
  목차에도 같은 제목이 있어 본문 쪽(마지막) 'II. 사업의 내용'부터 'III. 재무에 관한 사항' 앞까지 본다.
- 연구개발비용과 매출액 대비 비율, 시설투자액을 표에서 뽑는다 (rnd_capex).
  분기·반기보고서 수치는 그해 누계다. 두 회사의 R&D·투자 집계 기준이 달라 직접 비교하지 않는다 (리포트 3.3).
- 결과: data/processed/disclosure_sections.csv (섹션 본문, Day 5 chunking 입력)
        outputs/reports/disclosure_section_summary.csv (섹션별 글자 수·HBM 언급 수)
        outputs/reports/disclosure_rnd_capex.csv (보고서별 R&D·시설투자 수치)

실행: python -m src.dart.parse_documents              (collect_documents 다음. 텍스트 적재 + 섹션 추출, 다시 실행하면 같은 결과)
      python -m src.dart.parse_documents --sections   (DB 본문으로 섹션 추출만 다시. zip 불필요)

담당: 한도윤 (공시 분석)
일정: Day 2 (텍스트 적재), Day 3 (섹션 추출)
"""

import argparse
import html
import re
import zipfile
from pathlib import Path

import pandas as pd

from src.common import config, db
from src.dart.collect_documents import DOC_DIR, zip_path

SUMMARY_PATH = config.OUTPUTS_DIR / "reports" / "disclosure_text_summary.csv"
SECTIONS_PATH = config.PROCESSED_DIR / "disclosure_sections.csv"
SECTION_SUMMARY_PATH = config.OUTPUTS_DIR / "reports" / "disclosure_section_summary.csv"
RND_CAPEX_PATH = config.OUTPUTS_DIR / "reports" / "disclosure_rnd_capex.csv"

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


# ── 정기보고서 섹션 추출 (Day 3) ──

# 'II. 사업의 내용' 소제목 (번호, 제목, 섹션 성격). 성격이 None이면 경계로만 쓰고 저장하지 않는다.
# 근거: 2026-11-17 정기보고서 24건 모두 같은 7개 소제목 확인. 투자 현황은 3번 안에 있다
# (SK하이닉스 '4. 투자계획(현황)', 삼성전자 '(시설투자 현황)'). SK하이닉스 3분기보고서에는 투자계획이 없다.
SECTIONS: list[tuple[int, str, str | None]] = [
    (1, "사업의 개요", "사업"),
    (2, "주요 제품 및 서비스", "제품"),
    (3, "원재료 및 생산설비", "투자"),
    (4, "매출 및 수주상황", None),
    (5, "위험관리 및 파생거래", None),
    (6, "주요계약 및 연구개발활동", "연구개발"),
    (7, "기타 참고사항", "사업"),
]
_PART2 = re.compile(r"^II\.\s*사업의\s*내용\s*$")
_PART3 = re.compile(r"^III\.\s*재무에\s*관한\s*사항")
# 삼성전자는 부문별 연구개발 실적을 'XII. 상세표 > 4. 연구개발실적(상세)'로 따로 둔다 (HBM 언급 140건이 여기 있다).
# SK하이닉스 상세표에는 이 항목이 없다. 다음 '1. 전문가의 확인' 앞까지 본다.
DETAIL_RND = "연구개발실적(상세)"
_DETAIL_RND = re.compile(r"^\d+\.\s*연구개발실적\s*\(상세\)\s*$")
_DETAIL_END = re.compile(r"^\d+\.\s*전문가의\s*확인")
HBM_PATTERN = re.compile(r"HBM|고대역폭")
_NUMBER = re.compile(r"^△?[\d,]+$")
_PERCENT = re.compile(r"^(\d+(?:\.\d+)?)%$")


def _heading(no: int, title: str) -> re.Pattern:
    """'6. 주요계약 및 연구개발활동'처럼 줄 전체가 소제목인 경우만 맞춘다 (제목 안 띄어쓰기 차이는 허용)."""
    words = r"\s*".join(re.escape(w) for w in title.split())
    return re.compile(rf"^{no}\.\s*{words}\s*$")


def split_sections(text: str) -> dict[str, str]:
    """정기보고서 본문에서 'II. 사업의 내용' 소제목별 본문을 꺼낸다. {제목: 본문(소제목 줄 제외)}.

    소제목은 순서대로만 찾는다. 그래서 3번 안의 '4. 투자계획(현황)'을 4번 소제목으로 잘못 자르지 않는다.
    못 찾은 소제목은 결과에 없다.
    """
    lines = text.split("\n")
    starts = [i for i, line in enumerate(lines) if _PART2.match(line.strip())]
    if not starts:
        return {}
    begin = starts[-1] + 1  # 목차 다음 본문
    end = next((i for i in range(begin, len(lines)) if _PART3.match(lines[i].strip())), len(lines))

    found: list[tuple[int, str]] = []  # (줄 번호, 제목)
    pos = begin
    for no, title, _ in SECTIONS:
        pattern = _heading(no, title)
        hit = next((i for i in range(pos, end) if pattern.match(lines[i].strip())), None)
        if hit is not None:
            found.append((hit, title))
            pos = hit + 1
    out = {}
    for k, (start, title) in enumerate(found):
        stop = found[k + 1][0] if k + 1 < len(found) else end
        out[title] = "\n".join(lines[start + 1:stop]).strip()

    detail = [i for i in range(end, len(lines)) if _DETAIL_RND.match(lines[i].strip())]
    if detail:
        d0 = detail[-1] + 1
        d1 = next((i for i in range(d0, len(lines)) if _DETAIL_END.match(lines[i].strip())), len(lines))
        body = "\n".join(line for line in lines[d0:d1] if line.strip() != "☞ 본문 위치로 이동").strip()
        if body:
            out[DETAIL_RND] = body
    return out


def _value_after(lines: list[str], label: re.Pattern, value: re.Pattern, within: int = 6) -> str | None:
    """label에 맞는 첫 줄 다음 within줄 안에서 value에 맞는 첫 값 (표의 '당기' 열)."""
    for i, line in enumerate(lines):
        if label.search(line.strip()):
            for nxt in lines[i + 1:i + 1 + within]:
                if value.match(nxt.strip()):
                    return nxt.strip()
            return None
    return None


def _to_number(s: str | None) -> float | None:
    """'1,234' → 1234.0, '△1,234' → -1234.0"""
    if s is None:
        return None
    sign = -1 if s.startswith("△") else 1
    return sign * float(s.lstrip("△").replace(",", ""))


def rnd_capex(sections: dict[str, str]) -> dict:
    """연구개발비용·매출액 대비 비율·시설투자액 (표의 당기 열, 분기·반기는 그해 누계). 못 찾으면 None.

    - R&D (백만원): SK하이닉스 '연구개발비용 합계', 삼성전자 '연구개발비용 총계'(정부보조금 차감 전, 비율 분자와 같은 기준)
    - 비율 (%): '÷당기매출액' 설명 줄 다음 첫 % 값
    - 시설투자 (억원): SK하이닉스 '투자계획(현황)' 합계(십억원 → ×10, 유형자산 취득 기준),
      삼성전자 '(시설투자 현황)' 합계와 DS 부문
    """
    rnd = sections.get("주요계약 및 연구개발활동", "").split("\n")
    total = _value_after(rnd, re.compile(r"^연구개발비용\s*(합계|총계)$"), _NUMBER)
    ratio = _value_after(rnd, re.compile(r"÷\s*당기\s*매출액"), _PERCENT)

    facility = sections.get("원재료 및 생산설비", "").split("\n")
    capex_total = capex_ds = None
    # 삼성전자 2023 사업보고서는 '(시설투자 현황)' 뒤에 설명 문장이 같은 줄로 붙어 있어 줄 앞부분만 본다.
    for marker, scale in ((r"^\d\.\s*투자계획\s*\(현황\)$", 10), (r"^\(시설투자\s*현황\)", 1)):
        start = next((i for i, line in enumerate(facility) if re.match(marker, line.strip())), None)
        if start is None:
            continue
        block = facility[start:start + 80]
        raw_total = _value_after(block, re.compile(r"^합\s*계$"), _NUMBER, within=3)
        raw_ds = _value_after(block, re.compile(r"^DS\s*부문$"), _NUMBER, within=5)
        capex_total = _to_number(raw_total) * scale if raw_total else None
        capex_ds = _to_number(raw_ds) * scale if raw_ds else None
        break
    return {
        "rnd_expense_mil_krw": _to_number(total),
        "rnd_to_sales_pct": float(_PERCENT.match(ratio).group(1)) if ratio else None,
        "capex_100m_krw": capex_total,
        "capex_ds_100m_krw": capex_ds,
    }


def report_period(report_nm: str) -> str | None:
    """'분기보고서 (2025.09)' → '2025.09' (보고 기간 말)."""
    m = re.search(r"\((\d{4}\.\d{2})\)", report_nm)
    return m.group(1) if m else None


SECTION_TYPES = {title: kind for _, title, kind in SECTIONS if kind} | {DETAIL_RND: "연구개발"}


def tagged_sections(sections: dict[str, str]) -> list[tuple[str, str, str]]:
    """split_sections 결과에서 저장 대상 섹션만 (제목, 성격, 본문)으로. Day 5 chunking도 이 함수를 쓴다."""
    return [(title, SECTION_TYPES[title], body) for title, body in sections.items() if title in SECTION_TYPES]


def extract_sections(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """정기보고서(A)마다 섹션 행(성격이 있는 섹션만)과 R&D·투자 수치 행을 만든다."""
    section_rows, number_rows = [], []
    reports = df[(df["pblntf_ty"] == "A") & df["text"].notna()].sort_values(["rcept_dt", "corp_name"])
    for rec in reports.itertuples(index=False):
        meta = {
            "rcept_no": rec.rcept_no, "corp_name": rec.corp_name, "report_nm": rec.report_nm,
            "rcept_dt": rec.rcept_dt, "period": report_period(rec.report_nm),
        }
        sections = split_sections(rec.text)
        for title, kind, body in tagged_sections(sections):
            section_rows.append({
                **meta, "url": rec.url, "section": title, "section_type": kind,
                "n_chars": len(body), "hbm_count": len(HBM_PATTERN.findall(body)), "text": body,
            })
        n_part2 = sum(title in sections for _, title, _ in SECTIONS)  # 'II. 사업의 내용' 소제목을 몇 개 찾았나
        number_rows.append({**meta, "n_sections": n_part2, **rnd_capex(sections)})
    return pd.DataFrame(section_rows), pd.DataFrame(number_rows)


def sections_main(db_path: Path = config.DB_PATH) -> tuple[pd.DataFrame, pd.DataFrame]:
    """DB 본문으로 섹션·수치를 뽑아 저장한다. 원문 zip 없이도 다시 돌릴 수 있다."""
    conn = db.connect(db_path)
    try:
        df = db.read_table(
            conn, "disclosure", columns=["rcept_no", "corp_name", "report_nm", "rcept_dt", "pblntf_ty", "url", "text"]
        )
    finally:
        conn.close()
    sections, numbers = extract_sections(df)
    for path in (SECTIONS_PATH, SECTION_SUMMARY_PATH, RND_CAPEX_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
    sections.to_csv(SECTIONS_PATH, index=False, encoding="utf-8-sig")
    if not sections.empty:
        sections.drop(columns=["text", "url"]).to_csv(SECTION_SUMMARY_PATH, index=False, encoding="utf-8-sig")
    numbers.to_csv(RND_CAPEX_PATH, index=False, encoding="utf-8-sig")

    if numbers.empty:
        print("정기보고서 본문이 없다. 먼저 텍스트를 적재한다.")
        return sections, numbers
    short = int((numbers["n_sections"] < len(SECTIONS)).sum())
    print(f"정기보고서 {len(numbers)}건 → 섹션 {len(sections)}개 (소제목 7개를 다 못 찾은 보고서 {short}건)")
    if not sections.empty:
        print(sections.groupby(["section_type", "section"])[["n_chars", "hbm_count"]].sum().to_string())
    print(numbers.drop(columns=["rcept_no", "rcept_dt", "report_nm"]).to_string(index=False))
    print(f"저장: {SECTIONS_PATH}, {SECTION_SUMMARY_PATH}, {RND_CAPEX_PATH}")
    return sections, numbers


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
    sections_main(db_path)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="공시 원문 텍스트 적재 + 정기보고서 섹션 추출")
    parser.add_argument("--sections", action="store_true", help="DB 본문으로 섹션 추출만 다시 한다 (zip 불필요)")
    if parser.parse_args().sections:
        sections_main()
    else:
        main()
