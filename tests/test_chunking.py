"""
공시 청킹(src/rag/chunking.py) 테스트. 작은 표본 텍스트로 확인한다 (임베딩·API 호출 없음).

담당: 한도윤 (공시 분석)
일정: Day 3
"""

import pandas as pd
import pytest

from src.common import db
from src.rag import chunking

# 정기보고서 모양: 목차 → 'II. 사업의 내용' 소제목 7개 → III → 상세표(삼성전자 연구개발실적)
REPORT = "\n".join([
    "II. 사업의 내용", "III. 재무에 관한 사항",  # 목차
    "II. 사업의 내용",
    "1. 사업의 개요", "당사는 메모리 반도체와 시스템 반도체를 만드는 회사입니다.",
    "2. 주요 제품 및 서비스", "HBM3E 12단 제품을 양산하여 AI 서버 고객에게 공급하고 있습니다.",
    "3. 원재료 및 생산설비", "생산설비 현황은 다음과 같습니다. 평택과 화성 사업장에 라인이 있습니다.",
    "4. 매출 및 수주상황", "매출 표는 청크에 넣지 않는다 매출 표는 청크에 넣지 않는다",
    "5. 위험관리 및 파생거래", "환율 위험 관리 내용은 청크에 넣지 않는다 환율 위험",
    "6. 주요계약 및 연구개발활동", "2. 연구개발비용", "(단위: 백만원)",
    "연구개발비용 합계", "6,732,527", "4,954,447",
    "7. 기타 참고사항", "업계의 현황: AI 수요로 고대역폭 메모리 시장이 커지고 있습니다.",
    "III. 재무에 관한 사항", "재무제표 본문은 청크에 넣지 않는다",
    "XII. 상세표", "4. 연구개발실적(상세)", "☞ 본문 위치로 이동",
    "DX 부문", "□ 마이크로 LED TV 개발 내용은 DS가 아니라서 빠진다",
    "DS 부문", "메모리", "□ 업계 최초 HBM4 샘플 출하와 12단 적층 기술 확보",
    "SDC", "□ 디스플레이 패널 개발 내용은 빠진다",
    "1. 전문가의 확인", "해당 없음",
])

INVEST = "\n".join([
    "신규 시설투자 등", "1. 투자구분", "시설증설", "- 투자대상", "청주 M15X 건설",
    "2. 투자내역", "투자금액(원)", "5,296,200,000,000",
    "3. 투자목적", "선제적인 반도체 수요 대응을 위한 차세대 DRAM 생산능력 확장",
])


def disclosure_rows():
    base = {"corp_code": "00126380", "corp_name": "삼성전자", "url": "https://dart.fss.or.kr/x"}
    return [
        {**base, "rcept_no": "a1", "report_nm": "사업보고서 (2025.12)", "rcept_dt": "2026-03-10",
         "pblntf_ty": "A", "text": REPORT},
        {**base, "rcept_no": "i1", "report_nm": "신규시설투자등", "rcept_dt": "2024-04-24",
         "pblntf_ty": "I", "text": INVEST},
    ]


@pytest.fixture
def chunks():
    return chunking.chunk_disclosures(pd.DataFrame(disclosure_rows()))


def test_join_table_cells_keeps_subheadings_and_long_lines():
    text = "가. 주요 계약\n과 목\n제78기\n6,732,527\n2. 연구개발비용\n" + "긴 문장 " * 10 + "\n합 계\n30,173"
    assert chunking.join_table_cells(text).split("\n") == [
        "가. 주요 계약", "과 목 | 제78기 | 6,732,527", "2. 연구개발비용", ("긴 문장 " * 10).strip(), "합 계 | 30,173",
    ]


def test_ds_only_keeps_ds_part():
    detail = "DX 부문\nTV\nDS 부문\nHBM4\nSDC\n패널"
    assert chunking.ds_only(detail) == "DS 부문\nHBM4"
    assert chunking.ds_only("DS 없음") == "DS 없음"  # DS 줄이 없으면 그대로


def test_periodic_report_uses_tagged_sections_only(chunks):
    a = [c for c in chunks if c["rcept_no"] == "a1"]
    sections = [c["section"] for c in a]
    assert sections == ["사업의 개요", "주요 제품 및 서비스", "원재료 및 생산설비",
                        "주요계약 및 연구개발활동", "기타 참고사항", "연구개발실적(상세)"]
    text = "\n".join(c["text"] for c in a)
    for excluded in ("매출 표", "환율", "재무제표 본문", "마이크로 LED", "디스플레이 패널"):
        assert excluded not in text
    rnd = next(c for c in a if c["section"] == "주요계약 및 연구개발활동")
    assert "연구개발비용 합계 | 6,732,527 | 4,954,447" in rnd["text"]  # 항목과 값이 같은 줄
    assert rnd["section_type"] == "연구개발"


def test_chunk_metadata_and_header(chunks):
    inv = next(c for c in chunks if c["rcept_no"] == "i1")
    assert inv["chunk_id"] == "i1_00_000"
    assert (inv["section"], inv["section_type"], inv["pblntf_ty"]) == ("본문", "투자·설비", "I")
    assert inv["text"].startswith("[삼성전자 | 신규시설투자등 | 제출일 2024-04-24 | 본문]\n")
    assert inv["n_chars"] == len(inv["text"].split("\n", 1)[1])  # 머리말 제외 글자 수
    hbm = {c["section"]: c["has_hbm"] for c in chunks if c["rcept_no"] == "a1"}
    assert hbm["주요 제품 및 서비스"] and hbm["기타 참고사항"] and not hbm["사업의 개요"]  # 고대역폭도 HBM


def test_long_text_is_split_with_overlap_and_stable_ids():
    long_text = "\n".join(f"{i}번째 문장은 HBM 패키징 투자와 연구개발에 관한 설명을 담고 있습니다." for i in range(200))
    df = pd.DataFrame([{**disclosure_rows()[1], "text": long_text}])
    first = chunking.chunk_disclosures(df)
    assert len(first) > 1 and all(c["n_chars"] <= chunking.CHUNK_SIZE for c in first)
    assert first[0]["text"].split("\n")[-1] in first[1]["text"]  # 겹침: 앞 청크 마지막 줄이 다음 청크에도 있다
    assert [c["chunk_id"] for c in chunking.chunk_disclosures(df)] == [c["chunk_id"] for c in first]


def test_main_reads_only_rag_targets_and_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(chunking, "CHUNKS_PATH", tmp_path / "chunks.jsonl")
    monkeypatch.setattr(chunking, "SUMMARY_PATH", tmp_path / "summary.csv")
    conn = db.connect(db.init_db(tmp_path / "t.db"))
    rows = disclosure_rows() + [
        {**disclosure_rows()[1], "rcept_no": "j1", "pblntf_ty": "J", "report_nm": "특수관계인과의내부거래"},
    ]
    status = {"a1": ("확보", 1), "i1": ("확보", 1), "j1": ("확보", 0)}  # j1은 RAG 대상 아님
    db.write_table(conn, "disclosure", [
        {**r, "text_status": status[r["rcept_no"]][0], "rag_target": status[r["rcept_no"]][1]} for r in rows])
    conn.close()

    chunks = chunking.main(db_path=tmp_path / "t.db")
    assert {c["rcept_no"] for c in chunks} == {"a1", "i1"}
    assert chunking.load_chunks(tmp_path / "chunks.jsonl") == chunks
    docs = chunking.to_documents(chunks)
    assert docs[0].id == chunks[0]["chunk_id"] and "text" not in docs[0].metadata
    assert docs[0].metadata["url"] == "https://dart.fss.or.kr/x"
    summary = pd.read_csv(tmp_path / "summary.csv")
    assert summary["n_chunks"].sum() == len(chunks)


# ── 첨부 경영설명회 자료 (collect_attachments 결과) ──

ATTACHMENT = {
    "rcept_no": "i1", "att_rcept_no": "i1", "dcm_no": "100", "file_name": "3Q24_Earnings Presentation_KOR.pdf",
    "n_pages": 3, "n_chars": 0, "n_hbm": 1,
    "pages": ["실적발표", "이익 분석\nHBM\n매출 QoQ +70% 이상, YoY +330% 이상\n고부가가치제품 판매 확대", ""],
}


def test_attachment_pages_become_separate_chunks():
    df = pd.DataFrame(disclosure_rows())
    other = {**ATTACHMENT, "rcept_no": "zz"}  # 대상 공시가 아닌 첨부는 쓰지 않는다
    chunks = chunking.chunk_disclosures(df, attachments=[ATTACHMENT, other])
    att = [c for c in chunks if c["section"] == chunking.ATTACHMENT_SECTION]
    assert [c["chunk_id"] for c in att] == ["i1_a1p02_000"]  # 1쪽(표지, 30자 미만)·3쪽(빈 쪽)은 버린다
    c = att[0]
    assert (c["page"], c["file_name"], c["section_type"]) == (2, ATTACHMENT["file_name"], "IR자료")
    assert c["text"].startswith(
        "[삼성전자 | 신규시설투자등 | 제출일 2024-04-24 | 첨부 3Q24_Earnings Presentation_KOR.pdf p.2]\n")
    assert "HBM | 매출 QoQ +70% 이상, YoY +330% 이상" in c["text"] and c["has_hbm"]
    body = next(c for c in chunks if c["chunk_id"] == "i1_00_000")
    assert (body["page"], body["file_name"]) == (0, "")  # 본문 청크 (Chroma 메타데이터에 None을 넣지 않는다)


def test_main_uses_attachment_texts_of_rag_targets(tmp_path, monkeypatch):
    from src.dart import collect_attachments

    monkeypatch.setattr(chunking, "CHUNKS_PATH", tmp_path / "chunks.jsonl")
    monkeypatch.setattr(chunking, "SUMMARY_PATH", tmp_path / "summary.csv")
    monkeypatch.setattr(collect_attachments, "TEXT_PATH", tmp_path / "att.jsonl")
    collect_attachments.save_texts([ATTACHMENT])
    conn = db.connect(db.init_db(tmp_path / "t.db"))
    db.write_table(conn, "disclosure", [{**r, "text_status": "확보", "rag_target": 1} for r in disclosure_rows()])
    conn.close()

    chunks = chunking.main(db_path=tmp_path / "t.db")
    assert "i1_a1p02_000" in {c["chunk_id"] for c in chunks}
    doc = next(d for d in chunking.to_documents(chunks) if d.id == "i1_a1p02_000")
    assert doc.metadata["page"] == 2
