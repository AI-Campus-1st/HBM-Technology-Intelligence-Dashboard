"""
LLM 감성 분류 표본 검수(src/llm/validate_sample.py) 테스트.

담당: 김한승 (이슈 분석)
일정: Day 4
"""

import pandas as pd
import pytest

from src.common import db
from src.llm import prompts
from src.llm import validate_sample as vs


def analysis_frame(n_per=(30, 30, 20, 20)):
    """분기 2개 × 기업 그룹 4종 표 (LLM 결과 포함)."""
    groups = [("긍정", "해당없음"), ("해당없음", "부정"), ("중립", "긍정"), ("해당없음", "해당없음")]
    rows, k = [], 0
    for (skh, sec), n in zip(groups, n_per):
        for j in range(n):
            month = "2024-02" if j % 2 else "2024-05"
            rows.append({"news_id": f"n{k:03d}", "published_at": f"{month}-10", "title": f"t{k}",
                         "content": "본문" * 400, "sentiment_skh": skh, "sentiment_sec": sec})
            k += 1
    return pd.DataFrame(rows)


# ── 표본 추출 ──
def test_allocate_is_proportional_and_sums_to_n():
    out = vs.allocate(pd.Series({"a": 50, "b": 30, "c": 20}), 10)
    assert out.to_dict() == {"a": 5, "b": 3, "c": 2}
    out = vs.allocate(pd.Series({"a": 2, "b": 98}), 10)  # 층 크기를 넘지 않는다
    assert out.sum() == 10 and out["a"] <= 2


def test_allocate_when_n_exceeds_population():
    assert vs.allocate(pd.Series({"a": 3, "b": 2}), 100).to_dict() == {"a": 3, "b": 2}


def test_company_group():
    assert vs.company_group("긍정", "해당없음") == "SK만"
    assert vs.company_group("해당없음", "중립") == "삼성만"
    assert vs.company_group("부정", "긍정") == "둘 다"
    assert vs.company_group("해당없음", "해당없음") == "둘 다 해당없음"


def test_build_sample_is_stratified_blind_and_reproducible():
    df = analysis_frame()
    a = vs.build_sample(df, n=20, seed=1)
    b = vs.build_sample(df, n=20, seed=1)
    assert len(a) == 20 and a["news_id"].is_unique
    assert a["news_id"].tolist() == b["news_id"].tolist()  # 같은 seed → 같은 표본
    assert list(a.columns) == vs.REVIEW_COLUMNS
    assert "sentiment_skh" not in a.columns  # LLM 판정은 숨긴다 (사람이 독립 판정)
    assert a["human_skh"].isna().all()
    # 층(분기 × 기업 그룹)별 비례 배분: 그룹 비율 30:30:20:20 → 6:6:4:4
    groups = a["stratum"].str.split(" \\| ").str[1].value_counts().to_dict()
    assert groups == {"SK만": 6, "삼성만": 6, "둘 다": 4, "둘 다 해당없음": 4}
    assert a["head"].str.len().max() <= vs.HEAD_CHARS


# ── 지표 ──
def test_metrics_basic():
    y = ["긍정", "긍정", "부정", "중립"]
    p = ["긍정", "부정", "부정", "중립"]
    rep = vs.class_report(y, p).set_index("label")
    assert rep.loc["긍정", "precision"] == 1.0 and rep.loc["긍정", "recall"] == 0.5
    assert rep.loc["부정", "precision"] == 0.5 and rep.loc["부정", "recall"] == 1.0
    assert "해당없음" not in rep.index  # 정답·예측 어디에도 없는 라벨은 빼고 평균
    assert vs.macro_f1(y, p) == pytest.approx((2 / 3 + 2 / 3 + 1.0) / 3)
    cm = vs.confusion(y, p)
    assert cm.loc["긍정", "부정"] == 1 and cm.values.sum() == 4


def test_cohen_kappa():
    assert vs.cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == pytest.approx(1.0)
    assert vs.cohen_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]) == pytest.approx(0.0)
    assert vs.cohen_kappa(["a", "a"], ["a", "a"]) == pytest.approx(1.0)  # 한 라벨뿐이면 완전 일치 = 1


def test_score_table_with_cross_check():
    review = pd.DataFrame({
        "news_id": ["n1", "n2", "n3", "n4"],
        "human_skh": ["긍정", "중립", "해당없음", None],   # n4는 미라벨 → 제외
        "human_sec": ["해당없음", "부정", "긍정", None],
        "cross_skh": ["긍정", "긍정", None, None],          # 교차 검수 2건
        "cross_sec": ["해당없음", "부정", None, None],
    })
    llm = pd.DataFrame({"news_id": ["n1", "n2", "n3", "n4"],
                        "sentiment_skh": ["긍정", "중립", "중립", "긍정"],
                        "sentiment_sec": ["해당없음", "중립", "긍정", "긍정"]})
    table = vs.score_table(review, llm).set_index("company")
    assert table.loc["SK하이닉스", "n"] == 3 and table.loc["SK하이닉스", "accuracy"] == pytest.approx(2 / 3)
    assert table.loc["삼성전자", "accuracy"] == pytest.approx(2 / 3)
    assert table.loc["SK하이닉스", "n_cross"] == 2 and table.loc["SK하이닉스", "cross_agreement"] == pytest.approx(0.5)
    assert 0 <= table.loc["SK하이닉스", "ci_low"] <= table.loc["SK하이닉스", "accuracy"] <= table.loc["SK하이닉스", "ci_high"]


def test_score_rejects_invalid_label():
    review = pd.DataFrame({"news_id": ["n1"], "human_skh": ["좋음"], "human_sec": ["중립"],
                           "cross_skh": [None], "cross_sec": [None]})
    llm = pd.DataFrame({"news_id": ["n1"], "sentiment_skh": ["긍정"], "sentiment_sec": ["중립"]})
    with pytest.raises(ValueError):
        vs.score_table(review, llm)


# ── 실행 함수 ──
@pytest.fixture
def db_path(tmp_path):
    path = db.init_db(tmp_path / "t.db")
    conn = db.connect(path)
    df = analysis_frame((6, 4, 0, 0))
    db.write_table(conn, "news", df.assign(url=df["news_id"], is_duplicate=0, dup_group_id=None)[
        ["news_id", "published_at", "title", "content", "url", "is_duplicate", "dup_group_id"]], mode="append")
    db.write_table(conn, "news_analysis", df.assign(prompt_version=vs.SAMPLE_VERSION, issue_keywords="[]",
                                                    model="m")[
        ["news_id", "prompt_version", "sentiment_skh", "sentiment_sec", "issue_keywords", "model"]], mode="append")
    conn.close()
    return path


def test_sample_main_writes_and_refuses_overwrite(db_path, tmp_path):
    out = tmp_path / "review.csv"
    s = vs.sample_main(n=5, path=out, db_path=db_path)
    assert len(s) == 5 and out.exists()
    with pytest.raises(SystemExit):
        vs.sample_main(n=5, path=out, db_path=db_path)  # 라벨을 덮어쓰지 않는다
    assert len(vs.sample_main(n=4, path=out, db_path=db_path, force=True)) == 4


def test_score_main_end_to_end(db_path, tmp_path):
    out = tmp_path / "review.csv"
    s = vs.sample_main(n=4, path=out, db_path=db_path)
    llm = vs.load_llm(db_path).set_index("news_id")
    s["human_skh"] = s["news_id"].map(llm["sentiment_skh"])  # 전부 LLM과 같게 채우면 정확도 1
    s["human_sec"] = s["news_id"].map(llm["sentiment_sec"])
    s.to_csv(out, index=False, encoding="utf-8-sig")
    table = vs.score_main(path=out, db_path=db_path, llm_version=vs.SAMPLE_VERSION, out=tmp_path / "score.csv",
                          report_dir=tmp_path).set_index("company")
    assert (table["accuracy"] == 1.0).all() and (table["n"] == 4).all()
    assert (tmp_path / "score.csv").exists()


def test_html_main_writes_full_text_without_llm_labels(db_path, tmp_path):
    review = tmp_path / "review.csv"
    s = vs.sample_main(n=3, path=review, db_path=db_path)
    out = vs.html_main(path=review, db_path=db_path, out=tmp_path / "view.html")
    text = out.read_text(encoding="utf-8")
    assert text.startswith("<!DOCTYPE html>")
    for i, nid in enumerate(s["news_id"], start=1):
        assert f'id="r{i}"' in text and nid in text   # 번호 = CSV 행 순서
    assert "본문" * 400 in text                       # 본문 전체 (500자 head가 아님)
    assert "sentiment_skh" not in text and "긍정</td>" not in text  # LLM 판정 없음


def test_score_main_compares_other_llm_version_on_same_sample(db_path, tmp_path):
    """표본(sent_v1에서 뽑음)은 그대로 두고 다른 프롬프트 버전 결과를 채점한다 (v1·v2 비교)."""
    out = tmp_path / "review.csv"
    s = vs.sample_main(n=4, path=out, db_path=db_path)
    conn = db.connect(db_path)
    llm = vs.load_llm(db_path)
    db.write_table(conn, "news_analysis", llm.assign(prompt_version="v_other", sentiment_skh="해당없음",
                   issue_keywords="[]", model="m")[["news_id", "prompt_version", "sentiment_skh",
                   "sentiment_sec", "issue_keywords", "model"]], mode="append")
    conn.close()
    l1 = llm.set_index("news_id")
    s["human_skh"] = s["news_id"].map(l1["sentiment_skh"])
    s["human_sec"] = s["news_id"].map(l1["sentiment_sec"])
    s.to_csv(out, index=False, encoding="utf-8-sig")
    t = vs.score_main(path=out, db_path=db_path, llm_version="v_other", out=tmp_path / "o.csv",
                      report_dir=tmp_path).set_index("company")
    assert t.loc["삼성전자", "accuracy"] == 1.0          # sec는 그대로
    assert t.loc["SK하이닉스", "accuracy"] < 1.0          # skh는 모두 해당없음으로 바꿈
    assert vs.REVIEW_PATH.name == "sentiment_review_sent_v1.csv"  # 표본 파일은 v1 고정


# ── 이슈 키워드 검수 (가이드 3-1·6: 핵심 이슈 추출 정확도 표본 검수) ──
def kw_review_frame():
    review = pd.DataFrame({"news_id": [f"n{i}" for i in range(4)], "published_at": ["2024.01.0%d" % (i + 1) for i in range(4)],
                           "title": [f"제목{i}" for i in range(4)]})
    keywords = pd.DataFrame({"news_id": ["n0", "n1", "n2", "n3"],
                             "issue_keywords": ['["HBM3E 인증", "엔비디아 공급"]', '["대중 수출 규제"]', "[]",
                                                '["HBM4 양산", "가격 하락", "실적 악화"]']})
    return review, keywords


def test_build_keyword_review_takes_first_rows_with_llm_keywords_and_blank_judgments():
    review, keywords = kw_review_frame()
    kw = vs.build_keyword_review(review, keywords, rows=3)
    assert list(kw.columns) == vs.KW_COLUMNS
    assert kw["row"].tolist() == [1, 2, 3] and kw["news_id"].tolist() == ["n0", "n1", "n2"]  # 감성 표본과 같은 행 번호
    assert kw.loc[0, "keywords"] == "HBM3E 인증 | 엔비디아 공급" and kw["kw_total"].tolist() == [2, 1, 0]
    assert (kw["kw_correct"] == "").all() and (kw["kw_core"] == "").all()   # 판정 칸은 사람이 채운다


def test_keyword_score_precision_and_core_capture():
    kw = pd.DataFrame({"row": [1, 2, 3, 4], "kw_total": [2, 1, 3, 2], "kw_correct": ["2", "0", "2", ""],
                       "kw_core": ["1", "0", "1", ""]})
    t = vs.keyword_score(kw).iloc[0]
    assert t["n_articles"] == 3                                    # 판정이 빈 행(4)은 뺀다
    assert t["kw_total"] == 6 and t["kw_correct"] == 4
    assert t["precision"] == pytest.approx(4 / 6) and t["core_capture"] == pytest.approx(2 / 3)
    assert 0 <= t["precision_ci_low"] < t["precision"] < t["precision_ci_high"] <= 1
    assert 0 <= t["core_ci_low"] < t["core_capture"] < t["core_ci_high"] <= 1
    assert t["articles_all_wrong"] == 1                            # 키워드가 모두 틀린 기사 수


@pytest.mark.parametrize("correct, core", [("3", "1"), ("-1", "0"), ("1", "2"), ("x", "1")])
def test_keyword_score_rejects_invalid_judgments(correct, core):
    kw = pd.DataFrame({"row": [1], "kw_total": [2], "kw_correct": [correct], "kw_core": [core]})
    with pytest.raises(ValueError):
        vs.keyword_score(kw)                                       # 맞은 수 > 전체, 음수, kw_core가 0/1이 아님


def test_keyword_sample_main_uses_sentiment_sample_order_and_refuses_overwrite(db_path, tmp_path):
    review = tmp_path / "review.csv"
    s = vs.sample_main(n=4, path=review, db_path=db_path)
    out = tmp_path / "kw.csv"
    kw = vs.keyword_sample_main(review_path=review, db_path=db_path, version=vs.SAMPLE_VERSION, path=out, rows=3)
    assert kw["news_id"].tolist() == s["news_id"].tolist()[:3] and out.exists()
    with pytest.raises(SystemExit):
        vs.keyword_sample_main(review_path=review, db_path=db_path, version=vs.SAMPLE_VERSION, path=out, rows=3)
