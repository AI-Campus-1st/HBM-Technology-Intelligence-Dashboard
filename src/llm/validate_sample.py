"""
LLM 기업별 감성 분류 결과에서 층화 표본을 뽑아 사람이 독립 판정하고, 정확도·Macro-F1·혼동행렬을 계산한다 (Day 4~5).

흐름 (relevance_review와 같은 sample → 라벨 → score 방식):
    1) sample: news_analysis(현재 프롬프트 버전) 기사에서 표본 100건을 뽑아 data/labels/sentiment_review_<버전>.csv로 저장.
       - 층 = 분기 × 기업 그룹(LLM 판정 기준: SK만 / 삼성만 / 둘 다 / 둘 다 해당없음). 층 크기에 비례해 배분(최대 나머지 방식).
         분기·기업 구성이 모집단과 같아지고, '해당없음' 판정도 표본에 들어가 놓친 언급을 확인할 수 있다.
       - LLM 판정은 검수 파일에 넣지 않는다 (사람이 보고 따라가지 않도록, 태깅 검수와 같은 블라인드 원칙).
    2) 사람이 human_skh·human_sec를 채운다. 교차 검수자는 일부 행(20~30건)의 cross_skh·cross_sec를 따로 채운다.
    3) score: 사람 라벨을 정답으로 LLM 판정과 비교 → 기업별 정확도(Wilson 95% CI)·Macro-F1·LLM-사람 κ,
       교차 검수 일치율·κ, 라벨별 정밀도·재현율, 혼동행렬.

지표를 정확도 하나로 내지 않는 이유: 감성 라벨은 불균형(중립·해당없음이 많을 것으로 예상)이라
    다수 라벨만 맞혀도 정확도가 높게 나온다. 라벨마다 F1을 구해 단순 평균한 Macro-F1과 라벨별 재현율을 함께 본다.

실행: python -m src.llm.validate_sample sample [--n 100] [--force]
      python -m src.llm.validate_sample score
저장: data/labels/sentiment_review_<버전>.csv (커밋 대상), outputs/reports/sentiment_eval_<버전>.csv,
      outputs/reports/sentiment_eval_<버전>_by_label.csv, outputs/reports/sentiment_eval_<버전>_confusion.csv

담당: 김한승 (이슈 분석)
일정: Day 4~5
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from src.common import config, db
from src.llm import prompts
from src.news.tag_validation import wilson_interval

SAMPLE_SIZE = 100
SEED = 42
HEAD_CHARS = 500  # 검수 파일에 넣는 본문 앞부분 (LLM 입력 1,500자 중 판정 단서가 주로 있는 앞부분)
REVIEW_PATH = config.LABELS_DIR / f"sentiment_review_{prompts.PROMPT_VERSION}.csv"
REPORTS_DIR = config.OUTPUTS_DIR / "reports"
SCORE_PATH = REPORTS_DIR / f"sentiment_eval_{prompts.PROMPT_VERSION}.csv"
COMPANIES = (("SK하이닉스", "skh"), ("삼성전자", "sec"))
REVIEW_COLUMNS = ["news_id", "published_at", "quarter", "stratum", "title", "head",
                  "human_skh", "human_sec", "cross_skh", "cross_sec", "note", "labeler"]


# ── 표본 추출 ──
def quarter_of(published_at: str) -> str:
    """'2024-05-10' → '2024Q2'"""
    return f"{published_at[:4]}Q{(int(published_at[5:7]) - 1) // 3 + 1}"


def company_group(skh: str, sec: str) -> str:
    """LLM 판정으로 본 기사의 기업 등장 형태."""
    has_skh, has_sec = skh != "해당없음", sec != "해당없음"
    if has_skh and has_sec:
        return "둘 다"
    if has_skh:
        return "SK만"
    if has_sec:
        return "삼성만"
    return "둘 다 해당없음"


def allocate(sizes: pd.Series, n: int) -> pd.Series:
    """층 크기에 비례해 n건을 배분한다 (최대 나머지 방식, 층 크기를 넘지 않음). 합은 min(n, 전체)."""
    total = int(sizes.sum())
    n = min(n, total)
    exact = sizes / total * n
    out = np.floor(exact).astype(int)
    remainder = (exact - out).sort_values(ascending=False, kind="stable")
    for key in remainder.index:
        if out.sum() >= n:
            break
        if out[key] < sizes[key]:
            out[key] += 1
    return out.astype(int)


def build_sample(df: pd.DataFrame, n: int = SAMPLE_SIZE, seed: int = SEED) -> pd.DataFrame:
    """층화 표본 (검수 파일 형식, LLM 판정 열 없음).

    Args:
        df: news_id, published_at, title, content, sentiment_skh, sentiment_sec
    """
    work = df.copy()
    work["quarter"] = work["published_at"].map(quarter_of)
    work["stratum"] = work["quarter"] + " | " + [company_group(a, b) for a, b in
                                                 zip(work["sentiment_skh"], work["sentiment_sec"])]
    work = work.sort_values("news_id").reset_index(drop=True)  # 입력 순서와 무관하게 재현되도록
    quota = allocate(work["stratum"].value_counts().sort_index(), n)
    picks = [work[work["stratum"] == s].sample(n=int(k), random_state=seed) for s, k in quota.items() if k > 0]
    sample = pd.concat(picks).sort_values(["published_at", "news_id"]).reset_index(drop=True)
    sample["head"] = sample["content"].fillna("").str.strip().str[:HEAD_CHARS]
    for col in ("human_skh", "human_sec", "cross_skh", "cross_sec", "note", "labeler"):
        sample[col] = None
    return sample[REVIEW_COLUMNS]


# ── 지표 ──
def _labels_in(y_true, y_pred) -> list[str]:
    present = set(y_true) | set(y_pred)
    return [l for l in prompts.LABELS if l in present]


def confusion(y_true, y_pred) -> pd.DataFrame:
    """행 = 사람(정답), 열 = LLM. 등장한 라벨만."""
    labels = _labels_in(y_true, y_pred)
    cm = pd.crosstab(pd.Categorical(y_true, labels), pd.Categorical(y_pred, labels), dropna=False)
    cm.index.name, cm.columns.name = "사람", "LLM"
    return cm


def class_report(y_true, y_pred) -> pd.DataFrame:
    """라벨별 정밀도·재현율·F1·정답 건수 (정답·예측 어디에도 없는 라벨은 뺀다)."""
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)
    rows = []
    for label in _labels_in(y_true, y_pred):
        tp = int(((y_true == label) & (y_pred == label)).sum())
        pred, support = int((y_pred == label).sum()), int((y_true == label).sum())
        precision = tp / pred if pred else 0.0
        recall = tp / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        rows.append({"label": label, "precision": precision, "recall": recall, "f1": f1,
                     "support": support, "predicted": pred})
    return pd.DataFrame(rows, columns=["label", "precision", "recall", "f1", "support", "predicted"])


def macro_f1(y_true, y_pred) -> float:
    rep = class_report(y_true, y_pred)
    return float(rep["f1"].mean()) if not rep.empty else float("nan")


def cohen_kappa(a, b) -> float:
    """두 판정의 우연 일치를 보정한 일치도. 한 라벨만 있어 기대 일치가 1이면 완전 일치일 때 1."""
    a, b = np.asarray(a), np.asarray(b)
    if len(a) == 0:
        return float("nan")
    po = float((a == b).mean())
    pe = sum(float((a == l).mean()) * float((b == l).mean()) for l in set(a) | set(b))
    if pe >= 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1 - pe)


def _check_labels(series: pd.Series, name: str) -> None:
    bad = sorted(set(series.dropna()) - set(prompts.LABELS))
    if bad:
        raise ValueError(f"{name}에 허용되지 않은 라벨: {bad} (허용: {prompts.LABELS})")


def score_table(review: pd.DataFrame, llm: pd.DataFrame) -> pd.DataFrame:
    """기업별 요약 지표. 사람 라벨이 빈 행은 뺀다."""
    for col in ("human_skh", "human_sec", "cross_skh", "cross_sec"):
        _check_labels(review[col], col)
    merged = review.merge(llm, on="news_id", how="inner")
    rows = []
    for name, key in COMPANIES:
        done = merged.dropna(subset=[f"human_{key}"])
        y, p = done[f"human_{key}"].tolist(), done[f"sentiment_{key}"].tolist()
        k = sum(a == b for a, b in zip(y, p))
        low, high = wilson_interval(k, len(y))
        cross = done.dropna(subset=[f"cross_{key}"])
        rows.append({
            "company": name, "n": len(y), "accuracy": k / len(y) if y else float("nan"),
            "ci_low": low, "ci_high": high, "macro_f1": macro_f1(y, p), "kappa_llm_human": cohen_kappa(y, p),
            "n_cross": len(cross),
            "cross_agreement": float((cross[f"human_{key}"] == cross[f"cross_{key}"]).mean()) if len(cross) else float("nan"),
            "cross_kappa": cohen_kappa(cross[f"human_{key}"], cross[f"cross_{key}"]) if len(cross) else float("nan"),
        })
    return pd.DataFrame(rows)


# ── 실행 ──
def load_llm(db_path: Path = config.DB_PATH, prompt_version: str = prompts.PROMPT_VERSION) -> pd.DataFrame:
    """news_analysis(해당 버전) + 기사 제목·본문."""
    conn = db.connect(db_path)
    try:
        return pd.read_sql_query("""
            SELECT a.news_id, n.published_at, n.title, n.content, a.sentiment_skh, a.sentiment_sec
            FROM news_analysis AS a JOIN news AS n ON n.news_id = a.news_id
            WHERE a.prompt_version = ?
            ORDER BY a.news_id
        """, conn, params=(prompt_version,))
    finally:
        conn.close()


def sample_main(n: int = SAMPLE_SIZE, force: bool = False, path: Path = REVIEW_PATH,
                db_path: Path = config.DB_PATH, seed: int = SEED) -> pd.DataFrame:
    if path.exists() and not force:
        raise SystemExit(f"이미 있습니다: {path}\n라벨을 덮어쓰지 않으려고 멈춥니다. 새로 뽑으려면 --force를 붙이세요.")
    llm = load_llm(db_path)
    if llm.empty:
        raise SystemExit(f"news_analysis({prompts.PROMPT_VERSION})가 비어 있습니다. 먼저 python -m src.llm.classify를 실행하세요.")
    sample = build_sample(llm, n=n, seed=seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    sample.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"검수 표본 {len(sample)}건 (모집단 {len(llm)}건, seed {seed}) 저장: {path}")
    print(sample["stratum"].str.split(" \\| ").str[1].value_counts().rename("기업 그룹별 표본").to_string())
    return sample


def score_main(path: Path = REVIEW_PATH, db_path: Path = config.DB_PATH, out: Path = SCORE_PATH,
               report_dir: Path = REPORTS_DIR) -> pd.DataFrame:
    review = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False).replace({"": None})
    llm = load_llm(db_path)[["news_id", "sentiment_skh", "sentiment_sec"]]
    table = score_table(review, llm)
    out.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(out, index=False, encoding="utf-8-sig")

    merged = review.merge(llm, on="news_id")
    by_label, confusions = [], []
    for name, key in COMPANIES:
        done = merged.dropna(subset=[f"human_{key}"])
        by_label.append(class_report(done[f"human_{key}"], done[f"sentiment_{key}"]).assign(company=name))
        cm = confusion(done[f"human_{key}"].tolist(), done[f"sentiment_{key}"].tolist())
        confusions.append(cm.reset_index().assign(company=name))
    stem = out.stem
    pd.concat(by_label).to_csv(report_dir / f"{stem}_by_label.csv", index=False, encoding="utf-8-sig")
    pd.concat(confusions).to_csv(report_dir / f"{stem}_confusion.csv", index=False, encoding="utf-8-sig")

    print(f"라벨 {int(review['human_skh'].notna().sum())}/{len(review)}건 기준 ({prompts.PROMPT_VERSION})")
    print(table.round(3).to_string(index=False))
    print(f"저장: {out}, {stem}_by_label.csv, {stem}_confusion.csv")
    return table


def main(argv: list | None = None) -> None:
    parser = argparse.ArgumentParser(description="LLM 기업별 감성 분류 표본 검수")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_sample = sub.add_parser("sample", help="검수용 층화 표본 CSV 만들기")
    p_sample.add_argument("--n", type=int, default=SAMPLE_SIZE, help=f"표본 수 (기본 {SAMPLE_SIZE})")
    p_sample.add_argument("--force", action="store_true", help="이미 있는 검수 파일을 덮어쓴다 (라벨이 지워짐)")
    sub.add_parser("score", help="사람 라벨과 LLM 판정 비교")
    args = parser.parse_args(argv)
    if args.cmd == "sample":
        sample_main(n=args.n, force=args.force)
    else:
        score_main()


if __name__ == "__main__":
    main()
