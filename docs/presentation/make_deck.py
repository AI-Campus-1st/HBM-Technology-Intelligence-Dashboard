"""
발표 PPT 만들기 → docs/presentation/HBM_발표.pptx

- 대시보드와 같은 어두운 테마(theme.COLORS)를 쓴다. 글꼴은 맑은 고딕(Windows 기본).
- 숫자는 리포트(0장 핵심 요약, 3~6장)와 대시보드 요약 화면에서 옮겼다. 리포트 숫자가 바뀌면 여기도 고친다.
- 화면 캡처: img/dash_*.png (Edge headless로 대시보드 실행 화면을 찍음) → img/crop_*.png
- 실제 발표는 하지 않으므로 발표자 노트(대본)는 넣지 않는다. 슬라이드만으로 읽히게 쓴다.

실행: python docs/presentation/make_deck.py   (python-pptx 필요: pip install python-pptx)

담당: 공동
일정: Day 7
"""

from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

HERE = Path(__file__).resolve().parent
IMG = HERE / "img"
OUT = HERE / "HBM_발표.pptx"
FONT = "맑은 고딕"

# 대시보드 테마와 같은 색 (dashboard/components/theme.py)
BG, SURFACE, CARD, LINE = "121212", "1A1A1A", "242424", "4D4D4D"
TEXT, TEXT2, TEXT3 = "FFFFFF", "B3B3B3", "8A8A8A"
GREEN, RED, ORANGE, BLUE = "1ED760", "F3727F", "FFA42B", "539DF5"
SK, SEC = ORANGE, BLUE  # SK하이닉스 / 삼성전자

W, H = 13.333, 7.5
M = 0.6  # 좌우 여백


def rgb(h: str) -> RGBColor:
    return RGBColor.from_string(h)


def set_font(run, size, color=TEXT, bold=False, italic=False):
    f = run.font
    f.size, f.bold, f.italic = Pt(size), bold, italic
    f.color.rgb = rgb(color)
    f.name = FONT
    rpr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):  # 한글은 ea 글꼴로 그려지므로 같이 지정
        el = rpr.find(qn(tag))
        if el is None:
            el = rpr.makeelement(qn(tag), {})
            rpr.append(el)
        el.set("typeface", FONT)


def text(slide, x, y, w, h, paras, size=16, color=TEXT, bold=False, align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP, space_after=0, line_spacing=None, name=None):
    """paras: 문단 목록. 문단은 문자열 또는 [(글자, {size,color,bold,italic}), ...]."""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        tb.name = name
    tf = tb.text_frame
    tf.word_wrap, tf.auto_size, tf.vertical_anchor = True, MSO_AUTO_SIZE.NONE, anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    for i, para in enumerate(paras if isinstance(paras, list) else [paras]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(space_after)
        if line_spacing:
            p.line_spacing = line_spacing
        for t, o in ([(para, {})] if isinstance(para, str) else para):
            r = p.add_run()
            r.text = t
            set_font(r, o.get("size", size), o.get("color", color), o.get("bold", bold), o.get("italic", False))
    return tb


def box(slide, x, y, w, h, fill=CARD, radius=0.06, line=None, shape=MSO_SHAPE.ROUNDED_RECTANGLE, name=None):
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = radius
    s.fill.solid()
    s.fill.fore_color.rgb = rgb(fill)
    if line:
        s.line.color.rgb = rgb(line)
        s.line.width = Pt(1)
    else:
        s.line.fill.background()
    s.shadow.inherit = False
    if name:
        s.name = name
    return s


def circle(slide, x, y, d, fill, label, size=14, color=BG):
    s = box(slide, x, y, d, d, fill=fill, shape=MSO_SHAPE.OVAL)
    tf = s.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = label
    set_font(r, size, color, bold=True)
    return s


def picture(slide, path, x, y, w=None, h=None):
    pic = slide.shapes.add_picture(str(path), Inches(x), Inches(y),
                                   Inches(w) if w else None, Inches(h) if h else None)
    pic.line.color.rgb = rgb(LINE)
    pic.line.width = Pt(0.75)
    return pic


def new_slide(prs, kicker=None, title=None):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = rgb(BG)
    if kicker:
        text(s, M, 0.42, 9, 0.3, kicker, size=12, color=GREEN, bold=True, name="kicker")
    if title:
        text(s, M, 0.72, W - 2 * M, 0.75, title, size=28, bold=True, name="title")
    n = len(prs.slides)
    if n > 1:
        text(s, W - M - 1.5, H - 0.42, 1.5, 0.25, f"{n}", size=10, color=TEXT3, align=PP_ALIGN.RIGHT)
        text(s, M, H - 0.42, 8, 0.25, "HBM 기술 인텔리전스 대시보드 · 김한승 · 한도윤", size=10, color=TEXT3)
    return s


def stat(slide, x, y, w, value, label, color=TEXT, vsize=40, lsize=13):
    text(slide, x, y, w, 0.75, value, size=vsize, color=color, bold=True)
    text(slide, x, y + 0.78, w, 0.6, label, size=lsize, color=TEXT2)


def style_chart(chart, size=12):
    chart.font.size = Pt(size)
    chart.font.name = FONT
    chart.font.color.rgb = rgb(TEXT2)
    # 차트 글자도 한글(ea) 글꼴 지정
    defrpr = chart._chartSpace.find(qn("c:txPr")).find(qn("a:p")).find(qn("a:pPr")).find(qn("a:defRPr"))
    for tag in ("a:ea", "a:cs"):
        el = defrpr.makeelement(qn(tag), {"typeface": FONT})
        defrpr.append(el)
    va, ca = chart.value_axis, chart.category_axis
    va.major_gridlines.format.line.color.rgb = rgb("333333")
    va.format.line.fill.background()
    ca.format.line.color.rgb = rgb(LINE)
    for ax in (va, ca):
        ax.tick_labels.font.color.rgb = rgb(TEXT2)
        ax.tick_labels.font.size = Pt(size)


def no_invert(point):
    """음수 막대가 흰색으로 뒤집히지 않게: 데이터 점(dPt)에도 invertIfNegative=0을 넣는다."""
    dpt = point.format._element  # python-pptx: 점 서식의 요소가 c:dPt
    if dpt.tag != qn("c:dPt"):
        return
    if dpt.find(qn("c:invertIfNegative")) is None:
        el = dpt.makeelement(qn("c:invertIfNegative"), {"val": "0"})
        dpt.insert(1, el)  # c:idx 다음 자리 (스키마 순서)


# ───────────────────────── 슬라이드 ─────────────────────────

def s01_title(prs):
    s = new_slide(prs)
    text(s, M, 1.55, 9, 0.35, "AI 반도체 · 뉴스 × DART 공시 · LLM · RAG", size=14, color=GREEN, bold=True)
    text(s, M, 2.0, 11.5, 1.6, ["HBM 기술 인텔리전스", "대시보드"], size=48, bold=True, line_spacing=1.05)
    text(s, M, 3.95, 11.6, 1.0,
         [[("보도는 삼성전자 사건에 몰렸지만, ", {}), ("HBM 실적 성장은 SK하이닉스 공시에서 확인된다", {"color": GREEN, "bold": True})]],
         size=20, color=TEXT)
    text(s, M, 5.75, 10, 0.35, "김한승 · 한도윤", size=16, bold=True)
    text(s, M, 6.15, 11, 0.35, "분석 기간 2023-10-19 ~ 2026-10-19 · SK하이닉스 · 삼성전자 · 2026-11", size=13, color=TEXT2)


def s02_problem(prs):
    s = new_slide(prs, "문제 정의", "애널리스트는 HBM 뉴스 속에서 무엇이 변했는지 찾기 어렵다")
    # 왼쪽: 사용자
    box(s, M, 1.75, 5.4, 4.95, fill=CARD)
    text(s, M + 0.4, 2.05, 4.6, 0.3, "사용자", size=13, color=GREEN, bold=True)
    text(s, M + 0.4, 2.45, 4.6, 0.9, "증권사 반도체 담당 애널리스트", size=22, bold=True)
    text(s, M + 0.4, 3.45, 4.6, 3.0, [
        "공개 자료(뉴스·DART 공시)로 SK하이닉스와 삼성전자의 HBM 경쟁을 비교한다",
        "리포트를 쓸 때 무엇을 기준으로 삼고 무엇을 더 확인할지가 필요하다",
        "투자 의견·목표주가는 범위 밖",
    ], size=15, color=TEXT2, space_after=12)
    box(s, M + 0.4, 5.35, 4.6, 1.05, fill=SURFACE)
    text(s, M + 0.6, 5.35, 4.25, 1.05, [[("핵심 질문  ", {"color": GREEN, "size": 12}),
                                          ("지금 무슨 일이 일어나고 있고, 그 근거는 무엇인가", {})]],
         size=15, bold=True, anchor=MSO_ANCHOR.MIDDLE)
    # 오른쪽: 어려움 3개
    items = [("1", "보도량이 곧 관심도가 아니다", "전체 수집 기사 수가 달마다 크게 달라(2024-08은 68건뿐) 절대량만 보면 정점을 잘못 읽는다"),
             ("2", "기사는 많고 중복이 많다", "같은 제목의 재배포 기사 224건(3.1%)이 그대로 세어진다"),
             ("3", "보도와 공시가 따로 논다", "보도된 사건이 실제 공시(실적·투자)로 확인되는지 직접 찾아야 한다")]
    for i, (n, head, body) in enumerate(items):
        y = 1.75 + i * 1.7
        circle(s, 6.55, y + 0.05, 0.6, GREEN, n, size=18)
        text(s, 7.4, y, 5.3, 0.45, head, size=18, bold=True)
        text(s, 7.4, y + 0.5, 5.3, 0.9, body, size=14, color=TEXT2)


def s03_answer(prs):
    s = new_slide(prs, "질문과 답", "HBM에서 지금 무슨 일이 일어나고 있는가")
    box(s, M, 1.7, W - 2 * M, 1.55, fill=SURFACE)
    text(s, M + 0.45, 1.88, W - 2 * M - 0.9, 1.25, [
        [("HBM 보도는 ", {}), ("2024-12 정점(21.3%)", {"color": GREEN}), (" 이후 2차례 다시 급증한 뒤 최근 3개월 평균 2.8%로 식었다. ", {})],
        [("보도는 삼성전자 사건에 몰렸지만, HBM 실적 성장은 SK하이닉스 공시에서 확인된다.", {})],
    ], size=18, bold=True, anchor=MSO_ANCHOR.MIDDLE, space_after=4)
    cols = [("21.3%", "HBM 보도 비중 정점 (2024-12)", "① 무슨 일이 있었나", GREEN, "급증 4구간 = 정책·실적 발표"),
            ("53–95%", "급증 구간의 삼성전자 언급 비율\n평소(구간 밖)는 50%", "② 누구 이야기인가", SEC, "부정 보도 삼성 38% · SK 21%"),
            ("+70%↑", "SK하이닉스 HBM 매출 QoQ\n2024년 3분기 · 실적 첨부 p.5", "③ 공시로 확인된 사실", SK, "2025년 전년 대비 2배 이상")]
    cw = (W - 2 * M - 2 * 0.35) / 3
    for i, (v, lab, k, c, foot) in enumerate(cols):
        x = M + i * (cw + 0.35)
        box(s, x, 3.6, cw, 2.95, fill=CARD)
        text(s, x + 0.35, 3.85, cw - 0.7, 0.3, k, size=13, color=TEXT2, bold=True)
        text(s, x + 0.35, 4.25, cw - 0.7, 0.75, v, size=44, color=c, bold=True)
        text(s, x + 0.35, 5.05, cw - 0.7, 0.6, lab.split("\n"), size=13, color=TEXT2)
        text(s, x + 0.35, 5.85, cw - 0.7, 0.5, foot, size=12, color=TEXT, bold=True)


def s04_pipeline(prs):
    s = new_slide(prs, "데이터와 방법", "뉴스와 공시를 따로 좁힌 뒤 대시보드에서 만난다")
    lanes = [
        ("뉴스", GREEN, [("7,177", "반도체 뉴스\n2023-10 ~ 2026-10"), ("6,953", "중복 제외"),
                         ("385", "HBM 기사\n(핵심·관련 태깅)"), ("385 × 2", "LLM 기업별 감성\nSK하이닉스·삼성전자")]),
        ("공시", BLUE, [("568", "DART 공시 목록\n두 회사"), ("380", "원문 확보\n(확보율 100%)"),
                         ("101", "RAG 대상\n실적 첨부 PDF 포함"), ("2,191", "청크 → 벡터 DB\n하이브리드 검색")]),
    ]
    bw, gap, x0 = 2.2, 0.55, M + 1.25
    for li, (name, color, steps) in enumerate(lanes):
        y = 1.85 + li * 2.15
        text(s, M, y + 0.55, 1.1, 0.5, name, size=20, color=color, bold=True)
        for i, (v, lab) in enumerate(steps):
            x = x0 + i * (bw + gap)
            box(s, x, y, bw, 1.75, fill=CARD)
            text(s, x + 0.25, y + 0.2, bw - 0.4, 0.6, v, size=26, color=color, bold=True)
            text(s, x + 0.25, y + 0.85, bw - 0.4, 0.8, lab.split("\n"), size=12, color=TEXT2)
            if i < len(steps) - 1:
                a = box(s, x + bw + 0.14, y + 0.72, 0.28, 0.3, fill=LINE, shape=MSO_SHAPE.CHEVRON)
                a.name = "arrow"
    # 대시보드
    box(s, M, 6.1, W - 2 * M, 0.75, fill=SURFACE)
    text(s, M + 0.35, 6.1, W - 2 * M - 0.7, 0.75,
         [[("대시보드  ", {"color": GREEN, "bold": True}),
           ("요약 → 이슈 분석 → 공시 Q&A · 저장된 결과만 읽는다 (예시 질문도 저장된 답변) · 테스트 382개", {"color": TEXT2})]],
         size=15, anchor=MSO_ANCHOR.MIDDLE)


def s05_spikes(prs):
    s = new_slide(prs, "발견 ① 무슨 일이 있었나", "HBM 보도 급증은 정책과 실적 발표가 이끌었다")
    pic = picture(s, IMG / "crop_issue_chart.png", M, 1.7, w=7.7)
    text(s, M, 1.7 + pic.height / 914400 + 0.12, 7.7, 0.3,
         "대시보드 '이슈 분석' 화면 · 비중 = 그달 HBM 기사 / 전체 기사 · 진한 띠 = 공시로 확인된 급증 구간", size=11, color=TEXT3)
    x = M + 8.1
    text(s, x, 1.7, 4.0, 0.5, [[("6", {"color": TEXT2}), (" 구간 탐지 → ", {"size": 16, "color": TEXT2}),
                                ("4", {"color": GREEN}), (" 구간 분석", {"size": 16, "color": TEXT2})]], size=34, bold=True)
    text(s, x, 2.35, 4.0, 0.5, "중심 보도가 같은 시기 공시로 확인되는 구간만", size=13, color=TEXT2)
    events = [("2024-10", "삼성전자 3분기 실적 콘퍼런스콜"),
              ("2024-12 ~ 25-01", "미국의 대중 HBM 수출 통제 · 21.3% 정점"),
              ("2025-04 ~ 05", "삼성전자 1분기 'HBM 쇼크'"),
              ("2025-12 ~ 26-03", "두 회사 4분기 실적의 HBM4 경쟁")]
    for i, (d, e) in enumerate(events):
        y = 3.0 + i * 0.9
        box(s, x, y, 4.0, 0.78, fill=CARD)
        text(s, x + 0.2, y + 0.1, 3.7, 0.3, d, size=12, color=GREEN, bold=True)
        text(s, x + 0.2, y + 0.38, 3.7, 0.35, e, size=13)


def s06_who(prs):
    s = new_slide(prs, "발견 ② 누구 이야기인가", "보도와 논조는 삼성전자에 쏠렸다")
    stat(s, M, 1.85, 4.2, "53–95%", "급증 구간의 삼성전자 언급 비율\n(급증 구간 밖은 50%)", color=SEC, vsize=48, lsize=14)
    text(s, M, 3.55, 4.2, 0.35, "부정 보도 비율 (LLM 판정, sent_v2)", size=13, color=TEXT2, bold=True)
    for i, (name, pct, n, c) in enumerate([("삼성전자", 0.38, "124/325건", SEC), ("SK하이닉스", 0.21, "56/272건", SK)]):
        y = 4.05 + i * 0.95
        text(s, M, y, 1.6, 0.4, name, size=15, bold=True)
        box(s, M + 1.65, y + 0.05, 2.5, 0.32, fill=CARD, radius=0.5)
        box(s, M + 1.65, y + 0.05, 2.5 * pct / 0.5, 0.32, fill=c, radius=0.5)
        text(s, M + 1.65, y + 0.45, 2.5, 0.3, f"{pct:.0%} · {n}", size=12, color=TEXT2)
    text(s, M, 6.15, 4.3, 0.5, "보도 점유·논조는 시장 점유율이나 실적이 아니다", size=12, color=TEXT3)
    # 오른쪽: 분기 순감성 차트
    quarters = ["24Q4", "25Q1", "25Q2", "25Q3", "25Q4", "26Q1", "26Q2", "26Q3"]
    vals = [-0.37, 0.13, -0.49, 0.33, 0.93, 0.84, 0.70, 0.17]
    counts = [70, 47, 51, 6, 27, 37, 20, 18]
    x = M + 4.9
    box(s, x, 1.7, W - M - x, 4.95, fill=SURFACE)
    text(s, x + 0.35, 1.9, 6.5, 0.35, "삼성전자 분기 순감성 (긍정−부정)/등장 기사", size=14, bold=True)
    cd = CategoryChartData()
    cd.categories = [f"{q}\n{c}건" for q, c in zip(quarters, counts)]
    cd.add_series("순감성", vals)
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(x + 0.2), Inches(2.35),
                            Inches(W - M - x - 0.4), Inches(4.15), cd)
    ch = gf.chart
    style_chart(ch, size=11)
    ch.has_title = False
    ch.has_legend = False
    ch.value_axis.maximum_scale, ch.value_axis.minimum_scale = 1.1, -0.7
    ch.value_axis.major_unit = 0.2
    ch.value_axis.tick_labels.number_format = "+0.0;-0.0;0"
    ch.value_axis.tick_labels.number_format_is_linked = False
    ch.category_axis.tick_label_position  # 기본(축 옆)
    from pptx.enum.chart import XL_TICK_LABEL_POSITION
    ch.category_axis.tick_label_position = XL_TICK_LABEL_POSITION.LOW
    plot = ch.plots[0]
    plot.gap_width = 60
    plot.has_data_labels = True
    dl = plot.data_labels
    dl.number_format, dl.number_format_is_linked = "+0.00;-0.00;0.00", False
    dl.position = XL_LABEL_POSITION.OUTSIDE_END
    dl.font.size, dl.font.color.rgb, dl.font.bold = Pt(11), rgb(TEXT), True
    ser = plot.series[0]
    ser.invert_if_negative = False
    for i, v in enumerate(vals):
        pt = ser.points[i]
        pt.format.fill.solid()
        pt.format.fill.fore_color.rgb = rgb(RED if v < 0 else (SEC if i in (4, 7) else "3A5F8F"))
        no_invert(pt)


def s07_disclosure(prs):
    s = new_slide(prs, "발견 ③ 공시로 확인된 사실", "SK하이닉스의 HBM 성장은 보도가 아니라 공시에서 보인다")
    quotes = [("SK하이닉스", "2024년 3분기 실적발표 p.5 · 2024-10-24", "HBM 매출 QoQ +70% 이상, YoY +330% 이상", SK),
              ("SK하이닉스", "2025년 실적발표 p.8 · 2026-01-28", "’25년 HBM 매출 전년 대비 2배 이상 확대", SK),
              ("삼성전자", "2025년 1분기 경영설명회 p.8 · 2025-04-30",
               "첨단 반도체 수출 통제 영향 등에 따른 HBM 판매 감소 및 가격하락에 따른 실적 영향 有", SEC)]
    y = 1.75
    for corp, src, q, c in quotes:
        hq = 1.55 if len(q) > 40 else 1.2
        box(s, M, y, 7.6, hq, fill=CARD)
        text(s, M + 0.35, y + 0.2, 7.0, 0.3, [[(corp, {"color": c, "bold": True}), (f"  {src}", {"color": TEXT3})]], size=12)
        text(s, M + 0.35, y + 0.55, 7.0, hq - 0.65, f"“{q}”", size=17, bold=True)
        y += hq + 0.25
    x = M + 8.0
    box(s, x, 1.75, W - M - x, 4.6, fill=SURFACE)
    text(s, x + 0.35, 1.98, 3.6, 0.6, "실적 공시 전후 실적 기사\n(수집한 뉴스, 각 12회)".split("\n"), size=13, color=TEXT2, bold=True)
    stat(s, x + 0.35, 2.85, 1.7, "5", "SK하이닉스", color=SK, vsize=54, lsize=14)
    stat(s, x + 2.15, 2.85, 1.7, "33", "삼성전자", color=SEC, vsize=54, lsize=14)
    text(s, x + 0.35, 4.45, 3.6, 1.8,
         ["이 데이터의 보도량만으로 SK하이닉스의 HBM 실적을 판단하기 어렵다.",
          "키워드로 수집한 뉴스라 언론 전체의 보도량은 아니다."], size=13, color=TEXT2, space_after=6)
    text(s, M, 6.55, 11, 0.3, "인용은 DART 실적 공시 첨부 PDF 원문 그대로 · 사람이 원문 쪽을 열어 대조 (리포트 6.5.1)", size=11, color=TEXT3)


def s08_recommend(prs):
    s = new_slide(prs, "그래서 무엇을 할까", "애널리스트는 공시 지표를 기준으로 삼고, 보도는 시점 확인에만 쓴다")
    recs = [("1", "SK하이닉스는 공시 수치로", "보도량으로 판단하지 않는다. HBM 매출 성장은 실적 자료에서 확인되므로 비교 기준을 공시 수치로 잡는다", SK),
            ("2", "삼성 HBM4는 정성 근거까지만", "'HBM4 양산 판매 개시'(2026-04-30)·'공급 확대'(2026-07-30)는 있지만 출하량·매출 수치는 없다", SEC),
            ("3", "관심 둔화 ≠ 사업 둔화", "최근 3개월 보도 비중 2.8%는 보도 관심이 줄었다는 뜻이다. 사업 악화 신호로 읽지 않는다", GREEN),
            ("4", "투자액은 IR로 보완", "HBM 투자액은 공시로 확인할 수 없다(R&D·시설투자는 회사 전체 금액). 컨퍼런스콜로 보완한다", ORANGE)]
    cw, ch_ = (W - 2 * M - 0.35) / 2, 2.15
    for i, (n, head, body, c) in enumerate(recs):
        x, y = M + (i % 2) * (cw + 0.35), 1.75 + (i // 2) * (ch_ + 0.3)
        box(s, x, y, cw, ch_, fill=CARD)
        circle(s, x + 0.35, y + 0.35, 0.6, c, n, size=18)
        text(s, x + 1.2, y + 0.38, cw - 1.5, 0.5, head, size=18, bold=True)
        text(s, x + 1.2, y + 0.95, cw - 1.5, 1.1, body, size=14, color=TEXT2)
    text(s, M, 6.55, 11, 0.3, "공개 자료(뉴스·DART 공시) 기반 분석이며 투자 의견이 아니다", size=11, color=TEXT3)


def s09_sentiment(prs):
    s = new_slide(prs, "AI 활용 ① 기업별 감성 분류", "LLM 오류를 유형으로 나눠 프롬프트를 고쳤다")
    cd = CategoryChartData()
    cd.categories = ["v1 1차", "v1 (사람 라벨 정정 후)", "v2 (본문 6,000자 + 규칙 7)"]
    cd.add_series("SK하이닉스", [0.64, 0.70, 0.78])
    cd.add_series("삼성전자", [0.84, 0.88, 0.88])
    box(s, M, 1.7, 6.6, 4.95, fill=SURFACE)
    text(s, M + 0.35, 1.9, 6, 0.35, "정확도 (사람 라벨 50건, 4분류)", size=14, bold=True)
    gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(M + 0.2), Inches(2.3), Inches(6.2), Inches(4.2), cd)
    ch = gf.chart
    style_chart(ch, size=11)
    ch.has_legend = True
    ch.legend.include_in_layout = False
    from pptx.enum.chart import XL_LEGEND_POSITION
    ch.legend.position = XL_LEGEND_POSITION.TOP
    ch.legend.font.color.rgb, ch.legend.font.size = rgb(TEXT2), Pt(12)
    ch.has_title = False
    ch.value_axis.minimum_scale, ch.value_axis.maximum_scale, ch.value_axis.major_unit = 0.5, 1.0, 0.1
    ch.value_axis.tick_labels.number_format, ch.value_axis.tick_labels.number_format_is_linked = "0.0", False
    plot = ch.plots[0]
    plot.gap_width, plot.overlap = 70, -10
    plot.has_data_labels = True
    dl = plot.data_labels
    dl.number_format, dl.number_format_is_linked = "0.00", False
    dl.position = XL_LABEL_POSITION.OUTSIDE_END
    dl.font.size, dl.font.color.rgb, dl.font.bold = Pt(12), rgb(TEXT), True
    for ser, c in zip(plot.series, (SK, SEC)):
        ser.format.fill.solid()
        ser.format.fill.fore_color.rgb = rgb(c)
    rows = [("본문 잘림", "앞 1,500자만 넣어 '해당없음' 오판", "본문 6,000자로 확대"),
            ("업계 공통 악재", "수출 규제를 개별 기업엔 '중립'", "규칙 7: 업계 공통 영향도 반영"),
            ("같은 표본으로 튜닝", "규칙을 만든 50건으로 채점", "낙관적일 수 있음을 화면·리포트에 표시")]
    x = M + 7.0
    for i, (k, prob, fix) in enumerate(rows):
        y = 1.7 + i * 1.65
        box(s, x, y, W - M - x, 1.45, fill=CARD)
        text(s, x + 0.3, y + 0.15, 4.5, 0.35, k, size=15, color=GREEN, bold=True)
        text(s, x + 0.3, y + 0.55, 4.6, 0.35, prob, size=13, color=TEXT2)
        text(s, x + 0.3, y + 0.92, 4.6, 0.4, [[("→ ", {"color": GREEN}), (fix, {})]], size=13, bold=True)


def s10_rag(prs):
    s = new_slide(prs, "AI 활용 ② 공시 Q&A (RAG)", "근거가 없으면 답하지 않는다")
    steps = [("기업 필터", "질문 속 기업명으로\n공시 범위 좁히기"), ("하이브리드 검색", "벡터 40 + 키워드\nRRF → 근거 6개"),
             ("1차 거절", "검색 거리 0.65 초과면\nLLM 호출 없이 거절"), ("답변·2차 거절", "근거 안의 내용만 쓰고\n답할 수 없으면 거절"),
             ("출처 표시", "공시명·쪽 번호·\nDART 링크·발췌")]
    bw, gap = 2.12, 0.33
    for i, (k, v) in enumerate(steps):
        x = M + i * (bw + gap)
        box(s, x, 1.7, bw, 1.85, fill=CARD)
        circle(s, x + 0.22, 1.88, 0.42, GREEN, str(i + 1), size=13)
        text(s, x + 0.22, 2.42, bw - 0.35, 0.4, k, size=15, bold=True)
        text(s, x + 0.22, 2.85, bw - 0.35, 0.65, v.split("\n"), size=12, color=TEXT2)
        if i < len(steps) - 1:
            box(s, x + bw + 0.06, 2.48, 0.21, 0.28, fill=LINE, shape=MSO_SHAPE.CHEVRON)
    stats = [("21/24", "평가 질문 정확 (88%)", TEXT), ("5/5", "거절 정확 · 지어낸 답변 0건", GREEN), ("101", "RAG 대상 공시 · 청크 2,191개", TEXT)]
    for i, (v, lab, c) in enumerate(stats):
        stat(s, M + i * 2.35, 4.05, 2.25, v, lab, color=c, vsize=36, lsize=12)
    text(s, M, 5.65, 6.9, 1.0, ["틀린 3개는 모두 검색 누락(정답이 21~28위)", "→ 검색이 답변 품질의 상한이다"],
         size=14, color=TEXT2, space_after=4)
    # 검색 적중 차트
    x = M + 7.35
    box(s, x, 3.9, W - M - x, 2.85, fill=SURFACE)
    text(s, x + 0.3, 4.05, 4.5, 0.35, "검색 적중 hit@6 (답변 질문 19개)", size=13, bold=True)
    cd = CategoryChartData()
    cd.categories = ["벡터만", "하이브리드", "+ 재정렬(선택)"]
    cd.add_series("적중", [14, 16, 19])
    gf = s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(x + 0.15), Inches(4.45), Inches(W - M - x - 0.35), Inches(2.2), cd)
    ch = gf.chart
    style_chart(ch, size=11)
    ch.has_title = False
    ch.has_legend = False
    ch.value_axis.minimum_scale, ch.value_axis.maximum_scale = 0, 19
    ch.value_axis.visible = False
    ch.value_axis.has_major_gridlines = False
    ch.category_axis.reverse_order = True
    plot = ch.plots[0]
    plot.gap_width = 45
    plot.has_data_labels = True
    dl = plot.data_labels
    dl.number_format, dl.number_format_is_linked = '0"/19"', False
    dl.position = XL_LABEL_POSITION.INSIDE_END
    dl.font.size, dl.font.color.rgb, dl.font.bold = Pt(12), rgb(BG), True
    for i, c in enumerate(["5A5A5A", BLUE, GREEN]):
        pt = plot.series[0].points[i]
        pt.format.fill.solid()
        pt.format.fill.fore_color.rgb = rgb(c)


def s11_dashboard(prs):
    s = new_slide(prs, "대시보드", "열자마자 결론, 누르면 근거")
    p1 = picture(s, IMG / "crop_summary.png", M, 1.65, h=4.75)
    w1 = p1.width / 914400
    text(s, M, 6.5, w1, 0.3, "① 요약 — 질문 → 답 → 근거 3 → 권고 → 한계", size=12, color=TEXT2, bold=True)
    x = M + w1 + 0.35
    p2 = picture(s, IMG / "crop_qa.png", x, 1.65, w=W - M - x)
    h2 = p2.height / 914400
    text(s, x, 1.65 + h2 + 0.1, W - M - x, 0.3, "③ 공시 Q&A — 예시 질문은 저장된 답변, 직접 질문만 실시간", size=12, color=TEXT2, bold=True)
    pts = ["저장된 결과만 읽기", "필터 → 모든 차트", "오프라인 예시 답변"]
    cw = (W - M - x - 0.3) / 3
    for i, k in enumerate(pts):
        bx = x + i * (cw + 0.15)
        box(s, bx, 6.0, cw, 0.62, fill=CARD)
        circle(s, bx + 0.12, 6.17, 0.28, GREEN, "✓", size=10)
        text(s, bx + 0.48, 6.0, cw - 0.52, 0.62, k, size=11, bold=True, anchor=MSO_ANCHOR.MIDDLE)


def s12_limits(prs):
    s = new_slide(prs, "회고 · LLM 활용 한계와 대응", "AI가 틀리는 지점을 찾아 사람이 확인했다")
    rows = [("인용이 원문과 달라짐", "확인된 공시를 옮기며 '전년 대비'·'가격하락'이 빠짐", "PDF 원문 + 쪽 번호로 고정, 쪽 텍스트 대조 테스트"),
            ("LLM 출력이 흔들림", "같은 정답 기준, 두 번 실행에 23/24 · 21/24", "점수를 범위(21~23/24)로 보고, temperature 0·seed 시험"),
            ("평가 정답 사후 보정", "결과를 본 뒤 정답 근거를 2번 추가", "보정 전 점수·이유 기록, 시험 전 확인용 질문 12개"),
            ("수집 범위가 결론을 좌우", "키워드 수집이라 실적 기사가 적게 담김", "'이 데이터 안의 숫자'로만 말하고 공시로 보완")]
    heads = ["한계", "실제로 생긴 일", "대응"]
    xs, ws = [M, M + 3.3, M + 7.55], [3.1, 4.05, W - M - (M + 7.55)]
    for j, hname in enumerate(heads):
        text(s, xs[j] + 0.25, 1.7, ws[j], 0.3, hname, size=12, color=TEXT3, bold=True)
    for i, row in enumerate(rows):
        y = 2.1 + i * 1.12
        box(s, M, y, W - 2 * M, 0.98, fill=CARD)
        for j, cell in enumerate(row):
            text(s, xs[j] + 0.25, y, ws[j] - 0.35, 0.98, cell, size=15 if j == 0 else 13,
                 color=GREEN if j == 0 else (TEXT if j == 2 else TEXT2), bold=(j != 1), anchor=MSO_ANCHOR.MIDDLE)


def s13_next(prs):
    s = new_slide(prs, "회고 · 다음에 다르게 할 것", "평가 기준은 시험 전에, 수집 범위는 질문에 맞게")
    items = [("표본 분리", "프롬프트 개선용과 독립 평가용 표본을 처음부터 나눈다", GREEN),
             ("평가 기준 먼저", "정답 근거 기준과 확인용 질문을 시험 전에 정한다", GREEN),
             ("범위로 보고", "LLM 평가는 여러 번 실행해 점수를 범위로 적는다", GREEN),
             ("질문에 맞춘 수집", "실적·고객 공급·투자 주제를 수집 키워드에 넣는다", GREEN)]
    for i, (k, v, c) in enumerate(items):
        y = 1.75 + i * 1.12
        circle(s, M, y + 0.1, 0.55, c, str(i + 1), size=16)
        text(s, M + 0.8, y, 6.2, 0.45, k, size=18, bold=True)
        text(s, M + 0.8, y + 0.48, 6.2, 0.5, v, size=14, color=TEXT2)
    x = M + 7.4
    box(s, x, 1.75, W - M - x, 4.4, fill=SURFACE)
    text(s, x + 0.35, 1.98, 4, 0.35, "협업 방식", size=14, color=GREEN, bold=True)
    for i, (v, lab) in enumerate([("70+", "머지한 PR — 브랜치에서 작업하고 PR로 합침"), ("382", "테스트 (API 호출 없이 실행)"),
                                  ("0", "주고받은 DB 파일 — 각자 다시 만들고 지문으로 확인")]):
        y = 2.45 + i * 1.2
        text(s, x + 0.35, y, 1.5, 0.7, v, size=32, bold=True)
        text(s, x + 1.85, y + 0.12, W - M - x - 2.1, 0.8, lab, size=13, color=TEXT2)


def s14_close(prs):
    s = new_slide(prs)
    text(s, M, 1.6, 11, 0.35, "정리", size=14, color=GREEN, bold=True)
    text(s, M, 2.1, 11.8, 2.0, [
        [("보도는 삼성전자 사건에 몰렸지만,", {})],
        [("HBM 실적 성장은 SK하이닉스 공시에서 확인된다", {"color": GREEN})],
    ], size=34, bold=True, line_spacing=1.15)
    text(s, M, 4.3, 11.5, 0.9, "HBM 경쟁 구도는 보도량·논조가 아니라 실적 공시의 HBM 지표로 판단하고, 보도는 사건 시점을 확인하는 데만 쓴다.",
         size=17, color=TEXT2)
    text(s, M, 5.75, 6, 0.6, "감사합니다 · Q&A", size=26, bold=True)
    text(s, M, 6.4, 11, 0.35, "리포트: docs/report/리포트_통합본.md · 실행: streamlit run dashboard/app.py", size=12, color=TEXT3)


def main():
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(int(W * 914400)), Emu(int(H * 914400))
    prs.core_properties.title = "HBM 기술 인텔리전스 대시보드"
    prs.core_properties.author = "김한승, 한도윤"
    for build in (s01_title, s02_problem, s03_answer, s04_pipeline, s05_spikes, s06_who, s07_disclosure,
                  s08_recommend, s09_sentiment, s10_rag, s11_dashboard, s12_limits, s13_next, s14_close):
        build(prs)
    prs.save(OUT)
    print(f"{OUT.name} 저장: 슬라이드 {len(prs.slides)}장")


if __name__ == "__main__":
    main()
