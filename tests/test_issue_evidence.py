"""
급증 구간 근거 후보(src/dart/issue_evidence.py) 테스트. 작은 표와 임시 DB로 확인한다.

담당: 공동 (공시 근거 부분 한도윤)
일정: Day 3
"""

import pandas as pd
import pytest

from src.common import db
from src.dart import issue_evidence as ie
from src.eda import disclosure_trend

ISSUES = pd.DataFrame([
    {"issue_id": "HBM-2024-12", "start_date": "2024-12-01", "end_date": "2025-01-31"},
])


def links(rows):
    """rows: (news_id, published_at, rcept_no, report_nm, topic, days, relevance)"""
    df = pd.DataFrame(rows, columns=["news_id", "published_at", "rcept_no", "report_nm", "topic",
                                     "days_from_article", "relevance"])
    df["category"] = df["report_nm"].map(disclosure_trend.categorize)
    return df


def test_keyword_one_row_per_disclosure_with_core_representative():
    df = links([
        ("n1", "2024-12-20", "D1", "투자판단관련주요경영사항", "설비투자", 0, "관련"),
        ("n2", "2024-12-22", "D1", "투자판단관련주요경영사항", "설비투자", -2, "핵심"),
        ("n3", "2024-12-21", "D1", "투자판단관련주요경영사항", "설비투자", -1, "핵심"),
        ("n9", "2024-11-25", "D9", "신규시설투자등", "설비투자", 0, "핵심"),  # 구간 밖 기사
    ])
    out = ie.keyword_candidates(ISSUES, df)
    assert out["rcept_no"].tolist() == ["D1"]
    assert out.iloc[0]["news_id"] == "n3"  # 핵심 중 공시와 가장 가까운 기사
    assert "기사 3건(핵심 2)" in out.iloc[0]["auto_note"]


def test_scope_core_needs_core_article_and_broad_keeps_disclosure_types():
    df = links([
        ("n1", "2024-12-20", "D1", "풍문또는보도에대한해명(미확정)", "설비투자", 1, "관련"),
        ("n2", "2024-12-20", "D2", "동일인등출자계열회사와의상품ㆍ용역거래", "설비투자", 1, "관련"),
        ("n3", "2025-01-31", "D3", "연결재무제표기준영업(잠정)실적(공정공시)", "실적", 0, "핵심"),
    ])
    assert ie.keyword_candidates(ISSUES, df, "broad")["rcept_no"].tolist() == ["D1", "D3"]
    assert ie.keyword_candidates(ISSUES, df, "core")["rcept_no"].tolist() == ["D3"]
    with pytest.raises(ValueError):
        ie.keyword_candidates(ISSUES, df, "all")


def test_period_candidates_include_lead_days_and_skip_keyword_ones():
    disc = disclosure_trend.prepare(pd.DataFrame([
        ("D0", "SK하이닉스", "신규시설투자등", "2024-11-23", "I", "u"),       # 시작 8일 전 → 제외
        ("D1", "SK하이닉스", "신규시설투자등", "2024-11-24", "I", "u"),       # 시작 7일 전 → 포함
        ("D2", "SK하이닉스", "투자판단관련주요경영사항", "2024-12-20", "I", "u"),  # 키워드 후보 → 제외
        ("D3", "SK하이닉스", "현금ㆍ현물배당결정", "2025-01-10", "I", "u"),     # 사건성 아님
        ("D4", "삼성전자", "풍문또는보도에대한해명(미확정)", "2025-01-31", "I", "u"),
    ], columns=["rcept_no", "corp_name", "report_nm", "rcept_dt", "pblntf_ty", "url"]))
    keyword = pd.DataFrame([{"issue_id": "HBM-2024-12", "rcept_no": "D2"}])
    out = ie.period_candidates(ISSUES, disc, keyword)
    assert out["rcept_no"].tolist() == ["D1", "D4"]
    assert out["news_id"].isna().all() and (out["match_type"] == "기간").all()
    assert "구간 시작 전" in out.iloc[0]["auto_note"]


def candidates():
    return ie._key_frame(pd.DataFrame([
        {"issue_id": "I1", "rcept_no": "D1", "news_id": "n1", "match_type": "키워드", "auto_note": "a"},
        {"issue_id": "I1", "rcept_no": "D2", "news_id": None, "match_type": "기간", "auto_note": "b"},
    ]))


def test_merge_review_keeps_labels_and_manual_rows_drops_stale_blanks():
    review = ie._key_frame(pd.DataFrame([
        {"issue_id": "I1", "rcept_no": "D1", "news_id": "n1", "match_type": "키워드", "verified": "1", "note": "확인", "reviewer": "한도윤"},
        {"issue_id": "I1", "rcept_no": "D8", "news_id": None, "match_type": "기간", "verified": None, "note": None, "reviewer": None},
        {"issue_id": "I1", "rcept_no": "D9", "news_id": None, "match_type": "기간", "verified": "0", "note": None, "reviewer": "김한승"},
        {"issue_id": "I1", "rcept_no": None, "news_id": "n7", "match_type": "수동", "verified": "1", "note": "대표 기사", "reviewer": "김한승"},
    ]))
    merged = ie.merge_review(candidates(), review)
    assert set(merged["rcept_no"].fillna("-")) == {"D1", "D2", "D9", "-"}  # 후보 아닌 빈 행 D8만 빠짐
    assert merged.set_index("rcept_no").loc["D1", "verified"] == "1"


def test_evidence_rows_apply_labels_and_number_ids():
    review = ie.merge_review(candidates(), ie._key_frame(pd.DataFrame([
        {"issue_id": "I1", "rcept_no": "D1", "news_id": "n1", "match_type": "키워드", "verified": "1", "note": "확인", "reviewer": "x"},
        {"issue_id": "I1", "rcept_no": "D2", "news_id": None, "match_type": "기간", "verified": "0", "note": None, "reviewer": "x"},
        {"issue_id": "I1", "rcept_no": None, "news_id": "n7", "match_type": "수동", "verified": "1", "note": None, "reviewer": "x"},
    ])))
    out = ie.evidence_rows(candidates(), review)
    assert out["evidence_id"].tolist() == [1, 2, 3]
    assert out["match_type"].tolist() == ["키워드", "기간", "수동"]
    assert out["verified"].tolist() == [1, 0, 1]
    assert out.iloc[0]["note"] == "a | 확인" and out.iloc[1]["note"] == "b | 기각"


def test_main_writes_db_and_review_file_reproducibly(tmp_path):
    path = tmp_path / "t.db"
    conn = db.connect(db.init_db(path))
    db.write_table(conn, "issues", pd.DataFrame([{
        "issue_id": "HBM-2024-12", "tech_tag": "HBM", "start_date": "2024-12-01", "end_date": "2025-01-31",
        "peak_date": "2024-12-01", "peak_share": 0.2, "baseline_share": 0.04, "article_count": 10, "method": "m"}]))
    db.write_table(conn, "news", pd.DataFrame([{
        "news_id": "n1", "published_at": "2024-12-20", "title": "SK하이닉스 인디애나 HBM 공장 투자",
        "content": "SK하이닉스가 인디애나 공장에 투자한다. HBM", "url": "u", "is_duplicate": 0}]))
    db.write_table(conn, "news_tag", pd.DataFrame([
        {"news_id": "n1", "tag_type": "tech", "tag": "HBM", "relevance": "핵심", "in_title": 1, "body_count": 1, "rule_version": "x"},
        {"news_id": "n1", "tag_type": "company", "tag": "SK하이닉스", "relevance": "핵심", "in_title": 1, "body_count": 1, "rule_version": "x"},
    ]))
    db.write_table(conn, "disclosure", pd.DataFrame([
        {"rcept_no": "D1", "corp_code": "c", "corp_name": "SK하이닉스", "report_nm": "신규시설투자등",
         "rcept_dt": "2024-12-19", "pblntf_ty": "I", "url": "u1", "text": "인디애나 공장", "text_status": "확보"},
        {"rcept_no": "D2", "corp_code": "c", "corp_name": "SK하이닉스", "report_nm": "풍문또는보도에대한해명(미확정)",
         "rcept_dt": "2025-01-20", "pblntf_ty": "I", "url": "u2", "text": "증시 상장 검토", "text_status": "확보"},
    ]))
    conn.close()
    review_path = tmp_path / "review.csv"
    kwargs = dict(db_path=path, review_path=review_path, candidates_path=tmp_path / "cand.csv")

    table = ie.main(**kwargs)
    assert table[["rcept_no", "match_type"]].values.tolist() == [["D1", "키워드"], ["D2", "기간"]]
    assert table.iloc[0]["news_id"] == "n1" and pd.isna(table.iloc[1]["news_id"])
    review = pd.read_csv(review_path, dtype=str, keep_default_na=False)
    assert review["report_nm"].tolist() == ["신규시설투자등", "풍문또는보도에대한해명(미확정)"]

    review.loc[0, "verified"] = "1"
    review.to_csv(review_path, index=False, encoding="utf-8-sig")
    ie.main(**kwargs)
    conn = db.connect(path)
    rows = db.read_table(conn, "issue_evidence")
    conn.close()
    assert rows["verified"].tolist() == [1, 0]
    assert pd.read_csv(review_path, dtype=str, keep_default_na=False)["verified"].tolist() == ["1", ""]
    assert ie.clear(path) == 2
    assert review_path.exists()  # 라벨 파일은 그대로
