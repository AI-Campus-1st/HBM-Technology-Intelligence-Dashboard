"""
실적 공시의 첨부 경영설명회 자료(PDF, 국문)를 DART 웹 화면에서 받아 텍스트를 추출한다. RAG(chunking)의 입력.

왜 필요한가 (초안 §11 논의 질문 8, 2026-11-18 결정: 넣는다):
- 영업(잠정)실적 공시의 본 문서는 숫자 표뿐이다. HBM 판매·전망 발언은 첨부 경영설명회 PDF에 있다
  (예: SK하이닉스 '24.3Q "HBM 매출 QoQ +70% 이상"). 근거 공시 판정(issue_evidence)도 이 첨부로 했다.
- 첨부는 OpenAPI(document.xml) zip에 들어 있지 않고 DART 웹 화면에서만 받을 수 있다.

범위:
- 대상 공시: 공시명에 '영업(잠정)실적'이 있는 공시 (두 회사의 분기 실적 공시와 [기재정정])
  [기재정정]의 첨부는 정정 전 원래 공시에 붙어 있어 att_rcept_no(첨부의 접수번호)로 받는다.
  삼성전자 [기재정정]의 첨부는 월초 잠정실적 설명 자료(1~2쪽)다. 원본 실적 공시의 첨부는 분기 실적발표 자료
- 받는 파일: 첨부 중 PDF이고 국문인 것 (ENG·English 파일 제외). 선택 여부와 이유는 목록 CSV에 남긴다.
- 지속가능경영보고서·지배구조 첨부·영업보고서(스캔)·감사보고서는 대상 공시가 달라 자연히 빠진다 (2026-11-17 조사)

단계 (네트워크가 필요한 것은 1·2뿐):
1. 목록: 공시마다 웹 화면(main.do)의 '첨부' 목록 → 첨부별 다운로드 화면의 파일 목록 → attachment_list.csv
2. 다운로드: 선택된 PDF만 받는다. 이미 받은 파일은 건너뛴다 (다시 실행해도 같은 결과)
3. 추출: PDF 쪽(page)별 텍스트 → data/processed/disclosure_attachments.jsonl (파일 하나에 한 줄)

실행: python -m src.dart.collect_attachments            (1~3 전부. collect_list 다음)
      python -m src.dart.collect_attachments --extract  (3만. 공유받은 data/raw/dart/attachments로 추출, 네트워크 불필요)

저장:
- data/raw/dart/attachments/attachment_list.csv : 대상 공시의 첨부 파일 전체 목록과 선택 여부(selected, reason)
- data/raw/dart/attachments/<rcept_no>_<dcm_no>_<파일명>.pdf : 받은 PDF (원본 zip처럼 공유 드라이브로 공유)
- data/processed/disclosure_attachments.jsonl : 추출 텍스트 (rcept_no, att_rcept_no, dcm_no, file_name, n_pages, n_chars, n_hbm, pages)
  rcept_no는 DB disclosure의 접수번호(청크가 붙는 공시), att_rcept_no는 첨부가 실제로 붙은 접수번호

담당: 한도윤 (공시 분석)
일정: Day 4 (Day 5 RAG 준비)
"""

import argparse
import html
import json
import re
import time
from pathlib import Path

import pandas as pd
import requests

from src.common import config, db

BASE_URL = "https://dart.fss.or.kr"
VIEWER_URL = BASE_URL + "/dsaf001/main.do?rcpNo={rcept_no}"
DOWNLOAD_PAGE_URL = BASE_URL + "/pdf/download/main.do?rcp_no={rcept_no}&dcm_no={dcm_no}"
HEADERS = {"User-Agent": "Mozilla/5.0 (research script)"}
REQUEST_DELAY = 1.0  # 웹 화면이라 OpenAPI보다 천천히 요청한다
MAX_RETRIES = 3

ATT_DIR = config.RAW_DART_DIR / "attachments"
LIST_PATH = ATT_DIR / "attachment_list.csv"
TEXT_PATH = config.PROCESSED_DIR / "disclosure_attachments.jsonl"

TARGET_NAME = "영업(잠정)실적"
ENGLISH_FILE = re.compile(r"ENG|English|영문", re.I)
HBM_PATTERN = re.compile(r"HBM", re.I)

# 웹 화면 HTML에서 첨부 목록과 파일 링크를 꺼내는 패턴
_ATT_SELECT = re.compile(r'<select id="att"[^>]*>(.*?)</select>', re.S)
_ATT_OPTION = re.compile(r'<option value="rcpNo=(\d+)&amp;dcmNo=(\d+)"[^>]*>(.*?)</option>', re.S)
_FILE_ROW = re.compile(
    r'<td class="tL">([^<]+)</td>\s*<td>\s*<a class="btnFile" href="(/pdf/download/file\.do\?[^"]+)"', re.S)
_SPACES = re.compile(r"\s+")


def is_target_disclosure(report_nm: str) -> bool:
    return TARGET_NAME in report_nm


def parse_attachment_options(page: str) -> list[tuple[str, str, str]]:
    """웹 화면(main.do)의 '첨부' 선택 상자에서 (첨부의 접수번호, dcm_no, 첨부 제목) 목록. 첨부가 없으면 빈 목록.

    [기재정정] 공시의 첨부는 정정 전 원래 공시(DB에 없는 접수번호)에 붙어 있다.
    예: 20241031800030 [기재정정] → 첨부는 20241008800067('24.3분기 잠정실적 설명 자료)
    """
    m = _ATT_SELECT.search(page)
    if not m:
        return []
    out = []
    for att_rcept_no, dcm_no, label in _ATT_OPTION.findall(m.group(1)):
        title = _SPACES.sub(" ", html.unescape(re.sub(r"<[^>]+>", "", label))).strip()
        out.append((att_rcept_no, dcm_no, title))
    return out


def parse_file_links(page: str) -> list[tuple[str, str]]:
    """첨부 다운로드 화면에서 (파일명, 다운로드 경로) 목록. 묶음 zip 링크는 빼고 개별 파일만."""
    return [(html.unescape(name).strip(), html.unescape(href)) for name, href in _FILE_ROW.findall(page)]


def select_file(file_name: str) -> tuple[bool, str]:
    """받을 파일인지와 그 이유. PDF이면서 국문인 것만 받는다."""
    if not file_name.lower().endswith(".pdf"):
        return False, "PDF아님"
    if ENGLISH_FILE.search(file_name):
        return False, "영문"
    return True, "국문PDF"


def local_name(rcept_no: str, dcm_no: str, file_name: str) -> str:
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", file_name)
    return f"{rcept_no}_{dcm_no}_{safe}"


def _get(session: requests.Session, url: str, referer: str | None = None) -> requests.Response:
    headers = {"Referer": referer} if referer else {}
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, headers=headers, timeout=60)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"네트워크 오류: {e}") from e
            time.sleep(REQUEST_DELAY * 2**attempt)
    raise AssertionError("unreachable")


def list_attachments(disclosures: pd.DataFrame, session: requests.Session, delay: float = REQUEST_DELAY) -> pd.DataFrame:
    """대상 공시마다 첨부와 그 안의 파일 목록을 모은다. 첨부가 없는 공시도 한 행(file_name 빈 값)으로 남긴다."""
    rows = []
    for rec in disclosures.itertuples(index=False):
        viewer = VIEWER_URL.format(rcept_no=rec.rcept_no)
        options = parse_attachment_options(_get(session, viewer).text)
        time.sleep(delay)
        base = {"rcept_no": rec.rcept_no, "corp_name": rec.corp_name, "report_nm": rec.report_nm, "rcept_dt": rec.rcept_dt}
        if not options:
            rows.append({**base, "att_rcept_no": "", "dcm_no": "", "att_title": "", "file_name": "", "file_url": "",
                         "selected": 0, "reason": "첨부없음"})
            continue
        for att_rcept_no, dcm_no, title in options:
            base_att = {**base, "att_rcept_no": att_rcept_no, "dcm_no": dcm_no, "att_title": title}
            page_url = DOWNLOAD_PAGE_URL.format(rcept_no=att_rcept_no, dcm_no=dcm_no)
            files = parse_file_links(_get(session, page_url, referer=viewer).text)
            time.sleep(delay)
            if not files:
                rows.append({**base_att, "file_name": "", "file_url": "", "selected": 0, "reason": "파일없음"})
            for name, href in files:
                selected, reason = select_file(name)
                rows.append({**base_att, "file_name": name, "file_url": BASE_URL + href,
                             "selected": int(selected), "reason": reason})
    return pd.DataFrame(rows)


def download_selected(listing: pd.DataFrame, session: requests.Session, att_dir: Path = ATT_DIR,
                      delay: float = REQUEST_DELAY) -> tuple[int, dict[str, str]]:
    """선택된 파일 중 아직 없는 것만 받는다. Returns (다운로드 수, {파일: 실패 사유})."""
    att_dir.mkdir(parents=True, exist_ok=True)
    calls, failures = 0, {}
    for r in listing[listing["selected"] == 1].itertuples(index=False):
        path = att_dir / local_name(r.rcept_no, r.dcm_no, r.file_name)
        if path.exists():
            continue
        referer = DOWNLOAD_PAGE_URL.format(rcept_no=r.att_rcept_no, dcm_no=r.dcm_no)
        calls += 1
        try:
            content = _get(session, r.file_url, referer=referer).content
            if not content.startswith(b"%PDF"):
                raise RuntimeError(f"PDF가 아닌 응답: {content[:80]!r}")
            path.write_bytes(content)
        except RuntimeError as e:
            failures[path.name] = str(e)[:200]
        time.sleep(delay)
    return calls, failures


def clean_page(text: str) -> str:
    """PDF 쪽 텍스트의 빈 줄과 줄 안 공백을 정리한다."""
    lines = [_SPACES.sub(" ", line).strip() for line in text.replace("\x00", "").split("\n")]
    return "\n".join(line for line in lines if line)


def extract_pdf(path: Path) -> list[str]:
    """PDF 쪽별 텍스트. 글자를 못 뽑은 쪽(이미지)은 빈 문자열."""
    from pypdf import PdfReader

    return [clean_page(page.extract_text() or "") for page in PdfReader(path).pages]


def extract_all(listing: pd.DataFrame, att_dir: Path = ATT_DIR) -> list[dict]:
    """받아 둔 선택 파일의 텍스트. 파일이 없으면 경고만 하고 건너뛴다."""
    records = []
    for r in listing[listing["selected"] == 1].sort_values(["rcept_dt", "rcept_no", "dcm_no"]).itertuples(index=False):
        path = att_dir / local_name(r.rcept_no, r.dcm_no, r.file_name)
        if not path.exists():
            print(f"경고: 파일 없음, 건너뜀 {path.name}")
            continue
        pages = extract_pdf(path)
        joined = "\n".join(pages)
        records.append({
            "rcept_no": r.rcept_no, "att_rcept_no": r.att_rcept_no, "dcm_no": r.dcm_no, "file_name": r.file_name,
            "n_pages": len(pages), "n_chars": len(joined), "n_hbm": len(HBM_PATTERN.findall(joined)),
            "pages": pages,
        })
    return records


def save_texts(records: list[dict], path: Path | None = None) -> None:
    path = path or TEXT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_texts(path: Path | None = None) -> list[dict]:
    """추출 텍스트. 파일이 없으면 빈 목록 (첨부를 아직 수집하지 않은 환경)."""
    path = path or TEXT_PATH
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def read_listing(path: Path | None = None) -> pd.DataFrame:
    return pd.read_csv(path or LIST_PATH, dtype=str, keep_default_na=False).astype({"selected": int})


def target_disclosures(db_path: Path = config.DB_PATH) -> pd.DataFrame:
    conn = db.connect(db_path)
    try:
        df = db.read_table(conn, "disclosure", columns=["rcept_no", "corp_name", "report_nm", "rcept_dt"])
    finally:
        conn.close()
    return df[df["report_nm"].map(is_target_disclosure)].sort_values(["rcept_dt", "rcept_no"])


def main(extract_only: bool = False, db_path: Path = config.DB_PATH) -> list[dict]:
    if not extract_only:
        targets = target_disclosures(db_path)
        if targets.empty:
            raise SystemExit("대상 공시가 없습니다. 먼저 python -m src.dart.collect_list를 실행하세요.")
        session = requests.Session()
        session.headers.update(HEADERS)
        print(f"대상 공시 {len(targets)}건 ('{TARGET_NAME}') 첨부 목록 확인 중...")
        listing = list_attachments(targets, session)
        ATT_DIR.mkdir(parents=True, exist_ok=True)
        listing.to_csv(LIST_PATH, index=False, encoding="utf-8-sig")
        print(listing.groupby(["corp_name", "reason"]).size().to_string())
        calls, failures = download_selected(listing, session)
        print(f"다운로드 {calls}건, 실패 {len(failures)}건")
        for name, msg in failures.items():
            print(f"  실패 {name}: {msg}")
    elif not LIST_PATH.exists():
        raise SystemExit(f"{LIST_PATH}가 없습니다. 공유 드라이브의 attachments 폴더를 받거나 --extract 없이 실행하세요.")

    listing = read_listing()
    records = extract_all(listing)
    save_texts(records)
    empty = [r["file_name"] for r in records if r["n_chars"] == 0]
    print(f"추출: 파일 {len(records)}개, {sum(r['n_pages'] for r in records)}쪽, "
          f"{sum(r['n_chars'] for r in records):,}자, HBM 언급 {sum(r['n_hbm'] for r in records)}회"
          + (f", 텍스트 없음 {len(empty)}개" if empty else ""))
    print(f"저장: {LIST_PATH}, {TEXT_PATH}")
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="실적 공시 첨부 경영설명회 PDF 수집·텍스트 추출")
    parser.add_argument("--extract", action="store_true", help="받아 둔 PDF에서 텍스트 추출만 (네트워크 불필요)")
    main(extract_only=parser.parse_args().extract)
