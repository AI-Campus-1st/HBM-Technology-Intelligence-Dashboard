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


# ── collect_list (API 호출 없이 가짜 응답으로) ──

import json as _json

import pandas as pd

from src.common import db
from src.dart import collect_list


def fake_item(rcept_no, report_nm, corp_code="00164779", corp_name="SK하이닉스", rcept_dt="20240424"):
    return {"corp_code": corp_code, "corp_name": corp_name, "report_nm": report_nm + "   ",
            "rcept_no": rcept_no, "rcept_dt": rcept_dt}


def make_fetch(responses):
    """{(유형, 페이지): 응답}을 돌려주는 가짜 fetch. 호출 기록을 남긴다."""
    calls = []

    def fetch(corp_code, ty, page):
        calls.append((corp_code, ty, page))
        return responses.get((ty, page), {"status": "013", "message": "조회된 데이타가 없습니다."})

    return fetch, calls


def test_collect_pages_follows_pages_and_reuses_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(collect_list, "REQUEST_DELAY", 0)
    fetch, calls = make_fetch({
        ("A", 1): {"status": "000", "total_page": 2, "list": [fake_item("r1", "사업보고서 (2023.12)")]},
        ("A", 2): {"status": "000", "total_page": 2, "list": [fake_item("r2", "분기보고서 (2024.03)")]},
    })
    pages, n = collect_list.collect_pages("00164779", "A", raw_dir=tmp_path, fetch=fetch)
    assert n == 2 and len(pages) == 2
    pages, n = collect_list.collect_pages("00164779", "A", raw_dir=tmp_path, fetch=fetch)
    assert n == 0 and len(calls) == 2  # 두 번째 실행은 저장된 응답만 사용


def test_collect_pages_no_data_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(collect_list, "REQUEST_DELAY", 0)
    fetch, _ = make_fetch({})
    pages, _ = collect_list.collect_pages("00126380", "B", raw_dir=tmp_path, fetch=fetch)
    rows, _ = collect_list.pages_to_rows(pages, "B")
    assert rows == []


def test_collect_pages_stops_on_api_error_without_saving(tmp_path, monkeypatch):
    monkeypatch.setattr(collect_list, "REQUEST_DELAY", 0)
    fetch, _ = make_fetch({("A", 1): {"status": "020", "message": "요청 제한을 초과하였습니다."}})
    with pytest.raises(RuntimeError, match="020"):
        collect_list.collect_pages("00164779", "A", raw_dir=tmp_path, fetch=fetch)
    assert not list(tmp_path.rglob("*.json"))


def test_pages_to_rows_filters_d_and_formats():
    pages = [{"status": "000", "list": [
        fake_item("d1", "의결권대리행사권유참고서류"),
        fake_item("d2", "임원ㆍ주요주주특정증권등소유상황보고서"),
        fake_item("d3", "[기재정정]의결권대리행사권유참고서류"),
    ]}]
    rows, dropped = collect_list.pages_to_rows(pages, "D")
    assert [r["rcept_no"] for r in rows] == ["d1", "d3"] and dropped == 1
    assert rows[0]["rcept_dt"] == "2024-04-24"
    assert rows[0]["report_nm"] == "의결권대리행사권유참고서류"
    assert rows[0]["url"].endswith("rcpNo=d1")


def test_merge_keeps_text_results(tmp_path):
    new = pd.DataFrame(collect_list.pages_to_rows(
        [{"status": "000", "list": [fake_item("r1", "사업보고서"), fake_item("r2", "반기보고서")]}], "A")[0])
    first = collect_list.merge_with_existing(new, pd.DataFrame())
    assert first["text_status"].tolist() == ["대기", "대기"]

    conn = db.connect(db.init_db(tmp_path / "t.db"))
    db.write_table(conn, "disclosure", first)
    conn.execute("UPDATE disclosure SET text='본문', text_status='확보', rag_target=1 WHERE rcept_no='r1'")
    conn.commit()
    again = collect_list.merge_with_existing(new, db.read_table(conn, "disclosure"))
    db.write_table(conn, "disclosure", again)
    row = db.read_table(conn, "disclosure", where="rcept_no = 'r1'").iloc[0]
    assert (row["text"], row["text_status"], row["rag_target"]) == ("본문", "확보", 1)
    conn.close()
