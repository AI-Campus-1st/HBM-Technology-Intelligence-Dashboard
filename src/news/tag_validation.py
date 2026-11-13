"""
태깅 규칙(tagging.py)의 정밀도를 표본 검수로 측정한다.

흐름:
    1) sample: 분석 기간 기사에 규칙을 적용하고 (태그, 관련도) 층마다 표본을 무작위로 뽑아
       검수용 CSV(data/labels/tag_review_<규칙버전>_<뉴스파일번호>.csv)를 만든다. 매칭 주변 문맥을 함께 저장해
       본문 전체를 읽지 않고도 판정할 수 있게 한다.
    2) 사람이 label 열을 채운다. 1 = 해당 기술·기업을 실질적으로 다룬 기사, 0 = 무관·단순 나열.
    3) score: 층별 정밀도와 95% 신뢰구간(Wilson)을 계산해 outputs/reports/에 저장한다.

실행:
    python -m src.news.tag_validation sample
    python -m src.news.tag_validation score

담당: 김한승 (이슈 분석)
일정: Day 1 (초안 검수) / Day 3 (규칙 수정 후 재검수)
"""

import argparse
import math
import random
import re
from typing import Optional

import pandas as pd

from src.news.tagging import RULE_VERSION, TAG_RULES, tag_article

PATTERNS = {tag: pattern for _, tag, pattern in TAG_RULES}

# 검수할 층과 층별 표본 수. HBM은 분석의 중심축이라 등급마다 30건,
# 기업 태그는 '핵심'(제목 포함)을 빼고 판단이 갈리는 '관련'·'언급'만 20건씩 본다.
REVIEW_TARGETS = {
    "HBM": {"핵심": 30, "관련": 30, "언급": 30},
    "SK하이닉스": {"관련": 20, "언급": 20},
    "삼성전자": {"관련": 20, "언급": 20},
}


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """성공 k / 시도 n 비율의 Wilson 신뢰구간. 표본이 작거나 비율이 0·1에 가까워도 범위가 [0, 1]을 벗어나지 않는다."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def precision_table(labels: pd.DataFrame) -> pd.DataFrame:
    """검수 결과(tag, relevance, label)로 층별 정밀도 표를 만든다. label이 빈 행은 제외한다.

    Raises:
        ValueError: label에 0·1 이외의 값이 있을 때
    """
    labeled = labels.dropna(subset=["label"]).copy()
    if not labeled["label"].isin([0, 1]).all():
        raise ValueError("label은 0 또는 1이어야 합니다.")
    rows = []
    for (tag, relevance), group in labeled.groupby(["tag", "relevance"], sort=False):
        n, k = len(group), int(group["label"].sum())
        low, high = wilson_interval(k, n)
        rows.append({"tag": tag, "relevance": relevance, "n_labeled": n, "n_correct": k,
                     "precision": k / n, "ci_low": low, "ci_high": high})
    return pd.DataFrame(rows)


def extract_contexts(text, pattern: re.Pattern, width: int = 60, max_hits: int = 3) -> str:
    """본문에서 패턴이 걸린 위치 앞뒤 width자를 잘라 ' … '로 이어 붙인다 (검수자가 빠르게 판정하도록)."""
    if not isinstance(text, str):
        return ""
    snippets = []
    for match in list(pattern.finditer(text))[:max_hits]:
        start, end = max(0, match.start() - width), min(len(text), match.end() + width)
        snippets.append(text[start:end].replace("\n", " "))
    return " … ".join(snippets)


class ReservoirSampler:
    """전체 개수를 모르는 스트림에서 k개를 균등 확률로 뽑는다 (큰 CSV를 한 번만 읽기 위해 사용).

    같은 seed와 같은 입력 순서면 항상 같은 표본이 나온다.
    """

    def __init__(self, k: int, seed: int):
        self.k = k
        self.items: list = []
        self._seen = 0
        self._rng = random.Random(seed)

    def add(self, item) -> None:
        self._seen += 1
        if len(self.items) < self.k:
            self.items.append(item)
        else:
            j = self._rng.randrange(self._seen)
            if j < self.k:
                self.items[j] = item


def build_review_sample(csv_path, start, end, targets: dict, seed: int = 42) -> pd.DataFrame:
    """뉴스 CSV를 청크로 읽어 규칙을 적용하고 (태그, 관련도) 층별 검수 표본을 만든다.

    Args:
        csv_path: 제공 뉴스 CSV 경로
        start, end: 분석 기간 (date, 양 끝 포함)
        targets: {태그: {관련도: 표본 수}} 검수할 층과 층별 표본 수
        seed: 재현용 난수 시드

    제목이 같은 기사는 첫 번째만 사용한다 (중복 기사가 표본에 여러 번 들어가지 않도록).
    """
    samplers = {
        (tag, level): ReservoirSampler(n, seed + i)
        for i, (tag, level, n) in enumerate(
            (t, lv, n) for t, levels in targets.items() for lv, n in levels.items()
        )
    }
    seen_titles: set = set()
    columns = ["제목", "본문전문", "원문URL", "발행일"]
    for chunk in pd.read_csv(csv_path, encoding="utf-8-sig", chunksize=10000, usecols=columns):
        dates = pd.to_datetime(chunk["발행일"], errors="coerce").dt.date
        chunk = chunk[(dates >= start) & (dates <= end)]
        for title, body, url, published in zip(chunk["제목"], chunk["본문전문"], chunk["원문URL"], chunk["발행일"]):
            if title in seen_titles:
                continue
            seen_titles.add(title)
            for row in tag_article(url, title, body):
                sampler = samplers.get((row["tag"], row["relevance"]))
                if sampler:
                    sampler.add((row, title, body, str(published)[:10]))

    records = []
    for (tag, level), sampler in samplers.items():
        for row, title, body, published in sampler.items:
            records.append({
                "tag": tag, "relevance": level, "url": row["news_id"], "published_at": published,
                "title": title, "body_count": row["body_count"],
                "context": extract_contexts(body, PATTERNS[tag]),
                "label": None, "note": "",
            })
    return pd.DataFrame(records)


def main(argv: Optional[list] = None) -> None:
    from src.common.config import ANALYSIS_END, ANALYSIS_START, LABELS_DIR, NEWS_CSV, OUTPUTS_DIR

    parser = argparse.ArgumentParser(description="태깅 규칙 정밀도 검수")
    parser.add_argument("step", choices=["sample", "score"])
    args = parser.parse_args(argv)

    # 어떤 뉴스 파일로 만든 검수인지 파일명 앞 번호(예: 04)를 붙여 구분한다.
    data_id = NEWS_CSV.name.split("_")[0]
    review_path = LABELS_DIR / f"tag_review_{RULE_VERSION}_{data_id}.csv"
    if args.step == "sample":
        sample = build_review_sample(NEWS_CSV, ANALYSIS_START, ANALYSIS_END, REVIEW_TARGETS)
        sample.to_csv(review_path, index=False, encoding="utf-8-sig")
        print(f"검수 표본 {len(sample)}건 → {review_path}")
    else:
        table = precision_table(pd.read_csv(review_path, encoding="utf-8-sig"))
        out = OUTPUTS_DIR / "reports" / f"tag_precision_{RULE_VERSION}_{data_id}.csv"
        table.to_csv(out, index=False, encoding="utf-8-sig")
        print(table.to_string(index=False))


if __name__ == "__main__":
    main()
