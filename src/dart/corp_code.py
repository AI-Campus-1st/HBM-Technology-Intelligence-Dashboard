"""
corpCode.xml을 내려받아 대상 기업(SK하이닉스·삼성전자)의 corp_code를 찾는다. 결과는 data/raw/dart/corp_code에 저장.

실행: python -m src.dart.corp_code          (이미 받은 zip이 있으면 재사용)
      python -m src.dart.corp_code --refresh (zip을 새로 받음)

저장 파일 (data/raw/dart/corp_code/):
- CORPCODE.zip       : DART 응답 원본 (재실행 시 API를 다시 부르지 않기 위해 보관)
- target_corps.json  : 대상 기업별 corp_code, corp_name, stock_code, modify_date, role

담당: 한도윤 (공시 분석)
일정: Day 1~2
"""

import argparse
import io
import json
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from src.common import config

CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
OUT_DIR = config.RAW_DART_DIR / "corp_code"
ZIP_PATH = OUT_DIR / "CORPCODE.zip"
TARGET_PATH = OUT_DIR / "target_corps.json"


def download_zip(path: Path = ZIP_PATH) -> Path:
    """corpCode.xml(zip)을 내려받아 원본 그대로 저장한다."""
    api_key = config.require_env("DART_API_KEY")
    resp = requests.get(CORP_CODE_URL, params={"crtfc_key": api_key}, timeout=60)
    resp.raise_for_status()

    # 정상 응답은 zip(PK로 시작). 키 오류 등은 zip 대신 XML/JSON 에러 메시지가 온다.
    if not resp.content.startswith(b"PK"):
        raise RuntimeError(f"DART 응답이 zip이 아닙니다: {resp.content[:300].decode('utf-8', 'replace')}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(resp.content)
    return path


def load_corp_list(path: Path = ZIP_PATH) -> list[dict]:
    """zip 안의 CORPCODE.xml을 읽어 [{corp_code, corp_name, stock_code, modify_date}, ...]로 돌려준다."""
    with zipfile.ZipFile(path) as zf:
        xml_name = next(n for n in zf.namelist() if n.lower().endswith(".xml"))
        root = ET.parse(io.BytesIO(zf.read(xml_name))).getroot()

    return [
        {
            "corp_code": (item.findtext("corp_code") or "").strip(),
            "corp_name": (item.findtext("corp_name") or "").strip(),
            "stock_code": (item.findtext("stock_code") or "").strip(),
            "modify_date": (item.findtext("modify_date") or "").strip(),
        }
        for item in root.iter("list")
    ]


def find_corp(corps: list[dict], corp_name: str, stock_code: str) -> dict:
    """종목코드로 기업을 찾고, 회사명이 기대와 같은지 확인한다. (이름만으로 찾으면 비슷한 이름이 섞인다)"""
    matches = [c for c in corps if c["stock_code"] == stock_code]
    if len(matches) != 1:
        raise RuntimeError(f"종목코드 {stock_code}에 해당하는 기업이 {len(matches)}개입니다: {matches}")

    corp = matches[0]
    if corp["corp_name"] != corp_name:
        raise RuntimeError(f"종목코드 {stock_code}의 회사명이 '{corp['corp_name']}'로, 기대한 '{corp_name}'와 다릅니다.")
    return corp


def find_targets(corps: list[dict], targets: dict = config.TARGET_COMPANIES) -> list[dict]:
    """config.TARGET_COMPANIES의 모든 기업을 찾아 role(대상/비교)을 붙여 돌려준다."""
    return [
        {**find_corp(corps, name, info["stock_code"]), "role": info["role"]}
        for name, info in targets.items()
    ]


def main(refresh: bool = False) -> list[dict]:
    if refresh or not ZIP_PATH.exists():
        print("corpCode.xml 다운로드 중...")
        download_zip()
    else:
        print(f"저장된 zip 재사용: {ZIP_PATH}")

    corps = load_corp_list()
    targets = find_targets(corps)

    TARGET_PATH.write_text(json.dumps(targets, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"전체 기업 수: {len(corps):,}")
    for t in targets:
        print(f"[{t['role']}] {t['corp_name']} / corp_code={t['corp_code']} / stock_code={t['stock_code']}")
    print(f"저장: {TARGET_PATH}")
    return targets


def load_target_corps() -> list[dict]:
    """다른 스크립트(collect_list.py 등)에서 저장된 대상 기업 목록을 읽을 때 쓴다."""
    if not TARGET_PATH.exists():
        raise FileNotFoundError("target_corps.json이 없습니다. 먼저 python -m src.dart.corp_code를 실행하세요.")
    return json.loads(TARGET_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DART corpCode.xml에서 대상 기업 corp_code 찾기")
    parser.add_argument("--refresh", action="store_true", help="저장된 zip을 무시하고 새로 내려받는다")
    main(refresh=parser.parse_args().refresh)
