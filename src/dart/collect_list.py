"""
공시검색(list.json)으로 공시 목록을 수집한다. 요청 간 딜레이, 응답 원본 저장, 재실행 가능(이미 받은 건 건너뛰기).
수집 기간: 2023-10-19 ~ 2026-10-19 (bgn_de=20231019, end_de=20261019). 값은 config.DART_BGN_DE·DART_END_DE를 쓴다.

공시 범위 (2026-11-16 확정, 리포트 2.3):
- A 정기공시, B 주요사항보고, I 거래소공시, J 공정위공시: 목록 전체
- D 지분공시: 의결권대리행사권유참고서류만 (나머지 소유상황·대량보유 보고서는 목록에도 넣지 않는다)
- C 발행공시, E 기타공시: 수집하지 않는다
- 정정공시는 최종본만 (last_reprt_at=Y)
원문을 받을지(I 공시명 필터, J 본문 필터)는 collect_documents·parse_documents가 정한다. 여기서는 모두 text_status='대기'로 넣는다.

실행: python -m src.dart.collect_list            (저장된 응답이 있으면 API를 다시 부르지 않음)
      python -m src.dart.collect_list --refresh  (응답을 새로 받음)

저장:
- data/raw/dart/list/<bgn_de>_<end_de>/<corp_code>/<유형>_p<페이지>.json : list.json 응답 원본
- DB disclosure 테이블 : 목록 (이미 있는 공시의 본문·원문 상태는 유지)
- outputs/reports/disclosure_list_summary.csv : 기업·유형별 건수 (리포트 2.3용)

담당: 한도윤 (공시 분석)
일정: Day 2
"""

import argparse
import json
import time
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import requests

from src.common import config, db, schema
from src.dart.corp_code import load_target_corps

LIST_URL = "https://opendart.fss.or.kr/api/list.json"
VIEWER_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
RAW_LIST_DIR = config.RAW_DART_DIR / "list" / f"{config.DART_BGN_DE}_{config.DART_END_DE}"
SUMMARY_PATH = config.OUTPUTS_DIR / "reports" / "disclosure_list_summary.csv"

PAGE_COUNT = 100  # list.json 최대값
REQUEST_DELAY = 0.5  # 초. DART 일일 한도(2만 건)와 서버 부하를 고려
MAX_RETRIES = 3

# D 지분공시 중 수집할 공시명 (원문 표본 17건 중 10건에 HBM 등 사업 내용, 리포트 2.3)
D_INCLUDE = ("의결권대리행사권유참고서류",)

# 원문 처리 단계에서 채우는 컬럼. 목록을 다시 수집해도 이 값은 유지한다.
TEXT_COLUMNS = ("text", "text_status", "rag_target", "filter_reason")

STATUS_OK = "000"
STATUS_NO_DATA = "013"


def fetch_page(corp_code: str, pblntf_ty: str, page_no: int) -> dict:
    """list.json 한 페이지를 요청해 JSON을 돌려준다. 네트워크 오류는 MAX_RETRIES번까지 다시 시도한다."""
    params = {
        "crtfc_key": config.require_env("DART_API_KEY"),
        "corp_code": corp_code,
        "bgn_de": config.DART_BGN_DE,
        "end_de": config.DART_END_DE,
        "pblntf_ty": pblntf_ty,
        "last_reprt_at": "Y",
        "page_no": page_no,
        "page_count": PAGE_COUNT,
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(LIST_URL, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as e:
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"list.json 요청 실패 ({corp_code}, {pblntf_ty}, p{page_no}): {e}") from e
            time.sleep(REQUEST_DELAY * 2**attempt)
    raise AssertionError("unreachable")


def check_status(data: dict, where: str) -> bool:
    """정상이면 True, 해당 공시 없음이면 False. 그 밖의 상태(키 오류·한도 초과 등)는 멈춘다."""
    status = data.get("status")
    if status == STATUS_OK:
        return True
    if status == STATUS_NO_DATA:
        return False
    raise RuntimeError(f"DART 오류 {status} ({where}): {data.get('message')}")


def collect_pages(
    corp_code: str,
    pblntf_ty: str,
    raw_dir: Path = RAW_LIST_DIR,
    refresh: bool = False,
    fetch: Callable[[str, str, int], dict] = fetch_page,
) -> tuple[list[dict], int]:
    """한 기업·한 유형의 모든 페이지를 모은다. 저장된 응답이 있으면 쓰고, 없을 때만 API를 부른다.

    Returns:
        (페이지 응답 목록, API 호출 횟수)
    """
    out_dir = raw_dir / corp_code
    out_dir.mkdir(parents=True, exist_ok=True)
    pages, calls, page_no, total_page = [], 0, 1, 1
    while page_no <= total_page:
        path = out_dir / f"{pblntf_ty}_p{page_no:03d}.json"
        if path.exists() and not refresh:
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = fetch(corp_code, pblntf_ty, page_no)
            calls += 1
            check_status(data, f"{corp_code} {pblntf_ty} p{page_no}")  # 오류 응답은 저장하지 않는다
            path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            time.sleep(REQUEST_DELAY)
        pages.append(data)
        if not check_status(data, f"{corp_code} {pblntf_ty} p{page_no}"):
            break
        total_page = int(data.get("total_page") or 1)
        page_no += 1
    return pages, calls


def keep_item(pblntf_ty: str, report_nm: str) -> bool:
    """공시 범위 필터. D는 정해진 공시명만, 나머지 수집 유형은 전부."""
    if pblntf_ty == "D":
        return any(name in report_nm for name in D_INCLUDE)
    return pblntf_ty in schema.DISCLOSURE_TYPES


def pages_to_rows(pages: list[dict], pblntf_ty: str) -> tuple[list[dict], int]:
    """페이지 응답을 disclosure 행으로 바꾼다. Returns (행 목록, 범위 밖이라 뺀 건수)."""
    rows, dropped = [], 0
    for data in pages:
        for item in data.get("list", []):
            report_nm = " ".join(item["report_nm"].split())  # 응답 끝의 공백·줄바꿈 정리
            if not keep_item(pblntf_ty, report_nm):
                dropped += 1
                continue
            d = item["rcept_dt"]
            rows.append({
                "rcept_no": item["rcept_no"],
                "corp_code": item["corp_code"],
                "corp_name": item["corp_name"],
                "report_nm": report_nm,
                "rcept_dt": f"{d[:4]}-{d[4:6]}-{d[6:8]}",
                "pblntf_ty": pblntf_ty,
                "url": VIEWER_URL.format(rcept_no=item["rcept_no"]),
            })
    return rows, dropped


def merge_with_existing(new: pd.DataFrame, existing: pd.DataFrame) -> pd.DataFrame:
    """새 목록에 기존 DB의 원문 처리 결과(TEXT_COLUMNS)를 붙인다. 새 공시는 대기 상태로 둔다."""
    if existing.empty:
        merged = new.copy()
    else:
        merged = new.merge(existing[["rcept_no", *TEXT_COLUMNS]], on="rcept_no", how="left")
    for col in TEXT_COLUMNS:
        if col not in merged:
            merged[col] = None
    merged["text_status"] = merged["text_status"].fillna("대기")
    merged["rag_target"] = merged["rag_target"].fillna(0).astype(int)
    return merged


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    """기업·유형별 건수 표."""
    if df.empty:
        return pd.DataFrame(columns=["corp_name", "pblntf_ty", "count"])
    out = df.groupby(["corp_name", "pblntf_ty"]).size().rename("count").reset_index()
    return out.sort_values(["corp_name", "pblntf_ty"]).reset_index(drop=True)


def main(refresh: bool = False, db_path: Path = config.DB_PATH) -> pd.DataFrame:
    corps = load_target_corps()
    print(f"수집 기간: {config.DART_BGN_DE} ~ {config.DART_END_DE}, 유형: {', '.join(schema.DISCLOSURE_TYPES)} (D는 {D_INCLUDE[0]}만)")

    rows, total_calls, total_dropped = [], 0, 0
    for corp in corps:
        for ty in schema.DISCLOSURE_TYPES:
            pages, calls = collect_pages(corp["corp_code"], ty, refresh=refresh)
            got, dropped = pages_to_rows(pages, ty)
            rows += got
            total_calls += calls
            total_dropped += dropped
            print(f"  {corp['corp_name']} {ty}: {len(got)}건" + (f" (범위 밖 {dropped}건 제외)" if dropped else ""))

    new = pd.DataFrame(rows)
    dup = int(new.duplicated("rcept_no").sum()) if not new.empty else 0
    if dup:
        print(f"  같은 접수번호가 여러 유형에 나온 {dup}건은 처음 유형만 남김")
        new = new.drop_duplicates("rcept_no", keep="first")

    conn = db.connect(db_path)
    try:
        schema.create_all(conn)
        existing = db.read_table(conn, "disclosure")
        merged = merge_with_existing(new, existing)
        db.write_table(conn, "disclosure", merged, mode="replace")
    finally:
        conn.close()

    summary = summarize(merged)
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(SUMMARY_PATH, index=False, encoding="utf-8-sig")

    print(f"API 호출 {total_calls}회 (나머지는 저장된 응답 사용), 범위 밖 제외 {total_dropped}건")
    print(f"disclosure 적재: {len(merged):,}건 (기존 원문 상태 유지 {int((merged['text_status'] != '대기').sum())}건)")
    print(summary.pivot(index="pblntf_ty", columns="corp_name", values="count").fillna(0).astype(int).to_string())
    print(f"저장: {RAW_LIST_DIR}, {SUMMARY_PATH}")
    return merged


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DART list.json으로 대상 기업 공시 목록 수집")
    parser.add_argument("--refresh", action="store_true", help="저장된 응답을 무시하고 새로 받는다")
    main(refresh=parser.parse_args().refresh)
