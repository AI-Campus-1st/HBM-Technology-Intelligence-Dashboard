"""
Streamlit 진입점. 페이지 라우팅만 담당하고, 화면 로직은 pages/와 components/에 둔다.
실행: streamlit run dashboard/app.py

- 접속하면 '요약'이 바로 열린다 (default). "지금 무슨 일이 일어나고 있고 근거는 무엇인가"에 한 화면으로 답한다 (리포트 6.5).
- 근거는 이슈 분석(탭 1)·공시 Q&A(탭 2)에서 자세히 본다. 요약 카드의 링크가 url_path를 쓰므로 바꾸면 summary.py도 고친다.
- st.navigation을 쓰면 pages/ 자동 메뉴 대신 아래 목록이 메뉴가 된다. 페이지를 추가하면 여기에도 등록한다.

담당: 공동 (변경 최소화)
일정: Day 6
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # streamlit은 dashboard/만 경로에 넣으므로 프로젝트 루트를 더한다
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from dashboard.components import theme  # noqa: E402

st.set_page_config(page_title="HBM 대시보드", page_icon="📊", layout="wide")
theme.apply_theme()  # 대시보드 공통 어두운 테마 (모든 페이지 맨 위에서 부른다)

PAGES = [
    st.Page("pages/0_요약.py", title="요약", icon="🧭", default=True),
    st.Page("pages/1_이슈_분석.py", title="이슈 분석", icon="📈", url_path="이슈_분석"),
    st.Page("pages/2_공시_QA.py", title="공시 Q&A", icon="📄", url_path="공시_QA"),
]
st.navigation(PAGES).run()
