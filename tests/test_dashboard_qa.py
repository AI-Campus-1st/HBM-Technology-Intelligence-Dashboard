"""
대시보드 탭 2 (공시 Q&A) 테스트: 데이터 로더와 HTML 컴포넌트. API·Streamlit 서버 없이 확인한다.

담당: 한도윤 (공시 분석)
일정: Day 6
"""

import json
import sqlite3

import pandas as pd

from dashboard.components import qa_view
from dashboard.data_access import disclosure_loader as loader
from src.rag import qa_chain


def test_read_manifest_and_summary(tmp_path):
    assert loader.read_manifest(tmp_path / "none.json") is None and loader.read_eval_summary(tmp_path / "x.csv") == {}
    m = tmp_path / "manifest.json"
    m.write_text(json.dumps({"n_chunks": 2191, "n_disclosures": 101}), encoding="utf-8")
    assert loader.read_manifest(m)["n_chunks"] == 2191
    s = tmp_path / "summary.csv"
    pd.DataFrame({"지표": ["전체 정확"], "값": ["21/24"]}).to_csv(s, index=False, encoding="utf-8-sig")
    assert loader.read_eval_summary(s) == {"전체 정확": "21/24"}


def test_read_rag_disclosures_only_targets_newest_first(tmp_path):
    db = tmp_path / "t.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE disclosure (rcept_no, corp_name, report_nm, rcept_dt, pblntf_ty, url, rag_target)")
        conn.executemany("INSERT INTO disclosure VALUES (?,?,?,?,?,?,?)", [
            ("1", "SK하이닉스", "사업보고서", "2024-03-01", "A", "u1", 1),
            ("2", "삼성전자", "실적", "2025-01-01", "I", "u2", 1),
            ("3", "삼성전자", "임원 소유", "2025-02-01", "D", "u3", 0),
        ])
    df = loader.read_rag_disclosures(db)
    assert list(df["rcept_no"]) == ["2", "1"] and list(df["type_name"]) == ["거래소공시", "정기공시"]
    assert loader.read_rag_disclosures(tmp_path / "none.db").empty


def test_readiness_names_missing_parts_without_values():
    assert loader.readiness({"n_chunks": 1}, api_key="sk-secret") == []
    problems = loader.readiness(None, api_key="")
    assert len(problems) == 2 and all("sk-" not in p for p in problems)


def test_chunk_texts_dedupes_ids():
    class Store:
        def get(self, ids):
            self.ids = ids
            return {"ids": ids, "documents": [f"text-{i}" for i in ids]}

    store = Store()
    assert loader.chunk_texts(store, ["a", "b", "a"]) == {"a": "text-a", "b": "text-b"} and store.ids == ["a", "b"]
    assert loader.chunk_texts(store, []) == {}


def test_cite_html_escapes_and_marks_citations():
    out = qa_view.cite_html("매출 <70%> 증가 [1][12]")
    assert "&lt;70%&gt;" in out and out.count('class="qa-cite"') == 2


def test_excerpt_drops_header_and_trims():
    assert qa_view.excerpt("[SK | 실적 | 본문]\nHBM  매출\n증가") == "HBM 매출 증가"
    assert qa_view.excerpt("x" * 500, limit=10) == "x" * 10 + "…" and qa_view.excerpt(None) == ""


def test_answer_html_answer_and_refusal():
    ok = qa_chain.QAResult("q", "답 [1]", True, None, "SK하이닉스", 3)
    html = qa_view.answer_html(ok)
    assert "근거 기반 답변" in html and "refused" not in html and "기업 필터: SK하이닉스" in html
    no = qa_chain.QAResult("<q>", qa_chain.REFUSAL, False, "관련 공시 없음 (검색 거리 기준)", None, 0)
    html = qa_view.answer_html(no)
    assert "qa-answer refused" in html and "관련 공시 없음" in html and "&lt;q&gt;" in html and "없음 (전체)" in html


def test_source_html_has_link_location_and_excerpt():
    src = {"n": 1, "corp_name": "SK하이닉스", "report_nm": "실적", "rcept_dt": "2024-10-24",
           "location": "첨부 KOR.pdf p.5", "distance": 0.41, "url": "https://dart.fss.or.kr/x", "chunk_id": "c"}
    html = qa_view.source_html(src, "[머리말]\nHBM 매출 QoQ +70%")
    assert 'href="https://dart.fss.or.kr/x"' in html and "첨부 KOR.pdf p.5" in html and "거리 0.41" in html
    assert "HBM 매출 QoQ +70%" in html and "머리말" not in html


def test_disclosure_list_html():
    df = pd.DataFrame([{"rcept_no": "1", "corp_name": "삼성전자", "report_nm": "A&B", "rcept_dt": "2025-01-01",
                        "pblntf_ty": "I", "url": "u", "type_name": "거래소공시"}])
    html = qa_view.disclosure_list_html(df)
    assert "A&amp;B" in html and "거래소공시" in html and html.count('class="qa-row"') == 1
    assert "조건에 맞는 공시가 없습니다" in qa_view.disclosure_list_html(df.iloc[0:0])


def test_hero_and_stats_without_manifest():
    assert "-건" in qa_view.hero_html(None, "2026-10-19")
    html = qa_view.stats_html({"n_disclosures": 101, "n_attachment_chunks": 351}, {"전체 정확": "21/24"})
    assert "101" in html and "351" in html and "21/24" in html
