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
    db.write_table(conn, "news_analysis", df.assign(prompt_version=prompts.PROMPT_VERSION, issue_keywords="[]",
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
    table = vs.score_main(path=out, db_path=db_path, out=tmp_path / "score.csv",
                          report_dir=tmp_path).set_index("company")
    assert (table["accuracy"] == 1.0).all() and (table["n"] == 4).all()
    assert (tmp_path / "score.csv").exists()
