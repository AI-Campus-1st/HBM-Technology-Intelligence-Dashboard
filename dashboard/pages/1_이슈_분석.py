"""
이슈 트렌드·감성 추이 화면.

담당: 김한승 (이슈 분석)
일정: Day 6
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # streamlit은 dashboard/만 경로에 넣으므로 프로젝트 루트를 더한다
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from dashboard.components import theme  # noqa: E402

st.set_page_config(page_title="이슈 분석 · HBM 대시보드", page_icon="📈", layout="wide")
theme.apply_theme()  # 대시보드 공통 어두운 테마 (한도윤 추가, 2026-11-19). 화면 내용은 이 아래에 둔다
