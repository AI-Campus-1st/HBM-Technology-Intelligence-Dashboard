"""
대시보드 '한눈에 보는 결론' (애널리스트 관점)의 숫자 계산. 첫 화면 '요약'(pages/0_요약.py, components/summary.py)이 쓴다 (리포트 6.5).

형식은 초안 v1.2 §1.4 '상단 결론 문장 형식'을 따른다:
  ① 보도 비중의 정점과 추세 → ② 기업별 보도 점유·논조 차이 → ③ 공시로 확인된 사실 → ④ 확인할 수 없는 것·신뢰도.

숫자는 저장된 분석 결과(SQL 02·03·04, 급증 구간, 검수 결과)에서 그때그때 계산한다 (compute_facts).
→ 분석을 다시 돌려 결과가 바뀌면 문장 속 숫자도 따라 바뀐다. 문장에 숫자를 직접 적지 않는다.
사람의 판단이 필요한 부분만 아래 상수로 고정한다:
- CONFIRMED_EVENTS: 공시로 확인한 급증 4구간의 사건 이름 (리포트 3.5 사건 요약 '확정' 행에서 요약)
- EVIDENCE_HIGHLIGHTS: 결론에 인용하는 공시 첨부 PDF 원문 (쪽 번호 포함). verified=1(사람이 확인한 공시)이면서
  문구가 그 쪽 텍스트에 그대로 있는지 테스트가 검사한다 (리포트 6.5.1)
결론은 필터와 무관하게 전체 분석 기간 기준이다 (화면에 표시).
범위 표기는 '~' 대신 '–'를 쓴다 (Streamlit 마크다운에서 '~' 두 개가 취소선으로 바뀐다).

담당: 공동 (초안 김한승, 문구는 한도윤과 합의 후 확정)
일정: Day 7
"""

import pandas as pd

from src.common import config

REVIEW_PATH = config.LABELS_DIR / "issue_evidence_review_v1.csv"
OUTSIDE = "(급증 구간 밖)"

CONFIRMED_EVENTS = "삼성전자 3분기 실적·HBM3E 진전, 미국의 대중 HBM 수출 통제, 삼성전자 1분기 'HBM 쇼크', 삼성전자 HBM4 반등"

# 2026-11-20 원문 대조 (리포트 6.5.1): DART 공시(영업(잠정)실적)에 첨부된 실적발표 PDF의 해당 쪽을 열어 기업·기간·지표·수치를 확인했다.
# quote = 화면에 보이는 인용(원문 그대로, 쪽이 다르면 ' / '로 잇는다), excerpts = [(쪽, 원문)] — 테스트가 PDF 쪽 텍스트와 대조한다.
# SK '24.3Q의 'QoQ +70% 이상'은 SK하이닉스 자체 자료다. 같은 시기 삼성전자의 'HBM 매출 70% 이상 성장'은
# 10-31 콘퍼런스콜 발언(기사 출처)이며 삼성 첨부 자료에는 그 숫자가 없다 — 두 회사 발표를 섞지 않는다.
# 삼성 '25.1Q 문구는 '25.1분기 현황 단에 있다 (추출 텍스트는 단 순서가 섞여 PDF를 직접 보고 확인).
EVIDENCE_HIGHLIGHTS = [
    {"rcept_no": "20241024800002", "corp": "SK하이닉스", "date": "2024-10-24", "doc": "2024년 3분기 실적발표 자료 p.5",
     "quote": "HBM 매출 QoQ +70% 이상, YoY +330% 이상",
     "excerpts": [(5, "HBM 매출 QoQ +70% 이상, YoY +330% 이상")]},
    {"rcept_no": "20260128800709", "corp": "SK하이닉스", "date": "2026-01-28", "doc": "2025년 실적발표 자료 p.8·13",
     "quote": "’25년 HBM 매출 전년 대비 2배 이상 확대 / HBM4는 고객과 협의한 일정에 따라 현재 양산 진행 중",
     "excerpts": [(8, "’25년 HBM 매출 전년 대비 2배 이상 확대"), (13, "HBM4는 고객과 협의한 일정에 따라 현재 양산 진행 중")]},
    {"rcept_no": "20250430800069", "corp": "삼성전자", "date": "2025-04-30", "doc": "2025년 1분기 경영설명회 자료 p.8 ('25.1분기 현황)",
     "quote": "첨단 반도체 수출 통제 영향 등에 따른 HBM 판매 감소 및 가격하락에 따른 실적 영향 有",
     "excerpts": [(8, "첨단 반도체 수출 통제 영향 등에 따른 HBM 판매 감소 및 가격하락에 따른 실적 영향 有")]},
]


def _quarter(month: str) -> str:
    return f"{month[:4]}Q{(int(month[5:7]) - 1) // 3 + 1}"


def compute_facts(monthly: pd.DataFrame, issues: pd.DataFrame, coverage: pd.DataFrame,
                  sentiment: pd.DataFrame, evaluation: dict) -> dict:
    """결론 문장에 들어갈 숫자 (전체 기간).

    Args:
        monthly: SQL 02 (month, partial, share, ...)   issues: 급증 구간 + status(확정/제외)
        coverage: SQL 03 (period, skh_share, sec_share)  sentiment: SQL 04 (month, company, positive, neutral, negative, articles)
        evaluation: issue_loader.eval_summary() {기업: {accuracy, n, ...}}
    """
    full = monthly[monthly["partial"] == 0].sort_values("month")
    peak = full.loc[full["share"].idxmax()]
    recent = full.tail(3)

    confirmed_rows = issues[issues["status"] == "확정"]
    confirmed = confirmed_rows["issue_id"]
    later = int((confirmed_rows["start_date"].str[:7] > peak["month"]).sum())  # 정점 이후 다시 급증한 확정 구간 수
    cov = coverage.set_index("period")
    inside = cov.loc[cov.index.intersection(confirmed)]
    outside = cov.loc[OUTSIDE] if OUTSIDE in cov.index else None

    totals = sentiment.groupby("company")[["positive", "negative", "articles"]].sum()
    neg_share = (totals["negative"] / totals["articles"]).to_dict()

    sec = sentiment[sentiment["company"] == "삼성전자"].assign(q=lambda d: d["month"].map(_quarter))
    q = sec.groupby("q")[["positive", "negative", "articles"]].sum()
    q = q[q["articles"] >= 5]                                   # 기사 몇 건뿐인 분기는 추세 판단에서 뺀다
    q_net = ((q["positive"] - q["negative"]) / q["articles"]).sort_index()
    trough_q = q_net.idxmin() if len(q_net) else None
    after = q_net[q_net.index > trough_q] if trough_q else q_net.iloc[0:0]
    rebound_q = after.idxmax() if len(after) else None

    return {
        "period": f"{config.ANALYSIS_START:%Y-%m-%d}–{config.ANALYSIS_END:%Y-%m-%d}",
        "peak_month": peak["month"], "peak_share": float(peak["share"]), "later_spikes": later,
        "recent_months": f"{recent['month'].iloc[0]}–{recent['month'].iloc[-1]}",
        "recent_share": float(recent["share"].mean()),
        "confirmed": len(confirmed), "issues": len(issues),
        "sec_share_min": float(inside["sec_share"].min()) if len(inside) else float("nan"),
        "sec_share_max": float(inside["sec_share"].max()) if len(inside) else float("nan"),
        "skh_share_max": float(inside["skh_share"].max()) if len(inside) else float("nan"),
        "outside_sec": float(outside["sec_share"]) if outside is not None else float("nan"),
        "outside_skh": float(outside["skh_share"]) if outside is not None else float("nan"),
        "neg_share": neg_share,
        "sec_trough": (trough_q, float(q_net[trough_q])) if trough_q else None,
        "sec_rebound": (rebound_q, float(q_net[rebound_q])) if rebound_q else None,
        "accuracy": {c: float(e["accuracy"]) for c, e in evaluation.items()},
        "eval_n": int(next(iter(evaluation.values()))["n"]) if evaluation else 0,
    }
