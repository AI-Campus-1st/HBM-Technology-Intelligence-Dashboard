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


def test_month_options_cover_analysis_period():
    months = loader.month_options()
    assert months[0] == "2023-10" and months[-1] == "2026-10" and len(months) == 37


def test_filter_disclosures_by_period_company_type():
    df = pd.DataFrame({
        "rcept_no": ["1", "2", "3", "4"],
        "corp_name": ["SK하이닉스", "삼성전자", "삼성전자", "SK하이닉스"],
        "rcept_dt": ["2023-10-26", "2024-10-31", "2024-11-01", "2026-10-06"],
        "type_name": ["정기공시", "거래소공시", "정기공시", "거래소공시"],
    })
    ids = lambda d: list(d["rcept_no"])  # noqa: E731
    assert ids(loader.filter_disclosures(df)) == ["1", "2", "3", "4"]  # 필터 없음 = 전부
    assert ids(loader.filter_disclosures(df, "2023-10", "2026-10", "전체", [])) == ["1", "2", "3", "4"]
    assert ids(loader.filter_disclosures(df, "2024-10", "2024-10")) == ["2"]  # 월 단위, 양 끝 포함
    assert ids(loader.filter_disclosures(df, "2024-10", "2024-11", "삼성전자", ["정기공시"])) == ["3"]
    assert loader.filter_disclosures(df, "2025-01", "2025-06").empty


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


def test_read_saved_answers_maps_question_to_result_and_texts(tmp_path):
    src = {"n": 1, "corp_name": "SK하이닉스", "report_nm": "실적", "rcept_dt": "2024-10-24", "url": "u",
           "location": "본문", "distance": 0.4, "chunk_id": "c1"}
    r = qa_chain.QAResult("q1", "답 [1]", True, None, "SK하이닉스", 6, [src])
    path = tmp_path / "s.json"
    qa_chain.save_samples_json([r], {"c1": "근거 본문"}, path)
    saved = loader.read_saved_answers(path)
    assert saved["answers"]["q1"] == (r, {"c1": "근거 본문"}) and saved["created_at"]
    assert loader.read_saved_answers(tmp_path / "none.json") is None


def test_saved_answers_file_covers_sample_questions():
    saved = loader.read_saved_answers()
    assert saved is not None, "outputs/reports/qa_samples.json이 없습니다: python -m src.rag.qa_chain --samples"
    assert set(saved["answers"]) == {q for q, _ in qa_chain.SAMPLE_QUESTIONS}
    expected = dict(qa_chain.SAMPLE_QUESTIONS)
    for q, (r, texts) in saved["answers"].items():
        assert ("답변" if r.answerable else "거절") == expected[q]
        assert all(texts.get(s["chunk_id"]) for s in r.sources)  # 발췌 본문까지 저장돼 있다


def test_answer_html_shows_saved_note():
    r = qa_chain.QAResult("q", "답", True, None, None, 1)
    assert 'qa-badge saved">저장된 답변 · 2026-11-18 생성' in qa_view.answer_html(r, "저장된 답변 · 2026-11-18 생성")
    assert "saved" not in qa_view.answer_html(r)


def test_common_theme_shared_by_pages_and_config():
    from pathlib import Path

    from dashboard.components import theme
    root = Path(__file__).resolve().parents[1]
    # 공통 CSS는 theme에, 탭 2 전용 CSS(.qa-*)는 qa_view에만 있다
    assert "--bg: #121212" in theme.THEME_CSS and ".qa-" not in theme.THEME_CSS
    assert ".qa-hero" in qa_view.QA_CSS and ":root" not in qa_view.QA_CSS
    # 공용 config.toml도 같은 색이다
    cfg = (root / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    assert 'base = "dark"' in cfg and theme.COLORS["bg"] in cfg and theme.GREEN in cfg
    # 모든 페이지가 공통 테마를 부른다
    pages = [root / "dashboard" / "app.py", *sorted((root / "dashboard" / "pages").glob("*.py"))]
    for page in pages:
        assert "apply_theme()" in page.read_text(encoding="utf-8"), page.name


def test_app_opens_summary_first_and_registers_every_page():
    """첫 화면은 요약이고, pages/의 모든 파일이 메뉴에 등록돼 있다. 요약 카드 링크의 url_path도 app.py와 같다."""
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from dashboard.components import summary as sm

    root = Path(__file__).resolve().parents[1]
    src = (root / "dashboard" / "app.py").read_text(encoding="utf-8")
    for page in (root / "dashboard" / "pages").glob("*.py"):
        assert f'"pages/{page.name}"' in src, page.name
    assert 'st.Page("pages/0_요약.py", title="요약", icon="🧭", default=True)' in src
    assert src.count("default=True") == 1
    assert f'url_path="{sm.ISSUE_PAGE}"' in src and f'url_path="{sm.QA_PAGE}"' in src

    at = AppTest.from_file(str(root / "dashboard" / "app.py"), default_timeout=60).run()
    assert not at.exception
    # 첫 화면은 요약이다 (DB가 없는 환경이면 요약의 DB 안내가 뜬다)
    shown = [m.value for m in at.markdown] + [e.value for e in at.error]
    assert any(sm.QUESTION in s or "README 실행 순서" in s for s in shown)