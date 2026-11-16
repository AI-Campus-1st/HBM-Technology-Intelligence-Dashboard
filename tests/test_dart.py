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


# ── collect_documents · parse_documents ──

from src.dart import collect_documents, parse_documents

DART_XML = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT><DOCUMENT-NAME>동일인등출자계열회사와의상품ㆍ용역거래변경</DOCUMENT-NAME>
<BODY><P>거래상대방 에스케이에코플랜트(주)</P>
<TABLE><TR><TD>FAB 건설</TD><TD>신규 FAB 구축</TD><TD>4,004,900</TD></TR></TABLE>
<P>&amp; 기타 사항은 이사회 의결에 따른다. 거래기간 2026년 4분기.</P></BODY></DOCUMENT>"""

HTML_DOC = """<html><head><style>.x { font-size: 10px; }</style></head>
<body><table><tr><td>특수관계인과의 보험거래</td><td>퇴직연금</td></tr></table>
<p>거래상대방 삼성생명보험 주식회사, 거래금액 15,000억원, 계약체결 방식은 수의계약이다.</p></body></html>"""


def write_zip(doc_dir, rcept_no, content, encoding="utf-8"):
    doc_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(doc_dir / f"{rcept_no}.zip", "w") as zf:
        zf.writestr(f"{rcept_no}.xml", content.encode(encoding))
        zf.writestr(f"{rcept_no}_00760.xml", "<P>첨부 감사보고서 FAB</P>")


@pytest.mark.parametrize("ty, name, expected", [
    ("A", "사업보고서 (2023.12)", True),
    ("J", "특수관계인과의내부거래", True),
    ("I", "신규시설투자등", True),
    ("I", "기타경영사항(자율공시)", True),
    ("I", "기타경영사항(자율공시) ((배당기준일 변경 안내))", False),
    ("I", "현금ㆍ현물배당결정", False),
    ("I", "최대주주등소유주식변동신고서", False),
])
def test_is_text_target(ty, name, expected):
    assert collect_documents.is_text_target(ty, name) is expected


def test_download_skips_existing_and_records_failures(tmp_path):
    (tmp_path / "r1.zip").write_bytes(b"PK old")
    calls = []

    def fetch(r):
        calls.append(r)
        if r == "r3":
            raise RuntimeError("zip이 아닌 응답: 014 파일이 존재하지 않습니다")
        return b"PK new"

    failures, n = collect_documents.download(["r1", "r2", "r3"], doc_dir=tmp_path, fetch=fetch, delay=0)
    assert calls == ["r2", "r3"] and n == 2
    assert list(failures) == ["r3"] and not (tmp_path / "r3.zip").exists()


def test_markup_to_text_handles_xml_and_html():
    xml_text = parse_documents.markup_to_text(DART_XML)
    assert "FAB 건설 | 신규 FAB 구축 | 4,004,900" in xml_text
    assert "& 기타 사항" in xml_text and "<" not in xml_text
    html_text = parse_documents.markup_to_text(HTML_DOC)
    assert "font-size" not in html_text and "퇴직연금" in html_text


def test_parse_one_reads_main_document_and_filters_j(tmp_path):
    write_zip(tmp_path, "j1", DART_XML)
    write_zip(tmp_path, "j2", HTML_DOC, encoding="cp949")  # EUC-KR 원문
    r1 = parse_documents.parse_one("j1", "J", tmp_path)
    r2 = parse_documents.parse_one("j2", "J", tmp_path)
    assert (r1["text_status"], r1["rag_target"], r1["filter_reason"]) == ("확보", 1, None)
    assert (r2["text_status"], r2["rag_target"], r2["filter_reason"]) == ("확보", 0, "J_본문키워드없음")
    assert "첨부" not in r1["text"]  # 첨부 문서는 읽지 않는다
    # 같은 본문이라도 J가 아니면 RAG 대상
    assert parse_documents.parse_one("j2", "A", tmp_path)["rag_target"] == 1
    # 키워드가 있어도 계열사 현황·부동산임대 공시는 공시명으로 뺀다
    r3 = parse_documents.parse_one("j1", "J", tmp_path, "대규모기업집단현황공시[분기별공시(개별회사용)]")
    assert (r3["rag_target"], r3["filter_reason"]) == (0, "J_공시명")


def test_parse_one_marks_failures(tmp_path):
    (tmp_path / "bad.zip").write_bytes(b"PK not a zip")
    assert parse_documents.parse_one("bad", "A", tmp_path)["text_status"] == "실패"
    write_zip(tmp_path, "short", "<P>짧음</P>")
    assert parse_documents.parse_one("short", "A", tmp_path)["filter_reason"] == "본문없음"


def test_parse_main_updates_db_and_is_repeatable(tmp_path, monkeypatch):
    monkeypatch.setattr(parse_documents, "SUMMARY_PATH", tmp_path / "summary.csv")
    doc_dir = tmp_path / "docs"
    write_zip(doc_dir, "a1", DART_XML)
    conn = db.connect(db.init_db(tmp_path / "t.db"))
    rows = [
        {"rcept_no": "a1", "pblntf_ty": "A", "report_nm": "사업보고서", "text_status": "대기"},
        {"rcept_no": "i1", "pblntf_ty": "I", "report_nm": "현금ㆍ현물배당결정", "text_status": "대상아님"},
        {"rcept_no": "b1", "pblntf_ty": "B", "report_nm": "주요사항보고서", "text_status": "대기"},  # zip 없음
    ]
    db.write_table(conn, "disclosure", [
        {**r, "corp_code": "00164779", "corp_name": "SK하이닉스", "rcept_dt": "2024-01-01", "url": "u"} for r in rows])
    conn.close()
    for _ in range(2):
        summary = parse_documents.main(db_path=tmp_path / "t.db", doc_dir=doc_dir)
    conn = db.connect(tmp_path / "t.db")
    status = dict(conn.execute("SELECT rcept_no, text_status FROM disclosure").fetchall())
    conn.close()
    assert status == {"a1": "확보", "i1": "대상아님", "b1": "대기"}
    total = summary[summary["pblntf_ty"] == "합계"].iloc[0]
    assert (total["확보"], total["대상아님"], total["대기"]) == (1, 1, 1)
