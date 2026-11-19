"""
Streamlit 진입점. 상단 결론 영역과 페이지 라우팅만 담당하고, 화면 로직은 pages/와 components/에 둔다.
실행: streamlit run dashboard/app.py

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
