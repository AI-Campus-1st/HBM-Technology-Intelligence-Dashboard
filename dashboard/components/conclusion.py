"""
'한눈에 보는 결론' 문장 생성 (애널리스트 관점).

현재 화면에서는 쓰지 않는다 (2026-11-20): 결론은 한도윤이 만드는 별도 요약 페이지가 맡기로 해 이슈 분석 화면에서 뺐다.
숫자 계산(compute_facts)과 원문 대조를 마친 공시 인용(EVIDENCE_HIGHLIGHTS)은 요약 페이지가 재사용할 수 있게 남겨 둔다 (리포트 6.5).

형식은 초안 v1.2 §1.4 '상단 결론 문장 형식'을 따른다:
  ① 보도 비중의 정점과 추세 → ② 기업별 보도 점유·논조 차이 → ③ 공시로 확인된 사실 → ④ 확인할 수 없는 것·신뢰도.

숫자는 저장된 분석 결과(SQL 02·03·04, 급증 구간, 검수 결과, 실적 공시 전후 기사 수)에서 그때그때 계산한다 (compute_facts).
→ 분석을 다시 돌려 결과가 바뀌면 문장 속 숫자도 따라 바뀐다. 문장에 숫자를 직접 적지 않는다. 화면에서는 굵은 글씨로 구분한다.
사람의 판단이 필요한 부분만 아래 상수·문장으로 고정한다 (두 사람이 검토해 승인):
- CONFIRMED_EVENTS: 공시로 확인한 급증 4구간의 사건 이름 (리포트 3.5 사건 요약 '확정' 행에서 요약)
- EVIDENCE_HIGHLIGHTS: 결론에 인용하는 공시 첨부 PDF 원문 (쪽 번호 포함). verified=1(사람이 확인한 공시)이면서
  문구가 그 쪽 텍스트에 그대로 있는지 테스트가 검사한다. 단(현황/전망) 위치는 PDF를 직접 보고 section에 적었다.
- 해석 문장 (보도 데이터의 한계 등)
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

# 2026-11-20 원문 대조: DART 공시(영업(잠정)실적)에 첨부된 실적발표 PDF의 해당 쪽을 열어 문구·기업·기간을 확인했다.
# excerpts = [(쪽, 원문)] — 원문은 PDF 글자 그대로 둔다 (테스트가 공백만 무시하고 대조).
# SK '24.3Q의 'QoQ +70% 이상'은 SK하이닉스 자체 자료다. 같은 시기 삼성전자의 'HBM 매출 70% 이상 성장'은
# 10-31 콘퍼런스콜 발언(기사 출처)이며 삼성 첨부 자료에는 그 숫자가 없다 — 두 회사 발표를 섞지 않는다.
EVIDENCE_HIGHLIGHTS = [
    {"rcept_no": "20241024800002", "corp": "SK하이닉스", "date": "2024-10-24", "period": "2024년 3분기",
     "doc": "2024년 3분기 실적발표 자료", "section": "",
     "excerpts": [(5, "HBM 매출 QoQ +70% 이상, YoY +330% 이상")]},
    {"rcept_no": "20260128800709", "corp": "SK하이닉스", "date": "2026-01-28", "period": "2025년 4분기·연간",
     "doc": "2025년 실적발표 자료", "section": "",
     "excerpts": [(8, "’25년 HBM 매출 전년 대비 2배 이상 확대"), (13, "HBM4는 고객과 협의한 일정에 따라 현재 양산 진행 중")]},
    {"rcept_no": "20250430800069", "corp": "삼성전자", "date": "2025-04-30", "period": "2025년 1분기",
     "doc": "2025년 1분기 경영설명회 자료", "section": "'25.1분기 현황",
     "excerpts": [(8, "첨단 반도체 수출 통제 영향 등에 따른 HBM 판매 감소 및 가격하락에 따른 실적 영향 有")]},
]


def _quarter(month: str) -> str:
    return f"{month[:4]}Q{(int(month[5:7]) - 1) // 3 + 1}"


def compute_facts(monthly: pd.DataFrame, issues: pd.DataFrame, coverage: pd.DataFrame,
                  sentiment: pd.DataFrame, evaluation: dict, earnings: pd.DataFrame | None = None) -> dict:
    """결론 문장에 들어갈 숫자 (전체 기간). 모두 입력 표에서 계산하며 사람이 고친 값은 없다.

    Args:
        monthly: SQL 02 (month, partial, share, ...)   issues: 급증 구간 + status(확정/제외)
        coverage: SQL 03 (period, skh_share, sec_share) — 정규식 기업 태그 기준 점유 (한 기사에 두 기업이 함께 나오면 둘 다 센다)
        sentiment: SQL 04 (month, company, positive, neutral, negative, articles) — LLM 감성, articles = 그 기업이 등장한 기사
        evaluation: issue_loader.eval_summary() {기업: {accuracy, n, macro_f1, ...}}
        earnings: issue_loader.earnings_news_counts() (corp_name, releases, articles). 없으면 뉴스·공시 비교 문장을 뺀다.

    정의 메모 (화면 문장과 같은 정의):
        recent_share = 마지막 부분 월이 아닌 3개월 비중의 단순 평균 (기사 수 가중 아님)
        neg_share = 전체 기간(부분 월 포함) 부정 합계 / 등장 기사 합계
        삼성 분기 순감성 = (긍정 − 부정) / 등장 기사, 기사 5건 이상 분기만. 바닥 = 최소, 반등 = 바닥 이후 최대
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
    q_n = q["articles"].astype(int)
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
        "neg_counts": {c: (int(r["negative"]), int(r["articles"])) for c, r in totals.iterrows()},
        "sec_trough": (trough_q, float(q_net[trough_q])) if trough_q else None,
        "sec_trough_n": int(q_n[trough_q]) if trough_q else 0,
        "sec_rebound": (rebound_q, float(q_net[rebound_q])) if rebound_q else None,
        "sec_rebound_n": int(q_n[rebound_q]) if rebound_q else 0,
        "accuracy": {c: float(e["accuracy"]) for c, e in evaluation.items()},
        "macro_f1": {c: float(e["macro_f1"]) for c, e in evaluation.items() if "macro_f1" in e},
        "eval_n_by": {c: int(e["n"]) for c, e in evaluation.items()},
        "eval_n": int(next(iter(evaluation.values()))["n"]) if evaluation else 0,
        "earnings": ({r["corp_name"]: (int(r["articles"]), int(r["releases"])) for _, r in earnings.iterrows()}
                     if earnings is not None else None),
    }


def _pct(v: float) -> str:
    return f"{v:.0%}"


def _b(text: str) -> str:
    """자동 계산한 값 표시 (굵게). 고정 문구와 구분하기 위해 계산값에만 쓴다."""
    return f"<b>{text}</b>"


def _quote_html(h: dict, links: dict) -> str:
    """공시 인용 1건: 기업·자료·접수일 링크 + (단) + 쪽별 원문."""
    label = f"{h['corp']} {h['doc']}({h['date']} 공시)"
    url = links.get(h["rcept_no"])
    label = f'<a href="{esc(url)}" target="_blank" rel="noopener">{esc(label)} ↗</a>' if url else f"{esc(label)} (공시 링크 없음)"
    section = f" {esc(h['section'])}" if h.get("section") else ""
    parts = " · ".join(f"“{esc(t)}”(p.{p})" for p, t in h["excerpts"])
    return f"{label}{section}의 {parts}"


def conclusion_html(f: dict, evidence_links: pd.DataFrame) -> str:
    """결론 카드 HTML. evidence_links: rcept_no·url (EVIDENCE_HIGHLIGHTS의 DART 링크).

    굵은 글씨 = compute_facts가 계산한 값, “ ” = 공시 원문, 나머지 문장 = 두 사람이 검토해 고정한 해석.
    """
    links = dict(zip(evidence_links["rcept_no"], evidence_links["url"])) if len(evidence_links) else {}
    neg, cnt = f["neg_share"], f.get("neg_counts", {})

    def neg_txt(c: str) -> str:
        n = cnt.get(c)
        share = _pct(neg.get(c, float("nan")))
        return _b(f"{share}({n[0]}/{n[1]})" if n else share)

    turn = ""
    if f["sec_trough"] and f["sec_rebound"]:
        (tq, tv), (rq, rv) = f["sec_trough"], f["sec_rebound"]
        tn, rn = f.get("sec_trough_n", 0), f.get("sec_rebound_n", 0)
        trough, rebound = _b(f"{tq} {tv:+.2f}({tn}건)"), _b(f"{rq} {rv:+.2f}({rn}건)")
        turn = (f" 다만 삼성전자 분기 순감성((긍정−부정)/등장 기사, 기사 5건 이상 분기)은 "
                f"{trough} 바닥 이후 {rebound}까지 올라 긍정으로 돌아섰다.")
    again = f"{_b(str(f['later_spikes']))}차례 다시 급증했고, " if f["later_spikes"] else ""
    s1 = (f"HBM 보도 비중은 {_b(esc(f['peak_month']) + '에 ' + format(f['peak_share'], '.1%'))}로 정점을 찍은 뒤 {again}"
          f"최근 3개월({esc(f['recent_months'])}) 평균은 {_b(format(f['recent_share'], '.1%'))}로 낮아졌다.")
    s2 = (f"공시로 확인된 급증 {_b(str(f['confirmed']))}구간({esc(CONFIRMED_EVENTS)})에서 HBM 기사 중 삼성전자가 등장한 비율은 "
          f"{_b(_pct(f['sec_share_min'])[:-1] + '–' + _pct(f['sec_share_max']))}로 급증 구간 밖({_b(_pct(f['outside_sec']))})보다 높았다"
          f"(정규식 기업 태그 기준). LLM이 판정한 부정 비율(그 기업이 등장한 기사 중 부정, 전체 기간)도 삼성전자 "
          f"{neg_txt('삼성전자')}가 SK하이닉스 {neg_txt('SK하이닉스')}보다 높았다.{turn}")
    s3 = "공시 첨부 실적 자료에서는 " + ", ".join(_quote_html(h, links) for h in EVIDENCE_HIGHLIGHTS) + "가 확인된다."
    earn = f.get("earnings")
    if earn and "SK하이닉스" in earn and "삼성전자" in earn:
        (sk_a, sk_r), (sec_a, sec_r) = earn["SK하이닉스"], earn["삼성전자"]
        s3 += (f" 반면 수집한 뉴스에서 각 회사 분기 실적 공시 전후(D-1–D+3) 제목에 실적·매출·영업이익이 들어간 HBM 기사는 "
               f"SK하이닉스 {_b(f'{sk_a}건')}(실적 공시 {sk_r}회), 삼성전자 {_b(f'{sec_a}건')}({sec_r}회)이었다. "
               f"이 뉴스는 반도체 R&amp;D·수출 통제·밸류체인 등 키워드로 수집해 실적 기사가 적게 담겼을 수 있으므로, "
               f"이 데이터의 보도량·점유만으로 SK하이닉스의 HBM 실적을 판단하기는 어렵다(언론 전체 보도량을 뜻하지는 않는다).")
    acc = " · ".join(
        f"{c} {a:.2f}" + (f"(Macro-F1 {f['macro_f1'][c]:.2f})" if c in f.get("macro_f1", {}) else "")
        for c, a in f["accuracy"].items())
    ns = set(f.get("eval_n_by", {}).values()) or {f["eval_n"]}
    n_txt = f"기업별 사람 라벨 {next(iter(ns))}건" if len(ns) == 1 else \
        "사람 라벨 " + " · ".join(f"{c} {n}건" for c, n in f["eval_n_by"].items())
    s4 = (f"단, <b>HBM 투자액</b>은 공시로 확인할 수 없고(R&amp;D·시설투자는 회사 전체 금액), 감성은 LLM 판정이다: "
          f"사람 라벨과 4분류 일치율(정확도) {_b(acc)}, {n_txt}이며 같은 표본으로 프롬프트를 조정해 실제보다 높게 나왔을 수 있다. "
          f"보도 비중·점유는 시장 점유율이나 실적이 아니다.")
    legend = "읽는 법: <b>굵은 글씨</b>는 저장된 분석 결과에서 화면을 열 때마다 자동 계산한 값, “ ”는 공시 원문(쪽 번호), 나머지 문장은 두 사람이 검토해 고정한 해석이다."
    body = "".join(f"<p style='margin:0 0 10px'>{s}</p>" for s in (s1, s2, s3))
    small = "font-size:13px; color:var(--text-2)"
    return (f'<div class="qa-answer" style="box-shadow: inset 3px 0 0 var(--green), var(--shadow)">'
            f'<div class="q">한눈에 보는 결론 · 전체 기간 {esc(f["period"])} 기준 · 아래 필터와 무관</div>'
            f'<div class="a" style="font-size:16px; white-space:normal">{body}'
            f'<p style="margin:0 0 6px; {small}">{s4}</p>'
            f'<p style="margin:0; {small}">{legend}</p></div></div>')
