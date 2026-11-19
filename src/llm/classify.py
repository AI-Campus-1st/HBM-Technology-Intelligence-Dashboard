"""
HBM 기사에 LLM 기업별 감성 분류·이슈 키워드 추출을 배치로 실행하고 news_analysis에 저장한다 (Day 4).
대시보드에서 실시간으로 부르지 않도록 미리 생성한다.

대상: 중복 제외(is_duplicate = 0) + HBM 관련도 '핵심'·'관련' 기사 385건 (news_trend·spike_detection과 같은 분석 대상).
흐름: load_targets → (기사마다) prompts.build_messages → LLM 호출(JSON 모드) → prompts.parse_response → news_analysis upsert
- 응답 형식이 틀리거나 호출이 실패하면 max_retries번 다시 시도하고, 그래도 안 되면 실패 목록에 남긴다 (DB에는 넣지 않음).
- 같은 prompt_version으로 이미 저장된 기사는 건너뛴다 → 중간에 멈춰도 다시 실행하면 남은 기사만 처리한다.
- batch_size건마다 DB에 저장해 중간 결과를 잃지 않는다.

실행: python -m src.llm.classify --dry-run      (API 호출 없이 대상 건수·입력 글자 수만)
      python -m src.llm.classify --limit 20     (앞 20건만 — 프롬프트 점검용)
      python -m src.llm.classify                (남은 대상 전체)
필요: .env의 OPENAI_API_KEY, openai 패키지 (requirements/issue.txt). 모델은 config.LLM_MODEL (프로젝트 공통).
저장: news_analysis (news_id, prompt_version) / 실패 목록 outputs/reports/llm_failures_<버전>.csv

담당: 김한승 (이슈 분석)
일정: Day 4
"""

import argparse
import json
import time
from pathlib import Path

import pandas as pd

from src.common import config, db
from src.llm import prompts

TARGET_LEVELS = ("핵심", "관련")
BATCH_SIZE = 20
MAX_RETRIES = 2
RETRY_WAIT_SEC = 2.0
REPORTS_DIR = config.OUTPUTS_DIR / "reports"


def load_targets(conn, prompt_version: str = prompts.PROMPT_VERSION, limit: int | None = None) -> pd.DataFrame:
    """분류할 기사 (발행일·news_id 순). 같은 버전으로 이미 저장된 기사는 뺀다."""
    sql = """
        SELECT n.news_id, n.published_at, n.title, n.content
        FROM news AS n
        JOIN news_tag AS t
          ON t.news_id = n.news_id AND t.tag_type = 'tech' AND t.tag = 'HBM'
         AND t.relevance IN (?, ?)
        WHERE n.is_duplicate = 0
          AND NOT EXISTS (SELECT 1 FROM news_analysis AS a
                          WHERE a.news_id = n.news_id AND a.prompt_version = ?)
        ORDER BY n.published_at, n.news_id
    """
    params = [*TARGET_LEVELS, prompt_version]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))
    return pd.read_sql_query(sql, conn, params=params)


def estimate(targets: pd.DataFrame, max_chars: int = prompts.MAX_CONTENT_CHARS) -> dict:
    """API 호출 없이 입력 규모를 센다. 토큰 수는 모델 토크나이저에 따라 다르므로 글자 수로만 보고한다."""
    content = targets["content"].fillna("").str.strip().str[:max_chars].str.len().sum()
    title = targets["title"].str.len().sum()
    return {
        "n_articles": len(targets),
        "title_chars": int(title),
        "content_chars": int(content),
        "system_prompt_chars": len(prompts.SYSTEM_PROMPT),  # 기사마다 반복된다
        "total_input_chars": int(title + content + len(prompts.SYSTEM_PROMPT) * len(targets)),
    }


def make_client():
    """OpenAI 클라이언트 (키는 .env에서 읽고 출력하지 않는다). openai는 실행할 때만 import한다."""
    from openai import OpenAI
    return OpenAI(api_key=config.require_env("OPENAI_API_KEY"))


def classify_article(client, title: str, content: str | None, model: str,
                     max_retries: int = MAX_RETRIES, wait: float = 0.0) -> tuple[dict | None, int, str]:
    """기사 한 건 분류. Returns (결과 또는 None, 시도 횟수, 마지막 오류 메시지)."""
    messages = prompts.build_messages(title, content)
    error = ""
    for attempt in range(1, max_retries + 2):
        try:
            resp = client.chat.completions.create(model=model, messages=messages,
                                                  response_format={"type": "json_object"})
            return prompts.parse_response(resp.choices[0].message.content), attempt, ""
        except Exception as e:  # 형식 오류·네트워크·rate limit 모두 재시도 대상
            error = f"{type(e).__name__}: {e}"[:300]
            if wait and attempt <= max_retries:
                time.sleep(wait * attempt)
    return None, max_retries + 1, error


def run(conn, client, targets: pd.DataFrame, model: str = config.LLM_MODEL,
        prompt_version: str = prompts.PROMPT_VERSION, batch_size: int = BATCH_SIZE,
        max_retries: int = MAX_RETRIES, wait: float = 0.0) -> tuple[int, pd.DataFrame]:
    """대상 기사를 분류해 batch_size건마다 news_analysis에 upsert. Returns (저장 건수, 실패 목록)."""
    saved, buffer, failures = 0, [], []

    def flush():
        nonlocal saved
        if buffer:
            saved += db.write_table(conn, "news_analysis", pd.DataFrame(buffer), mode="upsert")
            buffer.clear()

    for i, row in enumerate(targets.itertuples(index=False), start=1):
        result, attempts, error = classify_article(client, row.title, row.content, model, max_retries, wait)
        if result is None:
            failures.append({"news_id": row.news_id, "published_at": row.published_at, "title": row.title,
                             "attempts": attempts, "error": error})
        else:
            buffer.append({"news_id": row.news_id, "prompt_version": prompt_version,
                           "sentiment_skh": result["sentiment_skh"], "sentiment_sec": result["sentiment_sec"],
                           "issue_keywords": json.dumps(result["issue_keywords"], ensure_ascii=False),
                           "model": model})
        if len(buffer) >= batch_size:
            flush()
            print(f"  {i}/{len(targets)}건 처리 (저장 {saved}, 실패 {len(failures)})")
    flush()
    return saved, pd.DataFrame(failures, columns=["news_id", "published_at", "title", "attempts", "error"])


def summarize(conn, prompt_version: str = prompts.PROMPT_VERSION) -> pd.DataFrame:
    """저장된 결과의 기업별 라벨 분포."""
    df = db.read_table(conn, "news_analysis", where="prompt_version = ?", params=(prompt_version,))
    rows = [{"company": name, **df[col].value_counts().reindex(prompts.LABELS, fill_value=0).to_dict()}
            for name, col in (("SK하이닉스", "sentiment_skh"), ("삼성전자", "sentiment_sec"))]
    return pd.DataFrame(rows)


def main(limit: int | None = None, dry_run: bool = False, model: str = config.LLM_MODEL,
         db_path: Path = config.DB_PATH, reports_dir: Path = REPORTS_DIR) -> dict:
    conn = db.connect(db_path)
    try:
        targets = load_targets(conn, limit=limit)
        est = estimate(targets)
        print(f"프롬프트 {prompts.PROMPT_VERSION} · 모델 {model} · 남은 대상 {est['n_articles']}건 "
              f"(본문 앞 {prompts.MAX_CONTENT_CHARS:,}자)")
        print(f"입력 글자 수: 제목 {est['title_chars']:,} + 본문 {est['content_chars']:,} "
              f"+ 시스템 프롬프트 {est['system_prompt_chars']:,}×{est['n_articles']} = {est['total_input_chars']:,}자")
        if dry_run or targets.empty:
            print("API 호출 없음 (--dry-run)" if dry_run else "분류할 기사가 없습니다.")
            return est
        saved, failures = run(conn, make_client(), targets, model=model, wait=RETRY_WAIT_SEC)
        print(f"저장 {saved}건, 실패 {len(failures)}건")
        if not failures.empty:
            reports_dir.mkdir(parents=True, exist_ok=True)
            path = reports_dir / f"llm_failures_{prompts.PROMPT_VERSION}.csv"
            failures.to_csv(path, index=False, encoding="utf-8-sig")
            print(f"실패 목록: {path} (다시 실행하면 실패한 기사만 다시 시도)")
        print(summarize(conn).to_string(index=False))
        return {**est, "saved": saved, "failed": len(failures)}
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HBM 기사 기업별 감성 분류 → news_analysis")
    parser.add_argument("--limit", type=int, default=None, help="앞에서부터 N건만 (프롬프트 점검용)")
    parser.add_argument("--dry-run", action="store_true", help="API 호출 없이 대상 건수·입력 글자 수만")
    parser.add_argument("--model", default=config.LLM_MODEL, help=f"기본 {config.LLM_MODEL} (config.LLM_MODEL)")
    args = parser.parse_args()
    main(limit=args.limit, dry_run=args.dry_run, model=args.model)
