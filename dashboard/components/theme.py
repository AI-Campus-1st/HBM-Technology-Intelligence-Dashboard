"""
대시보드 전체 공통 테마 (어두운 테마). 모든 페이지 맨 위에서 apply_theme()를 한 번 부른다.

디자인: Spotify 디자인 문서(getdesign.md, `npx getdesign@latest add spotify`)를 참조했다. 탭 2(공시 Q&A)에서
먼저 만든 테마를 2026-11-19 대시보드 전체로 넓혔다 (김한승·한도윤 합의).
- 배경 #121212, 카드 #181818·#1f1f1f, 본문 흰색, 보조 글자 #b3b3b3
- 초록(#1ed760)은 주요 버튼·활성 상태 같은 핵심 요소에만 쓰고 장식으로 쓰지 않는다
- 버튼은 알약 모양, 카드는 테두리 없이 배경 명도 차이와 진한 그림자로 구분한다
- 거절·부정은 빨강(#f3727f), 경고는 주황(#ffa42b)

.streamlit/config.toml의 [theme]도 같은 색으로 맞춰 두었다. Streamlit 기본 위젯과 st.plotly_chart(기본 theme="streamlit")가
이 색을 따라가고, 아래 CSS는 config로 바꿀 수 없는 모양(알약 버튼, 사이드바, 펼침 머리글 등)만 다룬다.
페이지 전용 요소(.qa-* 등)는 각 페이지 컴포넌트에 둔다.

담당: 공동 (변경 시 PR로 합의)
일정: Day 6
"""

import streamlit as st

COLORS = {
    "bg": "#121212", "surface": "#181818", "surface_2": "#1f1f1f", "card": "#252525",
    "text": "#ffffff", "text_2": "#b3b3b3", "text_3": "#cbcbcb", "line": "#4d4d4d",
    "green": "#1ed760", "red": "#f3727f", "orange": "#ffa42b", "blue": "#539df5",
}

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

/* 버튼: 기본은 어두운 알약, 주요 버튼(type="primary")만 초록 */
.stApp .stButton button, .stApp [data-testid="stFormSubmitButton"] button {
  border-radius: 9999px; background: var(--surface-2); color: var(--text); border: none;
  font-weight: 700; font-size: 14px; padding: 8px 18px; transition: background .15s, transform .15s;
}
.stApp .stButton button:hover, .stApp [data-testid="stFormSubmitButton"] button:hover { background: #2a2a2a; color: var(--text); }
.stApp [data-testid="stFormSubmitButton"] button[kind="primaryFormSubmit"], .stApp .stButton button[kind="primary"] {
  background: var(--green); color: #000000; letter-spacing: 0.14px; padding: 12px 18px; white-space: nowrap;
}
.stApp [data-testid="stFormSubmitButton"] button[kind="primaryFormSubmit"] p,
.stApp .stButton button[kind="primary"] p { color: #000000; font-weight: 700; white-space: nowrap; overflow: visible; }
.stApp [data-testid="stFormSubmitButton"] button[kind="primaryFormSubmit"]:hover,
.stApp .stButton button[kind="primary"]:hover { background: #3be477; transform: scale(1.03); }
.stApp [data-testid="stForm"] { border: none; padding: 0; }

/* 알약 선택(st.pills, st.segmented_control) */
.stApp [data-testid="stButtonGroup"] button {
  border-radius: 9999px; background: var(--surface-2); color: var(--text); border: none; font-size: 13px;
}
.stApp [data-testid="stButtonGroup"] button:hover { background: #2a2a2a; color: var(--text); }
.stApp [data-testid="stButtonGroup"] button[aria-checked="true"],
.stApp [data-testid="stButtonGroup"] button[aria-pressed="true"],
.stApp [data-testid="stButtonGroup"] button[data-selected="true"] { background: var(--text) !important; color: #000000; border: none; }
.stApp [data-testid="stButtonGroup"] button[aria-checked="true"] *,
.stApp [data-testid="stButtonGroup"] button[aria-pressed="true"] * { color: #000000; }

/* 토글·체크박스: 켜짐은 초록 (활성 상태) */
.stApp [data-testid="stCheckbox"] label span, .stApp [data-baseweb="checkbox"] div { color: var(--text-3); }
.stApp [data-baseweb="checkbox"] input:checked + div,
.stApp [data-testid="stCheckbox"] label[data-selected="true"] > span + div { background: var(--green) !important; }

/* 펼치기 */
.stApp [data-testid="stExpander"] details { background: var(--surface); border: none; border-radius: 8px; }
.stApp [data-testid="stExpander"] summary p { color: var(--text); font-weight: 600; }
.stApp [data-testid="stExpander"] summary,
.stApp [data-testid="stExpander"] summary:hover,
.stApp [data-testid="stExpander"] summary:focus { background: var(--surface) !important; color: var(--text); border-radius: 8px; }
.stApp [data-testid="stExpander"] summary:hover { background: var(--surface-2) !important; }
.stApp [data-testid="stExpander"] summary svg { fill: var(--text); color: var(--text); }
.stApp [data-testid="stAlert"] { background: var(--surface-2); border-radius: 8px; color: var(--text-3); }

/* 지표 카드(st.metric), 표(st.dataframe), 차트 */
.stApp [data-testid="stMetric"] { background: var(--surface); border-radius: 8px; padding: 16px 18px; }
.stApp [data-testid="stMetricValue"] { color: var(--text); font-weight: 800; font-variant-numeric: tabular-nums; }
.stApp [data-testid="stMetricLabel"] p { color: var(--text-2); font-size: 12px; }
.stApp [data-testid="stDataFrame"], .stApp [data-testid="stPlotlyChart"] { border-radius: 8px; }
</style>
"""


def apply_theme() -> None:
    """공통 어두운 테마 CSS를 넣는다. 페이지마다 st.set_page_config 바로 다음에 부른다."""
    st.markdown(THEME_CSS, unsafe_allow_html=True)
