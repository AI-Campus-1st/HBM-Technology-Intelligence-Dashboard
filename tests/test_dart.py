"""
DART 수집·파싱 테스트.

담당: 한도윤 (공시 분석)
일정: Day 2~
"""

import zipfile

import pytest

from src.dart import corp_code

# 실제 corpCode.xml과 같은 구조의 작은 표본 (API 호출 없이 테스트)
SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<result>
  <list><corp_code>00164779</corp_code><corp_name>SK하이닉스</corp_name><stock_code>000660</stock_code><modify_date>20240101</modify_date></list>
  <list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name><stock_code>005930</stock_code><modify_date>20240101</modify_date></list>
  <list><corp_code>99999999</corp_code><corp_name>SK하이닉스시스템아이씨</corp_name><stock_code> </stock_code><modify_date>20240101</modify_date></list>
</result>
"""


@pytest.fixture
def corps(tmp_path):
    path = tmp_path / "CORPCODE.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("CORPCODE.xml", SAMPLE_XML)
    return corp_code.load_corp_list(path)


def test_load_corp_list(corps):
    assert len(corps) == 3
    assert corps[2]["stock_code"] == ""  # 비상장사는 공백 → 빈 문자열


def test_find_targets_returns_both_companies(corps):
    targets = {t["corp_name"]: t for t in corp_code.find_targets(corps)}
    assert targets["SK하이닉스"]["corp_code"] == "00164779"
    assert targets["SK하이닉스"]["role"] == "대상"
    assert targets["삼성전자"]["corp_code"] == "00126380"
    assert targets["삼성전자"]["role"] == "비교"


def test_find_corp_name_mismatch(corps):
    with pytest.raises(RuntimeError):
        corp_code.find_corp(corps, "다른회사", "000660")


def test_find_corp_missing_stock_code(corps):
    with pytest.raises(RuntimeError):
        corp_code.find_corp(corps, "LG전자", "066570")
