"""
요약(첫 화면) 조각: "이 산업에서 지금 무슨 일이 일어나고 있으며, 그 판단의 근거는 무엇인가"에 한 화면으로 답한다.

화면 순서 (리포트 6.5):
  ① 질문(제목) → ② 한 줄 답 → ③ 근거 카드 3장(무슨 일 / 누구 이야기 / 공시로 확인된 사실) → ④ 한계 한 줄
숫자는 conclusion.compute_facts(저장된 분석 결과에서 계산)를 그대로 쓰고, 이 파일은 보여 주는 방식만 맡는다.
사람의 판단은 JUDGMENT 한 문장과 conclusion.CONFIRMED_EVENTS·EVIDENCE_HIGHLIGHTS(사람이 확인한 공시)뿐이다.

담당: 공동 (한도윤 작성, 문구는 김한승과 합의)
일정: Day 7
"""

import math

import pandas as pd

from dashboard.components import conclusion as cc
from dashboard.components.qa_view import esc

QUESTION = "HBM에서 지금 무슨 일이 일어나고 있고, 그 근거는 무엇인가"
# 한 줄 답의 판단 부분 (숫자 없이). 근거 카드 ②·③이 이 판단을 받친다.
JUDGMENT = "보도는 삼성전자 사건에 몰렸지만, HBM 실적 성장은 SK하이닉스 공시에서 확인된다."

ISSUE_PAGE = "이슈_분석"   # app.py의 url_path와 같아야 한다 (테스트가 확인)
QA_PAGE = "공시_QA"

SUMMARY_CSS = """
<style>
.sm-headline { font-size: 22px; font-weight: 700; line-height: 1.5; color: var(--text); margin-top: 12px; }
.sm-headline b { color: var(--green); }
.sm-cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin: 4px 0 14px; }
.sm-card { background: var(--surface); border-radius: 8px; padding: 18px 20px; display: flex; flex-direction: column; }
.sm-k { font-size: 12px; font-weight: 700; letter-spacing: 1.2px; color: var(--text-2); }
.sm-big { font-size: 30px; font-weight: 800; color: var(--text); line-height: 1.2; margin-top: 6px;
          font-variant-numeric: tabular-nums; }
.sm-big small { display: block; font-size: 13px; font-weight: 600; color: var(--text-2); margin-top: 2px; }
.sm-text { font-size: 14px; color: var(--text-3); line-height: 1.6; margin-top: 8px; }
.sm-text b { color: var(--text); }
.sm-list { margin: 8px 0 0; padding-left: 18px; font-size: 13px; color: var(--text-3); line-height: 1.6; }
.sm-list a { color: var(--text); }
.sm-spark { margin-top: 10px; }
.sm-go { margin-top: auto; padding-top: 12px; font-size: 13px; }
.sm-go a { color: var(--green); text-decoration: none; font-weight: 700; }
.sm-limit { font-size: 13px; color: var(--text-2); line-height: 1.6; padding: 12px 16px; border-radius: 8px;
            background: var(--surface); margin-bottom: 20px; }
@media (max-width: 900px) { .sm-cards { grid-template-columns: 1fr; } .sm-headline { font-size: 18px; } }
</style>
"""


def _pct(v: float) -> str:
    return "-" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.0%}"


def _go(page: str, label: str) -> str:
    return f'<a href="{page}" target="_self">{esc(label)} →</a>'


def sparkline_svg(monthly: pd.DataFrame, peak_month: str, width: int = 260, height: int = 54) -> str:
    """월별 HBM 비중 작은 추이선 (부분 월 제외) + 정점 점. 데이터가 2개 미만이면 빈 문자열."""
    m = monthly[monthly["partial"] == 0].sort_values("month")
    if len(m) < 2:
        return ""
    ys = m["share"].astype(float).tolist()
    top = max(ys) or 1.0
    xs = [i * (width - 8) / (len(ys) - 1) + 4 for i in range(len(ys))]
    pts = [(x, height - 4 - y / top * (height - 8)) for x, y in zip(xs, ys)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    months = m["month"].tolist()
    dot = ""
    if peak_month in months:
        px, py = pts[months.index(peak_month)]
        dot = f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.5" fill="var(--green)"/>'
    return (f'<svg class="sm-spark" viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img" '
            f'aria-label="월별 HBM 보도 비중 추이, {esc(peak_month)} 정점">'
            f'<polyline points="{line}" fill="none" stroke="var(--text-2)" stroke-width="1.5"/>{dot}</svg>')


def hero_html(f: dict) -> str:
    """① 질문 + ② 한 줄 답. 앞 문장은 계산값, 뒤 문장(JUDGMENT)은 사람의 판단."""
    again = f"{f['later_spikes']}차례 다시 급증한 뒤 " if f["later_spikes"] else ""
    answer = (f"HBM 보도는 <b>{esc(f['peak_month'])} 정점({f['peak_share']:.1%})</b> 이후 {again}"
              f"최근 3개월 평균 {f['recent_share']:.1%}로 식었다. {esc(JUDGMENT)}")
    return ('<div class="qa-hero">'
            f'<div class="qa-eyebrow">한눈에 보는 결론 · 전체 기간 {esc(f["period"])} · 저장된 분석 결과에서 계산</div>'
            f'<div class="qa-title">{esc(QUESTION)}</div>'
            f'<div class="sm-headline">{answer}</div></div>')


def cards_html(f: dict, monthly: pd.DataFrame, evidence_links: pd.DataFrame) -> str:
    """③ 근거 카드 3장: 무슨 일이 있었나 / 누구 이야기인가 / 공시로 확인된 사실."""
    events = "".join(f"<li>{esc(e.strip())}</li>" for e in cc.CONFIRMED_EVENTS.split(","))
    c1 = ('<div class="sm-card"><div class="sm-k">① 무슨 일이 있었나</div>'
          f'<div class="sm-big">{f["peak_share"]:.1%} <small>{esc(f["peak_month"])} 보도 비중 정점</small></div>'
          f'{sparkline_svg(monthly, f["peak_month"])}'
          f'<div class="sm-text">공시로 확인된 급증 <b>{f["confirmed"]}구간</b> (전체 {f["issues"]}구간 중)</div>'
          f'<ul class="sm-list">{events}</ul>'
          f'<div class="sm-go">{_go(ISSUE_PAGE, "보도 비중·급증 구간 보기")}</div></div>')

    neg = f["neg_share"]
    turn = ""
    if f["sec_trough"] and f["sec_rebound"]:
        (tq, tv), (rq, rv) = f["sec_trough"], f["sec_rebound"]
        turn = f" 삼성전자 논조는 <b>{esc(tq)}({tv:+.2f})</b> 바닥 뒤 <b>{esc(rq)}({rv:+.2f})</b>로 반등했다."
    c2 = ('<div class="sm-card"><div class="sm-k">② 누구 이야기인가</div>'
          f'<div class="sm-big">{_pct(f["sec_share_min"])[:-1]}–{_pct(f["sec_share_max"])} '
          '<small>급증 구간의 삼성전자 보도 점유</small></div>'
          f'<div class="sm-text">평소(급증 구간 밖) {_pct(f["outside_sec"])}보다 높다. 부정 보도 비율은 삼성전자 '
          f'<b>{_pct(neg.get("삼성전자"))}</b>, SK하이닉스 <b>{_pct(neg.get("SK하이닉스"))}</b>.{turn}</div>'
          f'<div class="sm-go">{_go(ISSUE_PAGE, "기업 점유·감성 추이 보기")}</div></div>')

    links = dict(zip(evidence_links["rcept_no"], evidence_links["url"])) if len(evidence_links) else {}
    quotes = []
    for h in cc.EVIDENCE_HIGHLIGHTS:
        label = f"{h['corp']} {h['doc']} ({h['date']})"
        url = links.get(h["rcept_no"])
        label = (f'<a href="{esc(url)}" target="_blank" rel="noopener">{esc(label)} ↗</a>' if url
                 else f"{esc(label)} (공시 링크 없음)")
        quotes.append(f"<li>{label}<br>‘{esc(h['quote'])}’</li>")
    c3 = ('<div class="sm-card"><div class="sm-k">③ 공시로 확인된 사실</div>'
          f'<ul class="sm-list">{"".join(quotes)}</ul>'
          '<div class="sm-text">SK하이닉스의 HBM 실적 호조는 공시에는 있지만 수집한 뉴스에는 실적 보도가 거의 없다. '
          '보도량만 보면 SK하이닉스의 성과를 과소평가할 수 있다.</div>'
          f'<div class="sm-go">{_go(QA_PAGE, "공시에 직접 물어보기")}</div></div>')
    return f'<div class="sm-cards">{c1}{c2}{c3}</div>'


def limits_html(f: dict) -> str:
    """④ 한계 한 줄."""
    acc = " · ".join(f"{c} {a:.2f}" for c, a in f["accuracy"].items()) or "결과 없음"
    return ('<div class="sm-limit"><b>한계</b> · HBM 투자액은 공시로 확인할 수 없다(R&amp;D·시설투자는 회사 전체 금액) · '
            f'감성은 LLM 판정(정확도 {esc(acc)}, 표본 {f["eval_n"]}건) · 보도 비중·점유는 시장 점유율이나 실적이 아니다.</div>')
