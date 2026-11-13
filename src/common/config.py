"""
환경변수(.env) 로딩과 프로젝트 경로 상수(DATA_DIR, DB_PATH, VECTORDB_DIR 등)를 정의한다.
API 키는 반드시 os.getenv로 읽고 코드에 직접 쓰지 않는다.

분석 기간·기준일·대상 기업도 여기서 한 번만 정의하고, 뉴스·공시 코드가 모두 이 값을 가져다 쓴다.
근거: docs/guidelines/초안_v1.1.md §4.1 (분석 기간), 대상 기업 SK하이닉스 / 비교 삼성전자

담당: 공동 (변경 시 PR로 합의)
일정: Day 1
"""

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

# ── 경로 ──
ROOT_DIR = Path(__file__).resolve().parents[2]

DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
RAW_NEWS_DIR = RAW_DIR / "news"
RAW_DART_DIR = RAW_DIR / "dart"
PROCESSED_DIR = DATA_DIR / "processed"
DB_DIR = DATA_DIR / "db"
DB_PATH = DB_DIR / "hbm.db"
VECTORDB_DIR = DATA_DIR / "vectordb"
LABELS_DIR = DATA_DIR / "labels"
OUTPUTS_DIR = ROOT_DIR / "outputs"

# ── 환경변수 (.env) ──
# 이미 설정된 환경변수가 있으면 덮어쓰지 않는다.
load_dotenv(ROOT_DIR / ".env")

DART_API_KEY = os.getenv("DART_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


def require_env(name: str) -> str:
    """필수 환경변수를 읽는다. 비어 있으면 어떤 키가 없는지 알려주고 멈춘다 (값은 출력하지 않는다)."""
    value = os.getenv(name, "")
    if not value:
        raise RuntimeError(f"환경변수 {name}가 비어 있습니다. .env.example을 복사해 .env에 값을 채우세요.")
    return value


# ── 분석 기간·기준일 (뉴스·공시 공통) ──
# 완결된 15개 분기(2023Q1 ~ 2026Q3). 2021~2022년은 기사가 희소하고 2026Q4는 16일분만 있어 제외한다.
# 가이드 권장 3년(2023-10 ~ 2026-10)과 다르며, 사유는 리포트에 적는다. (초안_v1.1 §4.1)
ANALYSIS_START = date(2023, 1, 1)
ANALYSIS_END = date(2026, 9, 30)  # 이 날짜 포함

# 기준일: "언제 시점의 데이터인가". 리포트·대시보드에 '기준일'로 표시한다.
REFERENCE_DATE = ANALYSIS_END

# 날짜 형식 (docs/schema.md 공통 규칙)
DATE_FORMAT = "%Y-%m-%d"  # DB·화면 표시용
DART_DATE_FORMAT = "%Y%m%d"  # DART API 파라미터(bgn_de, end_de)용

DART_BGN_DE = ANALYSIS_START.strftime(DART_DATE_FORMAT)
DART_END_DE = ANALYSIS_END.strftime(DART_DATE_FORMAT)

# ── 대상 기업 ──
# 이름만으로 찾으면 비슷한 이름이 섞일 수 있어 종목코드로 확인한다.
# corp_code는 src/dart/corp_code.py 실행 결과로 확정한다.
TARGET_COMPANIES = {
    "SK하이닉스": {"stock_code": "000660", "role": "대상"},
    "삼성전자": {"stock_code": "005930", "role": "비교"},
}
PRIMARY_CORP_NAME = "SK하이닉스"


if __name__ == "__main__":
    print(f"ROOT_DIR       : {ROOT_DIR}")
    print(f"분석 기간      : {ANALYSIS_START:{DATE_FORMAT}} ~ {ANALYSIS_END:{DATE_FORMAT}}")
    print(f"기준일         : {REFERENCE_DATE:{DATE_FORMAT}}")
    print(f"DART 파라미터  : bgn_de={DART_BGN_DE}, end_de={DART_END_DE}")
    for name, info in TARGET_COMPANIES.items():
        print(f"기업({info['role']})     : {name} ({info['stock_code']})")
    print(f"DART_API_KEY   : {'설정됨' if DART_API_KEY else '없음'}")
    print(f"OPENAI_API_KEY : {'설정됨' if OPENAI_API_KEY else '없음'}")
