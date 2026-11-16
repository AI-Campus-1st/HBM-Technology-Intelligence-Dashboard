"""
공시서류원본파일 API(document.xml)로 원문 zip을 내려받아 data/raw/dart/documents에 저장한다.

원문 대상 (공시 범위, 리포트 2.3):
- A 정기공시, B 주요사항보고, D 위임장 참고서류, J 공정위공시: 전부
  (J는 공시명이 같아도 거래 상대에 따라 내용이 달라 본문을 받아야 거를 수 있다. RAG 대상 여부는 parse_documents가 정한다)
- I 거래소공시: 공시명 필터(I_INCLUDE)에 걸리는 것만. 나머지는 text_status='대상아님', filter_reason='I_공시명'

요청 간 딜레이, 원본 저장, 재실행 시 이미 받은 zip은 건너뛴다. 다운로드에 실패하면
text_status='실패', filter_reason='다운로드오류: <내용>'으로 기록하고 다음 공시로 넘어간다 (다시 실행하면 재시도).

실행: python -m src.dart.collect_documents          (collect_list 다음)
      python -m src.dart.collect_documents --limit 5 (앞의 5건만, 시험용)

담당: 한도윤 (공시 분석)
일정: Day 2
"""

import argparse
import time
from collections.abc import Callable
from pathlib import Path

import requests

from src.common import config, db

DOCUMENT_URL = "https://opendart.fss.or.kr/api/document.xml"
DOC_DIR = config.RAW_DART_DIR / "documents"
REQUEST_DELAY = 0.5
MAX_RETRIES = 3

FULL_TEXT_TYPES = ("A", "B", "D", "J")
# I 거래소공시 중 원문을 받는 공시명 (사업·투자 관련). 배당 안내는 이름이 걸려도 뺀다.
I_INCLUDE = (
    "신규시설투자", "단일판매ㆍ공급계약", "영업(잠정)실적", "장래사업ㆍ경영계획", "풍문", "조회공시",
    "타법인주식", "유형자산취득", "투자판단", "영업양수", "영업양도", "기타경영사항",
)
I_EXCLUDE = ("배당",)


def is_text_target(pblntf_ty: str, report_nm: str) -> bool:
    """원문을 받을 공시인지."""
    if pblntf_ty in FULL_TEXT_TYPES:
        return True
    if pblntf_ty == "I":
        return any(k in report_nm for k in I_INCLUDE) and not any(k in report_nm for k in I_EXCLUDE)
    return False


def zip_path(rcept_no: str, doc_dir: Path = DOC_DIR) -> Path:
    return doc_dir / f"{rcept_no}.zip"


def fetch_document(rcept_no: str) -> bytes:
    """원문 zip을 받는다. 정상 응답은 zip(PK로 시작)이고, 오류는 XML/JSON 메시지로 온다."""
    params = {"crtfc_key": config.require_env("DART_API_KEY"), "rcept_no": rcept_no}
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(DOCUMENT_URL, params=params, timeout=120)
            resp.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"네트워크 오류: {e}") from e
            time.sleep(REQUEST_DELAY * 2**attempt)
    if not resp.content.startswith(b"PK"):
        message = resp.content[:200].decode("utf-8", "replace").replace("\n", " ")
        # 한도 초과·키 오류는 다음 공시도 실패하므로 바로 멈춘다.
        if "020" in message or "010" in message or "011" in message:
            raise SystemExit(f"DART 오류로 중단합니다: {message}")
        raise RuntimeError(f"zip이 아닌 응답: {message}")
    return resp.content


def download(
    rcept_nos: list[str],
    doc_dir: Path = DOC_DIR,
    fetch: Callable[[str], bytes] = fetch_document,
    delay: float = REQUEST_DELAY,
) -> tuple[dict[str, str], int]:
    """zip이 없는 공시만 받는다. Returns ({rcept_no: 실패 사유}, API 호출 횟수)."""
    doc_dir.mkdir(parents=True, exist_ok=True)
    failures, calls = {}, 0
    for i, rcept_no in enumerate(rcept_nos, 1):
        path = zip_path(rcept_no, doc_dir)
        if path.exists():
            continue
        calls += 1
        try:
            path.write_bytes(fetch(rcept_no))
        except RuntimeError as e:
            failures[rcept_no] = str(e)[:200]
        time.sleep(delay)
        if calls % 50 == 0:
            print(f"  {i}/{len(rcept_nos)} 처리, 다운로드 {calls}건")
    return failures, calls


def main(limit: int | None = None, db_path: Path = config.DB_PATH) -> None:
    conn = db.connect(db_path)
    try:
        df = db.read_table(conn, "disclosure", columns=["rcept_no", "pblntf_ty", "report_nm", "text_status"])
        if df.empty:
            raise SystemExit("disclosure가 비어 있습니다. 먼저 python -m src.dart.collect_list를 실행하세요.")
        df["target"] = [is_text_target(t, n) for t, n in zip(df["pblntf_ty"], df["report_nm"])]

        with conn:
            conn.executemany(
                "UPDATE disclosure SET text_status='대상아님', filter_reason='I_공시명', text=NULL, rag_target=0 "
                "WHERE rcept_no=?",
                [(r,) for r in df.loc[~df["target"], "rcept_no"]],
            )

        targets = df.loc[df["target"], "rcept_no"].tolist()
        if limit:
            targets = targets[:limit]
        print(f"원문 대상 {int(df['target'].sum())}건 / 목록 {len(df)}건 (대상아님 {int((~df['target']).sum())}건)")
        failures, calls = download(targets)

        with conn:
            # 이번에 실패한 공시는 실패로, 이전에 실패했다가 이번에 받은 공시는 다시 대기로 돌린다.
            conn.executemany(
                "UPDATE disclosure SET text_status='실패', filter_reason=?, text=NULL, rag_target=0 WHERE rcept_no=?",
                [(f"다운로드오류: {msg}", r) for r, msg in failures.items()],
            )
            conn.executemany(
                "UPDATE disclosure SET text_status='대기', filter_reason=NULL "
                "WHERE rcept_no=? AND text_status='실패' AND filter_reason LIKE '다운로드오류%'",
                [(r,) for r in targets if r not in failures and zip_path(r).exists()],
            )
    finally:
        conn.close()

    have = sum(zip_path(r).exists() for r in targets)
    print(f"API 호출 {calls}회, zip 보유 {have}/{len(targets)}건, 실패 {len(failures)}건")
    for r, msg in list(failures.items())[:10]:
        print(f"  실패 {r}: {msg}")
    print(f"저장: {DOC_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DART 공시 원문 zip 다운로드")
    parser.add_argument("--limit", type=int, help="앞의 N건만 받는다 (시험용)")
    main(limit=parser.parse_args().limit)
