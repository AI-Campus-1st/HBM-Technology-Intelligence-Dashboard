"""
질문 입력, 답변, 근거 공시 목록 표시 UI.

디자인: Spotify 디자인 문서(getdesign.md, `npx getdesign@latest add spotify`)를 참조한 어두운 테마.
- 배경 #121212, 카드 #181818·#1f1f1f, 본문 흰색, 보조 글자 #b3b3b3
- 초록(#1ed760)은 '질문하기' 버튼·활성 상태·답변 표시 같은 핵심 요소에만 쓰고 장식으로 쓰지 않는다
- 버튼은 알약 모양, 카드는 테두리 없이 배경 명도 차이와 진한 그림자로 구분한다
- 거절은 빨강(#f3727f), 경고는 주황(#ffa42b)
이 CSS는 공시 Q&A 페이지 안에서만 적용한다 (.streamlit/config.toml 공용 테마는 그대로).

HTML 문자열을 만드는 함수(*_html)와 Streamlit에 그리는 함수(render_*)를 나눠 테스트할 수 있게 했다.

담당: 한도윤 (공시 분석)
일정: Day 6
"""

import html
import re

import pandas as pd
import streamlit as st

GREEN = "#1ed760"
EXCERPT_CHARS = 360

THEME_CSS = """
<style>
:root {
  --bg: #121212; --surface: #181818; --surface-2: #1f1f1f; --card: #252525;
  --text: #ffffff; --text-2: #b3b3b3; --text-3: #cbcbcb; --line: #4d4d4d;
  --green: #1ed760; --red: #f3727f; --orange: #ffa42b; --blue: #539df5;
  --shadow: rgba(0,0,0,0.3) 0px 8px 8px; --shadow-heavy: rgba(0,0,0,0.5) 0px 8px 24px;
}
.stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] { background: var(--bg); color: var(--text); }
[data-testid="stSidebar"] { background: #000000; }
[data-testid="stSidebar"] * { color: var(--text-2); }
[data-testid="stSidebarNav"] a[aria-current="page"] span { color: var(--text); font-weight: 700; }
html, body, .stApp, .stApp p, .stApp label, .stApp input, .stApp button, .stApp textarea {
  font-family: "Pretendard", "Noto Sans KR", "Helvetica Neue", Arial, sans-serif;
}
.stApp p, .stApp label, .stApp span, .stApp li { color: var(--text-3); line-height: 1.5; }
.stApp h1, .stApp h2, .stApp h3 { color: var(--text); letter-spacing: -0.01em; line-height: 1.3; }
[data-testid="stCaptionContainer"], .stApp small { color: var(--text-2) !important; }
hr { border-color: #2a2a2a !important; }

/* 입력: 알약 모양 검색창 */
.stApp [data-testid="stTextInput"] input {
  background: var(--surface-2); color: var(--text); border-radius: 500px; padding: 14px 22px;
  border: none; box-shadow: rgb(18,18,18) 0px 1px 0px, rgb(124,124,124) 0px 0px 0px 1px inset;
}
.stApp [data-testid="stTextInput"] input::placeholder { color: #7c7c7c; }
.stApp [data-testid="stTextInput"] input:focus { box-shadow: 0 0 0 2px var(--text) inset; }
.stApp [data-testid="stTextInput"] div[data-baseweb="input"],
.stApp [data-testid="stTextInput"] div[data-baseweb="base-input"] { background: transparent; border: none; }

/* 버튼: 기본은 어두운 알약, 주요 버튼(질문하기)만 초록 */
.stApp .stButton button, .stApp [data-testid="stFormSubmitButton"] button {
  border-radius: 9999px; background: var(--surface-2); color: var(--text); border: none;
  font-weight: 700; font-size: 14px; padding: 8px 18px; transition: background .15s, transform .15s;
}
.stApp .stButton button:hover, .stApp [data-testid="stFormSubmitButton"] button:hover { background: #2a2a2a; color: var(--text); }
.stApp [data-testid="stFormSubmitButton"] button[kind="primaryFormSubmit"], .stApp .stButton button[kind="primary"] {
  background: var(--green); color: #000000; letter-spacing: 0.14px; padding: 12px 18px; white-space: nowrap;
}
.stApp [data-testid="stFormSubmitButton"] button p { color: #000000; font-weight: 700; white-space: nowrap; overflow: visible; }
.stApp [data-testid="stFormSubmitButton"] button[kind="primaryFormSubmit"]:hover { background: #3be477; transform: scale(1.03); }
.stApp [data-testid="stForm"] { border: none; padding: 0; }

/* 알약 선택(예시 질문, 필터) */
.stApp [data-testid="stButtonGroup"] button {
  border-radius: 9999px; background: var(--surface-2); color: var(--text); border: none; font-size: 13px;
}
.stApp [data-testid="stButtonGroup"] button:hover { background: #2a2a2a; color: var(--text); }
.stApp [data-testid="stButtonGroup"] button[aria-checked="true"],
.stApp [data-testid="stButtonGroup"] button[aria-pressed="true"],
.stApp [data-testid="stButtonGroup"] button[data-selected="true"] { background: var(--text) !important; color: #000000; border: none; }
.stApp [data-testid="stButtonGroup"] button[aria-checked="true"] *,
.stApp [data-testid="stButtonGroup"] button[aria-pressed="true"] * { color: #000000; }

/* 토글: 켜짐은 초록 (활성 상태) */
.stApp [data-testid="stCheckbox"] label span, .stApp [data-baseweb="checkbox"] div { color: var(--text-3); }
.stApp [data-baseweb="checkbox"] input:checked + div,
.stApp [data-testid="stCheckbox"] label[data-selected="true"] > span + div { background: var(--green) !important; }

/* 펼치기 */
.stApp [data-testid="stExpander"] details { background: var(--surface); border: none; border-radius: 8px; }
.stApp [data-testid="stExpander"] summary p { color: var(--text); font-weight: 600; }
.stApp [data-testid="stAlert"] { background: var(--surface-2); border-radius: 8px; color: var(--text-3); }

/* 이 페이지 전용 요소 */
.qa-hero { padding: 28px 28px 22px; border-radius: 8px; margin-bottom: 18px;
  background: linear-gradient(180deg, #2a2a2a 0%, var(--bg) 100%); }
.qa-eyebrow { font-size: 12px; font-weight: 700; letter-spacing: 1.6px; text-transform: uppercase; color: var(--text-2); }
.qa-title { font-size: 40px; font-weight: 800; color: var(--text); margin: 6px 0 8px; line-height: 1.1; letter-spacing: -0.02em; }
.qa-sub { font-size: 14px; color: var(--text-2); }
.qa-sub b { color: var(--text); }
.qa-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 4px 0 22px; }
.qa-stat { background: var(--surface); border-radius: 8px; padding: 16px 18px; }
.qa-stat .v { font-size: 26px; font-weight: 800; color: var(--text); line-height: 1.2; font-variant-numeric: tabular-nums; }
.qa-stat .l { font-size: 12px; color: var(--text-2); margin-top: 4px; }
.qa-section { font-size: 24px; font-weight: 700; color: var(--text); margin: 26px 0 12px; }
.qa-answer { background: var(--surface); border-radius: 8px; padding: 22px 24px; box-shadow: var(--shadow); margin: 8px 0 18px; }
.qa-answer .q { font-size: 13px; color: var(--text-2); margin-bottom: 10px; }
.qa-answer .a { font-size: 17px; color: var(--text); line-height: 1.6; white-space: pre-wrap; }
.qa-answer.refused { box-shadow: inset 3px 0 0 var(--red), var(--shadow); }
.qa-answer.refused .a { color: var(--text-3); }
.qa-meta { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 14px; }
.qa-badge { display: inline-block; font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 9999px;
  background: var(--card); color: var(--text-3); }
.qa-badge.ok { background: rgba(30,215,96,0.14); color: var(--green); }
.qa-badge.no { background: rgba(243,114,127,0.14); color: var(--red); }
.qa-badge.saved { background: rgba(83,157,245,0.14); color: var(--blue); }
.qa-cite { display: inline-block; min-width: 20px; padding: 0 6px; margin: 0 1px; border-radius: 9999px;
  background: var(--card); color: var(--text); font-size: 11px; font-weight: 700; text-align: center;
  line-height: 18px; vertical-align: 2px; }
.qa-src { display: flex; gap: 14px; background: var(--surface); border-radius: 8px; padding: 14px 16px;
  margin-bottom: 8px; transition: background .15s; }
.qa-src:hover { background: #222222; }
.qa-src .n { flex: 0 0 34px; height: 34px; border-radius: 50%; background: var(--surface-2); color: var(--text);
  display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 13px; }
.qa-src .body { flex: 1; min-width: 0; }
.qa-src .t { font-size: 15px; font-weight: 700; color: var(--text); }
.qa-src .t a { color: var(--text); text-decoration: none; }
.qa-src .t a:hover { text-decoration: underline; }
.qa-src .m { font-size: 12px; color: var(--text-2); margin-top: 2px; }
.qa-src .x { font-size: 13px; color: var(--text-3); margin-top: 8px; line-height: 1.55; }
.qa-list { background: var(--surface); border-radius: 8px; padding: 6px 0; max-height: 460px; overflow-y: auto; }
.qa-row { display: grid; grid-template-columns: 34px 1fr 110px 92px; gap: 12px; align-items: center;
  padding: 8px 16px; font-size: 13px; color: var(--text-2); }
.qa-row:hover { background: #2a2a2a; }
.qa-row .i { color: var(--text-2); text-align: right; font-variant-numeric: tabular-nums; }
.qa-row .nm a { color: var(--text); text-decoration: none; font-weight: 600; }
.qa-row .nm a:hover { text-decoration: underline; }
.qa-row .nm span { display: block; font-size: 12px; color: var(--text-2); }
.qa-row .d { font-variant-numeric: tabular-nums; }
.qa-row.head { font-size: 11px; letter-spacing: 1.2px; text-transform: uppercase; border-bottom: 1px solid #2a2a2a;
  padding-bottom: 10px; margin-bottom: 4px; }
.qa-row.head:hover { background: transparent; }
.qa-empty { color: var(--text-2); font-size: 14px; padding: 18px; }
@media (max-width: 760px) {
  .qa-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .qa-title { font-size: 30px; }
  .qa-row { grid-template-columns: 28px 1fr 84px; }
  .qa-row .d { display: none; }
}
</style>
"""

_CITE = re.compile(r"\[(\d{1,2})\]")
_HEADER = re.compile(r"^\[[^\]]*\]\n")


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def cite_html(answer: str) -> str:
    """답변 안의 [n] 인용을 작은 동그라미 배지로 바꾼다 (나머지 글자는 이스케이프)."""
    return _CITE.sub(r'<span class="qa-cite">\1</span>', esc(answer))


def excerpt(text: str | None, limit: int = EXCERPT_CHARS) -> str:
    """청크 머리말([기업 | 공시 | 위치])을 떼고 앞부분만. 공백은 한 칸으로."""
    if not text:
        return ""
    body = " ".join(_HEADER.sub("", text).split())
    return body if len(body) <= limit else body[:limit].rstrip() + "…"


def hero_html(manifest: dict | None, reference_date: str) -> str:
    n_docs = manifest["n_disclosures"] if manifest else "-"
    n_chunks = f"{manifest['n_chunks']:,}" if manifest else "-"
    return (
        '<div class="qa-hero"><div class="qa-eyebrow">공시 Q&amp;A · DART 근거 검색</div>'
        '<div class="qa-title">공시에 물어보기</div>'
        f'<div class="qa-sub">SK하이닉스·삼성전자 공시 <b>{esc(n_docs)}건</b>(청크 <b>{esc(n_chunks)}개</b>)에서 '
        f'근거를 찾아 답하고, 근거가 없으면 답하지 않습니다. 기준일 {esc(reference_date)}</div></div>'
    )


def stats_html(manifest: dict | None, summary: dict) -> str:
    items = [
        (manifest["n_disclosures"] if manifest else "-", "RAG 대상 공시"),
        (f"{manifest['n_attachment_chunks']:,}" if manifest else "-", "실적 IR 첨부 청크"),
        (summary.get("전체 정확", "-"), "평가 정확 (24문항)"),
        (summary.get("검색 적중 hit@6 (하이브리드)", "-"), "검색 적중 hit@6"),
    ]
    cells = "".join(f'<div class="qa-stat"><div class="v">{esc(v)}</div><div class="l">{esc(l)}</div></div>'
                    for v, l in items)
    return f'<div class="qa-stats">{cells}</div>'


def answer_html(result, note: str | None = None) -> str:
    """답변 카드. 거절이면 빨간 줄과 거절 이유를 보인다. note는 '저장된 답변 · 생성일' 같은 출처 표시."""
    badges = []
    if result.answerable:
        badges.append('<span class="qa-badge ok">근거 기반 답변</span>')
    else:
        badges.append('<span class="qa-badge no">답변 거절</span>')
        if result.refusal_reason:
            badges.append(f'<span class="qa-badge">{esc(result.refusal_reason)}</span>')
    badges.append(f'<span class="qa-badge">기업 필터: {esc(result.company_filter or "없음 (전체)")}</span>')
    badges.append(f'<span class="qa-badge">검색된 근거 {result.retrieved}개</span>')
    if note:
        badges.append(f'<span class="qa-badge saved">{esc(note)}</span>')
    cls = "qa-answer" if result.answerable else "qa-answer refused"
    return (f'<div class="{cls}"><div class="q">Q. {esc(result.question)}</div>'
            f'<div class="a">{cite_html(result.answer)}</div><div class="qa-meta">{"".join(badges)}</div></div>')


def source_html(src: dict, text: str | None = None) -> str:
    """근거 공시 카드: 번호, 공시명(DART 링크), 기업·제출일·위치·거리, 발췌."""
    title = esc(src.get("report_nm"))
    if src.get("url"):
        title = f'<a href="{esc(src["url"])}" target="_blank" rel="noopener">{title} ↗</a>'
    meta = " · ".join(esc(v) for v in (src.get("corp_name"), src.get("rcept_dt"), src.get("location")) if v)
    meta += f' · 거리 {src.get("distance")}'
    body = excerpt(text)
    x = f'<div class="x">{esc(body)}</div>' if body else ""
    return (f'<div class="qa-src"><div class="n">{esc(src.get("n"))}</div><div class="body">'
            f'<div class="t">{title}</div><div class="m">{meta}</div>{x}</div></div>')


def disclosure_list_html(df: pd.DataFrame) -> str:
    """RAG 대상 공시 목록 (번호, 공시명·기업/유형, 유형, 제출일)."""
    if df.empty:
        return '<div class="qa-list"><div class="qa-empty">조건에 맞는 공시가 없습니다.</div></div>'
    rows = ['<div class="qa-row head"><div class="i">#</div><div>공시</div><div>유형</div><div class="d">제출일</div></div>']
    for i, r in enumerate(df.itertuples(index=False), 1):
        rows.append(
            f'<div class="qa-row"><div class="i">{i}</div>'
            f'<div class="nm"><a href="{esc(r.url)}" target="_blank" rel="noopener">{esc(r.report_nm)}</a>'
            f'<span>{esc(r.corp_name)}</span></div><div>{esc(r.type_name)}</div><div class="d">{esc(r.rcept_dt)}</div></div>'
        )
    return f'<div class="qa-list">{"".join(rows)}</div>'


# ── Streamlit에 그리기 ──
def apply_theme() -> None:
    st.markdown(THEME_CSS, unsafe_allow_html=True)


def render_html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def render_result(result, texts: dict[str, str] | None = None, note: str | None = None) -> None:
    texts = texts or {}
    render_html(answer_html(result, note))
    if result.sources:
        render_html(f'<div class="qa-section" style="font-size:18px">근거 공시 {len(result.sources)}건</div>')
        render_html("".join(source_html(s, texts.get(s.get("chunk_id"))) for s in result.sources))
