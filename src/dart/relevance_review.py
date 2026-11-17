"""
수집한 공시가 프로젝트 질문에 실제로 관련 있는지 표본 검수로 확인한다.
뉴스 태깅 검수(src/news/tag_validation.py)와 같은 흐름이고, 신뢰구간 등 계산 함수를 함께 쓴다.

흐름:
    1) sample: disclosure 테이블에서 층(유형 × RAG 대상/제외)마다 표본을 뽑아
       검수용 CSV(data/labels/disclosure_review_v1.csv)를 만든다. 판정에 필요한 본문 발췌를 함께 저장한다.
    2) 사람이 label 열을 채운다 (아래 기준).
    3) score: 층별 관련 비율과 95% 신뢰구간(Wilson)을 outputs/reports/disclosure_relevance_v1.csv에 저장한다.
       - RAG 대상 층: 관련 비율 = 정밀도 (낮으면 그 유형·공시명을 RAG에서 뺀다)
       - 제외 층: 관련 비율 = 놓친 비율 (높으면 필터가 관련 공시를 잘못 뺀 것)

라벨 기준 (핵심 질문: HBM 경쟁에서 두 기업의 관심·이슈 변화, 공시로 확인되는 대응과 기회·위험 신호):
    2 = 직접: HBM 또는 HBM 관련 투자·제품·실적·고객을 직접 다룬다
    1 = 간접: 메모리 사업·설비투자·실적·경영계획 등 HBM 판단의 배경 근거가 된다
    0 = 무관: 프로젝트 질문과 관계없다 (자사주 보상 처분, 배당, 계열사 보험·급식 거래, 위임장 플랫폼 안내 등)
    판정이 애매하면 note에 이유를 적는다. labeler에는 판정한 사람을 적는다 (예: 한도윤, claude_1차).

실행:
    python -m src.dart.relevance_review sample           (이미 있으면 덮어쓰지 않음, --force로 덮어씀)
    python -m src.dart.relevance_review score

담당: 한도윤 (공시 분석)
일정: Day 2~3 (Day 5 RAG 전에 범위 확정)
"""

import argparse
import re
from pathlib import Path

import pandas as pd

from src.common import config, db
from src.news.tag_validation import extract_contexts, wilson_interval

REVIEW_VERSION = "v1"
REVIEW_PATH = config.LABELS_DIR / f"disclosure_review_{REVIEW_VERSION}.csv"
SCORE_PATH = config.OUTPUTS_DIR / "reports" / f"disclosure_relevance_{REVIEW_VERSION}.csv"
SEED = 42

# 층별 표본 크기. None이면 전수. (2026-11-16 기준 층 크기: A 24, B 37, D 11, I 101, J 29 / 제외 I 188, J 178)
STRATA = {
    ("A", "RAG대상"): None,
    ("B", "RAG대상"): 20,
    ("D", "RAG대상"): None,
    ("I", "RAG대상"): 20,
    ("J", "RAG대상"): None,
    ("I", "제외"): 15,
    ("J", "제외"): 15,
}

# 판정 근거가 될 만한 단어 주변을 발췌한다 (관련·무관 신호를 모두 포함해 검수자가 판단하게 한다).
# '투자'는 모든 거래소 공시의 상투 문구 "기타 투자판단과 관련한 중요사항"에 걸려 '투자판단'은 뺀다.
CONTEXT_PATTERN = re.compile(
    r"HBM|고대역폭|메모리|D램|DRAM|FAB|팹|공장|설비|증설|건설|생산|투자(?!판단)|패키징|AI|"
    r"자기주식|배당|보상|임직원|보험|퇴직연금|거래상대방"
)
HEAD_CHARS = 300
LABELS = (0, 1, 2)
REVIEW_COLUMNS = [
    "stratum", "pblntf_ty", "rcept_no", "corp_name", "rcept_dt", "report_nm", "url",
    "rag_target", "filter_reason", "hbm_count", "text_len", "head", "context", "label", "note", "labeler",
]


def stratum_of(rag_target: int) -> str:
    return "RAG대상" if rag_target == 1 else "제외"


def build_sample(df: pd.DataFrame, strata: dict = STRATA, seed: int = SEED) -> pd.DataFrame:
    """disclosure 행에서 층별 표본을 뽑아 검수용 표로 만든다. 같은 입력·seed면 항상 같은 표본."""
    df = df.sort_values("rcept_no").reset_index(drop=True)
    df["stratum"] = df["rag_target"].map(stratum_of)
    parts = []
    for (ty, stratum), size in strata.items():
        group = df[(df["pblntf_ty"] == ty) & (df["stratum"] == stratum)]
        if size is not None and len(group) > size:
            group = group.sample(n=size, random_state=seed)
        parts.append(group.sort_values("rcept_no"))
    sample = pd.concat(parts, ignore_index=True) if parts else df.head(0)

    text = sample["text"].fillna("")
    sample["hbm_count"] = text.str.count("HBM")
    sample["text_len"] = text.str.len()
    sample["head"] = text.str.replace(r"\s+", " ", regex=True).str[:HEAD_CHARS]
    sample["context"] = [extract_contexts(t, CONTEXT_PATTERN, width=50, max_hits=4) for t in text]
    no_text = sample["text"].isna()
    sample.loc[no_text, "context"] = "(원문 미수집 — 공시명과 링크로 판정)"
    for col in ("label", "note", "labeler"):
        sample[col] = None
    return sample[REVIEW_COLUMNS]


def relevance_table(labels: pd.DataFrame) -> pd.DataFrame:
    """검수 결과로 층별 관련 비율 표를 만든다. label이 빈 행은 제외한다.

    Raises:
        ValueError: label에 0·1·2 이외의 값이 있을 때
    """
    labeled = labels.dropna(subset=["label"]).copy()
    labeled["label"] = labeled["label"].astype(int)
    if not labeled["label"].isin(LABELS).all():
        raise ValueError("label은 0(무관), 1(간접), 2(직접) 중 하나여야 합니다.")
    rows = []
    for (ty, stratum), g in labeled.groupby(["pblntf_ty", "stratum"], sort=True):
        n = len(g)
        k_rel = int((g["label"] >= 1).sum())
        k_direct = int((g["label"] == 2).sum())
        low, high = wilson_interval(k_rel, n)
        rows.append({
            "pblntf_ty": ty, "stratum": stratum, "n_labeled": n,
            "n_direct": k_direct, "n_indirect": k_rel - k_direct, "n_unrelated": n - k_rel,
            "relevant_rate": round(k_rel / n, 3), "ci_low": round(low, 3), "ci_high": round(high, 3),
            "meaning": "정밀도" if stratum == "RAG대상" else "놓친 비율",
        })
    return pd.DataFrame(rows)


def unrelated_names(labels: pd.DataFrame, top: int = 10) -> pd.DataFrame:
    """RAG 대상인데 무관(0)으로 판정된 공시명 상위 목록 — 범위 조정 후보."""
    bad = labels[(labels["stratum"] == "RAG대상") & (labels["label"] == 0)].copy()
    # [기재정정] 같은 앞머리와 정기보고서의 기간 표기 '(2024.03)'만 지운다. B의 '(자기주식처분결정)'처럼 종류를 나타내는 괄호는 남긴다.
    bad["name"] = bad["report_nm"].str.replace(r"^\[.*?\]", "", regex=True).str.replace(r"\s*\(\d{4}\.\d{2}\)$", "", regex=True)
    return bad.groupby(["pblntf_ty", "name"]).size().rename("count").reset_index().sort_values(
        "count", ascending=False).head(top)


def sample_main(force: bool = False, path: Path = REVIEW_PATH, db_path: Path = config.DB_PATH) -> pd.DataFrame:
    if path.exists() and not force:
        raise SystemExit(f"이미 있습니다: {path}\n라벨을 덮어쓰지 않으려고 멈춥니다. 새로 뽑으려면 --force를 붙이세요.")
    conn = db.connect(db_path)
    try:
        df = db.read_table(conn, "disclosure", columns=[
            "rcept_no", "corp_name", "report_nm", "rcept_dt", "pblntf_ty", "url",
            "text", "text_status", "rag_target", "filter_reason"])
    finally:
        conn.close()
    if df.empty:
        raise SystemExit("disclosure가 비어 있습니다. collect_list → collect_documents → parse_documents를 먼저 실행하세요.")
    sample = build_sample(df)
    path.parent.mkdir(parents=True, exist_ok=True)
    sample.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"검수 표본 {len(sample)}건 저장: {path}")
    print(sample.groupby(["pblntf_ty", "stratum"]).size().rename("표본").to_string())
    return sample


def score_main(path: Path = REVIEW_PATH, out: Path = SCORE_PATH) -> pd.DataFrame:
    labels = pd.read_csv(path, encoding="utf-8-sig", dtype={"rcept_no": str})
    table = relevance_table(labels)
    out.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(out, index=False, encoding="utf-8-sig")
    done, total = int(labels["label"].notna().sum()), len(labels)
    print(f"라벨 {done}/{total}건 기준")
    print(table.to_string(index=False))
    bad = unrelated_names(labels.dropna(subset=["label"]).astype({"label": int}))
    if not bad.empty:
        print("\nRAG 대상 중 무관 판정이 많은 공시명 (범위 조정 후보):")
        print(bad.to_string(index=False))
    print(f"저장: {out}")
    return table


def main(argv: list | None = None) -> None:
    parser = argparse.ArgumentParser(description="공시 관련성 표본 검수")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_sample = sub.add_parser("sample", help="검수용 표본 CSV 만들기")
    p_sample.add_argument("--force", action="store_true", help="이미 있는 검수 파일을 덮어쓴다")
    sub.add_parser("score", help="라벨을 채운 CSV로 관련 비율 계산")
    args = parser.parse_args(argv)
    if args.cmd == "sample":
        sample_main(force=args.force)
    else:
        score_main()


if __name__ == "__main__":
    main()
