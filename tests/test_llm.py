"""
LLM 기업별 감성 분류(src/llm/prompts.py, classify.py) 테스트.
실제 API는 부르지 않고, OpenAI SDK와 같은 모양의 가짜 클라이언트로 확인한다.

담당: 김한승 (이슈 분석)
일정: Day 4
"""

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from src.common import db
from src.llm import classify, prompts


# ── 가짜 클라이언트: client.chat.completions.create(...).choices[0].message.content ──
class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)  # 문자열 또는 Exception
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])


def ok(skh="긍정", sec="해당없음", kw=("HBM3E", "엔비디아")):
    return json.dumps({"sentiment_skh": skh, "sentiment_sec": sec, "issue_keywords": list(kw)}, ensure_ascii=False)


# ── prompts ──
def test_system_prompt_has_every_label_and_company():
    for label in prompts.LABELS:
        assert label in prompts.SYSTEM_PROMPT
    assert "SK하이닉스" in prompts.SYSTEM_PROMPT and "삼성전자" in prompts.SYSTEM_PROMPT


def test_build_messages_truncates_content():
    msgs = prompts.build_messages("제목", "가" * 5000, max_chars=100)
    assert [m["role"] for m in msgs] == ["system", "user"]
    user = msgs[1]["content"]
    assert "제목" in user and "가" * 100 in user and "가" * 101 not in user


def test_build_messages_handles_missing_content():
    assert "제목" in prompts.build_messages("제목", None)[1]["content"]


def test_parse_response_valid_and_code_fence():
    out = prompts.parse_response("```json\n" + ok(kw=(" HBM3E ", "HBM3E", "", "엔비디아")) + "\n```")
    assert out == {"sentiment_skh": "긍정", "sentiment_sec": "해당없음", "issue_keywords": ["HBM3E", "엔비디아"]}


def test_parse_response_limits_keywords():
    out = prompts.parse_response(ok(kw=[f"k{i}" for i in range(10)]))
    assert len(out["issue_keywords"]) == prompts.MAX_KEYWORDS


@pytest.mark.parametrize("text", [
    "not json",
    json.dumps({"sentiment_skh": "좋음", "sentiment_sec": "중립", "issue_keywords": []}),
    json.dumps({"sentiment_skh": "긍정", "issue_keywords": []}),
    json.dumps({"sentiment_skh": "긍정", "sentiment_sec": "중립", "issue_keywords": "HBM"}),
])
def test_parse_response_rejects_invalid(text):
    with pytest.raises(ValueError):
        prompts.parse_response(text)


# ── classify ──
ROWS = [  # (news_id, published_at, is_duplicate, HBM 관련도)
    ("a", "2024-01-05", 0, "핵심"),
    ("b", "2024-01-06", 1, "핵심"),   # 중복 → 제외
    ("c", "2024-01-07", 0, "관련"),
    ("d", "2024-01-08", 0, "언급"),   # 언급 → 제외
    ("e", "2024-01-09", 0, None),     # HBM 아님 → 제외
]


@pytest.fixture
def conn(tmp_path):
    conn = db.connect(db.init_db(tmp_path / "t.db"))
    db.write_table(conn, "news", pd.DataFrame([
        {"news_id": i, "published_at": d, "title": f"제목 {i}", "content": f"본문 {i}", "url": i,
         "is_duplicate": dup, "dup_group_id": None} for i, d, dup, _ in ROWS]), mode="append")
    db.write_table(conn, "news_tag", pd.DataFrame([
        {"news_id": i, "tag_type": "tech", "tag": "HBM", "relevance": rel, "in_title": int(rel == "핵심"),
         "body_count": 1, "rule_version": "test"} for i, _, _, rel in ROWS if rel]), mode="append")
    yield conn
    conn.close()


def test_load_targets_only_hbm_core_related_non_duplicate(conn):
    t = classify.load_targets(conn)
    assert t["news_id"].tolist() == ["a", "c"]
    assert list(t.columns) == ["news_id", "published_at", "title", "content"]


def test_load_targets_skips_already_classified_same_version(conn):
    db.write_table(conn, "news_analysis", pd.DataFrame([{
        "news_id": "a", "prompt_version": prompts.PROMPT_VERSION, "sentiment_skh": "중립",
        "sentiment_sec": "중립", "issue_keywords": "[]", "model": "m"}]), mode="append")
    assert classify.load_targets(conn)["news_id"].tolist() == ["c"]
    assert classify.load_targets(conn, prompt_version="other")["news_id"].tolist() == ["a", "c"]


def test_load_targets_limit(conn):
    assert len(classify.load_targets(conn, limit=1)) == 1


def test_estimate_counts_truncated_chars(conn):
    est = classify.estimate(classify.load_targets(conn), max_chars=2)
    assert est["n_articles"] == 2
    assert est["content_chars"] == 4  # '본문 a' → '본문' 2자 × 2건


def test_run_saves_results_and_uses_json_mode(conn):
    client = FakeClient([ok(), ok(skh="해당없음", sec="부정", kw=["수율"])])
    saved, failures = classify.run(conn, client, classify.load_targets(conn), model="m")
    assert saved == 2 and failures.empty
    out = db.read_table(conn, "news_analysis").set_index("news_id")
    assert out.loc["c", "sentiment_sec"] == "부정"
    assert json.loads(out.loc["a", "issue_keywords"]) == ["HBM3E", "엔비디아"]
    assert set(out["prompt_version"]) == {prompts.PROMPT_VERSION} and set(out["model"]) == {"m"}
    assert client.calls[0]["model"] == "m"
    assert client.calls[0]["response_format"] == {"type": "json_object"}


def test_run_retries_invalid_then_records_failure(conn):
    # a: 잘못된 응답 1회 후 성공 / c: 재시도까지 모두 실패
    client = FakeClient(["not json", ok(), "bad", RuntimeError("timeout"), "bad"])
    saved, failures = classify.run(conn, client, classify.load_targets(conn), model="m", max_retries=2)
    assert saved == 1
    assert failures["news_id"].tolist() == ["c"]
    assert failures.iloc[0]["attempts"] == 3 and failures.iloc[0]["error"]  # 마지막 오류 메시지를 남긴다
    assert db.read_table(conn, "news_analysis")["news_id"].tolist() == ["a"]
    assert len(client.calls) == 5


def test_run_is_resumable(conn):
    classify.run(conn, FakeClient([ok(), "bad", "bad", "bad"]), classify.load_targets(conn), model="m", max_retries=2)
    rest = classify.load_targets(conn)
    assert rest["news_id"].tolist() == ["c"]  # 실패한 기사만 다시 대상
    saved, _ = classify.run(conn, FakeClient([ok()]), rest, model="m")
    assert saved == 1 and len(db.read_table(conn, "news_analysis")) == 2


def test_main_dry_run_makes_no_client(conn, tmp_path, monkeypatch):
    def boom():
        raise AssertionError("dry-run에서 클라이언트를 만들면 안 된다")
    monkeypatch.setattr(classify, "make_client", boom)
    est = classify.main(db_path=tmp_path / "t.db", dry_run=True)
    assert est["n_articles"] == 2


def test_run_stops_after_consecutive_failures(tmp_path):
    """환경 문제처럼 매번 같은 오류가 나면 남은 기사를 부르지 않고 멈춘다 (불필요한 호출·비용 방지)."""
    conn = db.connect(db.init_db(tmp_path / "s.db"))
    ids = [f"n{i}" for i in range(6)]
    db.write_table(conn, "news", pd.DataFrame([
        {"news_id": i, "published_at": "2024-01-01", "title": i, "content": "본문", "url": i,
         "is_duplicate": 0, "dup_group_id": None} for i in ids]), mode="append")
    db.write_table(conn, "news_tag", pd.DataFrame([
        {"news_id": i, "tag_type": "tech", "tag": "HBM", "relevance": "핵심", "in_title": 1,
         "body_count": 1, "rule_version": "test"} for i in ids]), mode="append")
    client = FakeClient([TypeError("env")] * 100)
    saved, failures = classify.run(conn, client, classify.load_targets(conn), model="m",
                                   max_retries=0, abort_after=2)
    assert saved == 0 and len(failures) == 2  # 2건 연속 실패 후 중단
    assert len(client.calls) == 2
    conn.close()


def test_run_success_resets_consecutive_failures(conn):
    client = FakeClient(["bad", ok()])  # a 실패, c 성공 → 중단하지 않음
    saved, failures = classify.run(conn, client, classify.load_targets(conn), model="m",
                                   max_retries=0, abort_after=2)
    assert saved == 1 and len(failures) == 1


# ── 프롬프트 버전 (v1 보존 + v2) ──
def test_prompt_versions_registered():
    assert prompts.PROMPT_VERSION == "sent_v2"
    assert set(prompts.PROMPTS) >= {"sent_v1", "sent_v2"}
    assert prompts.PROMPTS["sent_v1"]["max_chars"] == 1500
    assert prompts.PROMPTS["sent_v2"]["max_chars"] == 6000
    v1, v2 = prompts.PROMPTS["sent_v1"]["system"], prompts.PROMPTS["sent_v2"]["system"]
    assert "7. 수출 규제" not in v1 and "7. 수출 규제" in v2  # v2: 업계 공통 악재·호재 규칙
    assert v2.startswith(v1.split("[출력 형식]")[0].rstrip())   # 규칙 1~6은 v1과 같다
    assert prompts.SYSTEM_PROMPT == v2


def test_build_messages_uses_version_length():
    long = "가" * 7000
    v1 = prompts.build_messages("t", long, version="sent_v1")[1]["content"]
    v2 = prompts.build_messages("t", long)[1]["content"]
    assert "가" * 1500 in v1 and "가" * 1501 not in v1
    assert "가" * 6000 in v2 and "가" * 6001 not in v2
    assert prompts.build_messages("t", long, version="sent_v1")[0]["content"] == prompts.PROMPTS["sent_v1"]["system"]


def test_build_messages_unknown_version():
    with pytest.raises(KeyError):
        prompts.build_messages("t", "b", version="nope")
