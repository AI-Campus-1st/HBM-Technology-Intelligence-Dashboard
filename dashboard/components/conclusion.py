"""
대시보드 상단 '한눈에 보는 결론' (애널리스트 관점). 이슈 분석 첫 화면 맨 위에 둔다 (리포트 6.3, #56 결정).

형식은 초안 v1.2 §1.4 '상단 결론 문장 형식'을 따른다:
  ① 보도 비중의 정점과 추세 → ② 기업별 보도 점유·논조 차이 → ③ 공시로 확인된 사실 → ④ 확인할 수 없는 것·신뢰도.

숫자는 저장된 분석 결과(SQL 02·03·04, 급증 구간, 검수 결과)에서 그때그때 계산한다 (compute_facts).
→ 분석을 다시 돌려 결과가 바뀌면 문장 속 숫자도 따라 바뀐다. 문장에 숫자를 직접 적지 않는다.
사람의 판단이 필요한 부분만 아래 상수로 고정한다:
- CONFIRMED_EVENTS: 공시로 확인한 급증 4구간의 사건 이름 (리포트 3.5 사건 요약 '확정' 행에서 요약)
- EVIDENCE_HIGHLIGHTS: 결론에 인용하는 공시 문구 (data/labels/issue_evidence_review_v1.csv에서 verified=1인 공시의 확인 메모 인용,
  테스트가 '사람이 확인한 공시만 인용'을 검사한다)
결론은 필터와 무관하게 전체 분석 기간 기준이다 (화면에 표시).
범위 표기는 '~' 대신 '–'를 쓴다 (Streamlit 마크다운에서 '~' 두 개가 취소선으로 바뀐다).

담당: 공동 (초안 김한승, 문구는 한도윤과 합의 후 확정)
일정: Day 7
"""

import pandas as pd

from dashboard.components.qa_view import esc
from src.common import config

REVIEW_PATH = config.LABELS_DIR / "issue_evidence_review_v1.csv"
OUTSIDE = "(급증 구간 밖)"

CONFIRMED_EVENTS = "삼성전자 3분기 실적·HBM3E 진전, 미국의 대중 HBM 수출 통제, 삼성전자 1분기 'HBM 쇼크', 삼성전자 HBM4 반등"

EVIDENCE_HIGHLIGHTS = [
    {"rcept_no": "20241024800002", "corp": "SK하이닉스", "date": "2024-10-24", "doc": "3분기 실적 발표 자료",
     "quote": "HBM 매출 전 분기 대비 70% 이상, 전년 대비 330% 이상 증가"},
    {"rcept_no": "20260128800709", "corp": "SK하이닉스", "date": "2026-01-28", "doc": "4분기 실적 발표 자료",
     "quote": "2025년 HBM 매출 2배 이상, HBM4 양산 진행 중"},
    {"rcept_no": "20250430800069", "corp": "삼성전자", "date": "2025-04-30", "doc": "1분기 실적 발표 자료",
     "quote": "수출 통제 등으로 HBM 판매 감소"},
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


def _pct(v: float) -> str:
    return f"{v:.0%}"


def conclusion_html(f: dict, evidence_links: pd.DataFrame) -> str:
    """결론 카드 HTML. evidence_links: rcept_no·url (EVIDENCE_HIGHLIGHTS의 DART 링크)."""
    links = dict(zip(evidence_links["rcept_no"], evidence_links["url"])) if len(evidence_links) else {}
    neg = f["neg_share"]
    turn = ""
    if f["sec_trough"] and f["sec_rebound"]:
        (tq, tv), (rq, rv) = f["sec_trough"], f["sec_rebound"]
        turn = f" 다만 삼성전자 논조는 {tq}(순감성 {tv:+.2f}) 바닥 이후 {rq}({rv:+.2f})까지 긍정으로 돌아섰다."
    again = f"{f['later_spikes']}차례 다시 급증했고, " if f["later_spikes"] else ""
    s1 = (f"HBM 보도 비중은 <b>{esc(f['peak_month'])}에 {f['peak_share']:.1%}</b>로 정점을 찍은 뒤 {again}"
          f"최근 3개월({esc(f['recent_months'])}) 평균은 {f['recent_share']:.1%}로 낮아졌다.")
    s2 = (f"공시로 확인된 급증 {f['confirmed']}구간({esc(CONFIRMED_EVENTS)})에서 HBM 기사의 삼성전자 점유는 "
          f"<b>{_pct(f['sec_share_min'])[:-1]}–{_pct(f['sec_share_max'])}</b>로 평소({_pct(f['outside_sec'])})보다 높았고, "
          f"부정 보도 비율도 삼성전자 {_pct(neg.get('삼성전자', float('nan')))}가 SK하이닉스 "
          f"{_pct(neg.get('SK하이닉스', float('nan')))}보다 높았다.{turn}")
    quotes = []
    for h in EVIDENCE_HIGHLIGHTS:
        label = f"{h['corp']} {h['doc']}({h['date']})"
        url = links.get(h["rcept_no"])
        label = f'<a href="{esc(url)}" target="_blank" rel="noopener">{esc(label)} ↗</a>' if url else f"{esc(label)} (공시 링크 없음)"
        quotes.append(f"{label}의 ‘{esc(h['quote'])}’")
    s3 = ("공시에서는 " + ", ".join(quotes) + "가 확인된다. SK하이닉스의 HBM 실적 호조는 공시에는 있으나 "
          "수집한 뉴스에서는 실적 보도가 거의 없어, 보도량만으로는 SK하이닉스의 성과가 덜 드러난다.")
    acc = " · ".join(f"{c} {a:.2f}" for c, a in f["accuracy"].items())
    s4 = (f"단, <b>HBM 투자액</b>은 공시로 확인할 수 없고(R&amp;D·시설투자는 회사 전체 금액), 감성은 LLM 판정(정확도 {acc}, "
          f"표본 {f['eval_n']}건)이며, 보도 비중·점유는 시장 점유율이나 실적이 아니다.")
    body = "".join(f"<p style='margin:0 0 10px'>{s}</p>" for s in (s1, s2, s3))
    return (f'<div class="qa-answer" style="box-shadow: inset 3px 0 0 var(--green), var(--shadow)">'
            f'<div class="q">한눈에 보는 결론 · 전체 기간 {esc(f["period"])} 기준 · 아래 필터와 무관</div>'
            f'<div class="a" style="font-size:16px; white-space:normal">{body}'
            f'<p style="margin:0; font-size:13px; color:var(--text-2)">{s4}</p></div></div>')
