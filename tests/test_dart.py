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


@pytest.fixture
def section_outputs(tmp_path, monkeypatch):
    """섹션 추출 결과를 실제 data/·outputs/ 대신 임시 폴더에 쓴다."""
    for name in ("SUMMARY_PATH", "SECTIONS_PATH", "SECTION_SUMMARY_PATH", "RND_CAPEX_PATH"):
        monkeypatch.setattr(parse_documents, name, tmp_path / "out" / f"{name.lower()}.csv")
    return tmp_path / "out"


def test_parse_main_updates_db_and_is_repeatable(tmp_path, section_outputs):
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


# ── relevance_review (공시 관련성 표본 검수) ──

from src.dart import relevance_review


def fake_disclosures():
    rows = []
    for i in range(30):
        rows.append({"rcept_no": f"b{i:02d}", "corp_name": "SK하이닉스", "report_nm": "주요사항보고서(자기주식처분결정)",
                     "rcept_dt": "2024-01-01", "pblntf_ty": "B", "url": "u", "text": "자기주식 처분 임직원 보상",
                     "text_status": "확보", "rag_target": 1, "filter_reason": None})
    rows.append({"rcept_no": "a01", "corp_name": "SK하이닉스", "report_nm": "사업보고서", "rcept_dt": "2024-03-01",
                 "pblntf_ty": "A", "url": "u", "text": "당사는 HBM3E 양산을 시작했다. HBM 매출 증가",
                 "text_status": "확보", "rag_target": 1, "filter_reason": None})
    rows.append({"rcept_no": "i01", "corp_name": "삼성전자", "report_nm": "현금ㆍ현물배당결정", "rcept_dt": "2024-01-31",
                 "pblntf_ty": "I", "url": "u", "text": None, "text_status": "대상아님", "rag_target": 0,
                 "filter_reason": "I_공시명"})
    return pd.DataFrame(rows)


def test_build_sample_is_stratified_and_repeatable():
    strata = {("A", "RAG대상"): None, ("B", "RAG대상"): 20, ("I", "제외"): 15}
    s1 = relevance_review.build_sample(fake_disclosures(), strata)
    s2 = relevance_review.build_sample(fake_disclosures().sample(frac=1, random_state=1), strata)
    assert s1["rcept_no"].tolist() == s2["rcept_no"].tolist()  # 입력 순서가 달라도 같은 표본
    counts = s1.groupby(["pblntf_ty", "stratum"]).size().to_dict()
    assert counts == {("A", "RAG대상"): 1, ("B", "RAG대상"): 20, ("I", "제외"): 1}
    a = s1[s1["rcept_no"] == "a01"].iloc[0]
    assert a["hbm_count"] == 2 and "HBM3E" in a["context"]
    assert "원문 미수집" in s1[s1["rcept_no"] == "i01"].iloc[0]["context"]
    assert list(s1.columns) == relevance_review.REVIEW_COLUMNS


def test_relevance_table_counts_levels():
    labels = pd.DataFrame({
        "pblntf_ty": ["A", "A", "B", "B", "B", "I"],
        "stratum": ["RAG대상", "RAG대상", "RAG대상", "RAG대상", "RAG대상", "제외"],
        "label": [2, 1, 0, 0, None, 1],
    })
    t = relevance_review.relevance_table(labels).set_index(["pblntf_ty", "stratum"])
    assert t.loc[("A", "RAG대상"), "relevant_rate"] == 1.0
    assert t.loc[("A", "RAG대상"), "n_direct"] == 1
    assert t.loc[("B", "RAG대상"), "n_labeled"] == 2 and t.loc[("B", "RAG대상"), "relevant_rate"] == 0.0
    assert t.loc[("I", "제외"), "meaning"] == "놓친 비율"


def test_relevance_table_rejects_bad_label():
    with pytest.raises(ValueError):
        relevance_review.relevance_table(pd.DataFrame({"pblntf_ty": ["A"], "stratum": ["RAG대상"], "label": [3]}))


def test_sample_main_does_not_overwrite_labels(tmp_path):
    path = tmp_path / "review.csv"
    path.write_text("labels", encoding="utf-8")
    with pytest.raises(SystemExit):
        relevance_review.sample_main(path=path, db_path=tmp_path / "none.db")
    assert path.read_text(encoding="utf-8") == "labels"


# ── news_link (HBM 기사 ↔ 공시 연결, 새 RAG 기준) ──

from src.dart import news_link


@pytest.mark.parametrize("ty, name, text, expected", [
    ("A", "사업보고서 (2024.12)", "공장 증설 실적 HBM", set()),          # 긴 문서는 연결하지 않음
    ("D", "의결권대리행사권유참고서류", "공장 투자", set()),
    ("J", "동일인등출자계열회사와의상품ㆍ용역거래변경", "FAB 건설 신규 FAB 구축 4,004,900", {"설비투자"}),
    ("J", "동일인등출자계열회사와의상품ㆍ용역거래", "Wafer 구매 FAB 운영지원", set()),
    ("J", "대규모기업집단현황공시[분기별공시(대표회사용)]", "건설 FAB 설계", set()),
    ("I", "신규시설투자등", "청주 M15X 건설", {"설비투자"}),
    ("I", "연결재무제표기준영업(잠정)실적(공정공시)", "매출액", {"실적"}),
    ("I", "기타경영사항(자율공시)", "스마트공장 지원사업 대외후원금 출연", set()),
    ("I", "풍문또는보도에대한해명(미확정)", "美 신규 어드밴스드 패키징 공장 건설 관련 보도", {"설비투자"}),
    ("I", "풍문또는보도에대한해명(미확정)", "자사주 90조 매입 공장", set()),
    ("B", "주요사항보고서(유상증자결정)", "자금조달의 목적 - 시설자금", {"설비투자"}),
    ("B", "주요사항보고서(유상증자결정)", "운영자금", set()),
    ("B", "주요사항보고서(자기주식처분결정)", "임직원 보상 공장", set()),
])
def test_disclosure_topics(ty, name, text, expected):
    assert news_link.disclosure_topics(ty, name, text) == expected


def make_link_inputs():
    articles = pd.DataFrame([
        {"news_id": "n1", "published_at": "2024-04-20", "title": "SK하이닉스, 청주 M15X에 HBM 라인 증설",
         "content": "HBM", "companies": ("SK하이닉스",)},
        {"news_id": "n2", "published_at": "2024-04-20", "title": "삼성전자 HBM 엔비디아 퀄 테스트",
         "content": None, "companies": ("삼성전자",)},
    ])
    base = {"corp_code": "x", "url": "u", "text_status": "확보", "rag_target": 1}
    disclosures = pd.DataFrame([
        {**base, "rcept_no": "i1", "corp_name": "SK하이닉스", "report_nm": "신규시설투자등", "rcept_dt": "2024-04-24",
         "pblntf_ty": "I", "text": "청주 M15X 건설"},
        {**base, "rcept_no": "i2", "corp_name": "SK하이닉스", "report_nm": "신규시설투자등", "rcept_dt": "2024-07-01",
         "pblntf_ty": "I", "text": "증설"},                                       # 날짜가 멀다
        {**base, "rcept_no": "i3", "corp_name": "삼성전자", "report_nm": "신규시설투자등", "rcept_dt": "2024-04-24",
         "pblntf_ty": "I", "text": "평택 증설"},                                  # n2는 설비투자 주제가 아님
        {**base, "rcept_no": "b1", "corp_name": "SK하이닉스", "report_nm": "주요사항보고서(자기주식처분결정)",
         "rcept_dt": "2024-04-24", "pblntf_ty": "B", "text": "임직원 보상"},
        {**base, "rcept_no": "a1", "corp_name": "삼성전자", "report_nm": "사업보고서", "rcept_dt": "2024-03-12",
         "pblntf_ty": "A", "text": "HBM 매출"},
        {**base, "rcept_no": "d1", "corp_name": "삼성전자", "report_nm": "의결권대리행사권유참고서류",
         "rcept_dt": "2024-02-26", "pblntf_ty": "D", "text": "HBM3E 양산"},
        {**base, "rcept_no": "i4", "corp_name": "SK하이닉스", "report_nm": "유형자산취득결정", "rcept_dt": "2024-04-25",
         "pblntf_ty": "I", "text": None, "text_status": "대상아님", "rag_target": 0},  # 연결되지만 원문 없음
    ])
    return articles, disclosures


def test_link_requires_company_window_and_topic():
    articles, disclosures = make_link_inputs()
    links = news_link.link(articles, disclosures, window_days=30)
    assert set(zip(links["news_id"], links["rcept_no"])) == {("n1", "i1"), ("n1", "i4")}
    assert (links[links["rcept_no"] == "i1"]["days_from_article"] == 4).all()


def test_new_rag_target_keeps_a_hbm_and_linked_only():
    articles, disclosures = make_link_inputs()
    res = news_link.new_rag_target(disclosures, news_link.link(articles, disclosures)).set_index("rcept_no")
    assert res["new_rag_target"].to_dict() == {"i1": 1, "i2": 0, "i3": 0, "b1": 0, "a1": 1, "d1": 1, "i4": 0}
    assert res.loc["i4", "needs_text"] == 1                    # 연결됐지만 원문이 없어 RAG 불가
    assert res.loc["b1", "new_reason"].startswith(news_link.LINK_VERSION)
    assert res.loc["i4", "new_reason"] is None                 # 대상아님 공시의 기록은 건드리지 않는다


def test_hbm_articles_falls_back_to_tagging_when_news_tag_empty(tmp_path):
    conn = db.connect(db.init_db(tmp_path / "t.db"))
    db.write_table(conn, "news", [
        {"news_id": "n1", "published_at": "2024-04-20", "title": "SK하이닉스 HBM 증설", "content": "본문",
         "url": "u1", "is_duplicate": 0},
        {"news_id": "n2", "published_at": "2024-04-20", "title": "반도체 수출 통제", "content": "HBM 한 번",
         "url": "u2", "is_duplicate": 0},                      # HBM 언급 등급 → 제외
        {"news_id": "n3", "published_at": "2024-04-20", "title": "SK하이닉스 HBM 증설", "content": "본문",
         "url": "u3", "is_duplicate": 1},                      # 중복 기사 → 제외
    ])
    art, source = news_link.hbm_articles(conn)
    conn.close()
    assert art["news_id"].tolist() == ["n1"] and art.loc[0, "companies"] == ("SK하이닉스",)
    assert "즉석 계산" in source
