"""
Streamlit 진입점. 페이지 라우팅만 담당하고, 화면 로직은 pages/와 components/에 둔다.
실행: streamlit run dashboard/app.py

- 접속하면 '이슈 분석'(탭 1)이 바로 열린다 (default). 빈 시작 화면을 두지 않는다.
- 상단 결론 문장(Day 7)은 근거 차트와 한 화면에서 읽히도록 이슈 분석 맨 위에 둔다 (리포트 6.3).
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
    st.Page("pages/1_이슈_분석.py", title="이슈 분석", icon="📈", default=True),
    st.Page("pages/2_공시_QA.py", title="공시 Q&A", icon="📄", url_path="공시_QA"),
]
st.navigation(PAGES).run()
