"""
HBM 기사와 공시를 연결하고, 그 결과로 RAG 대상 공시(disclosure.rag_target)를 다시 정한다.

방향 (2026-11-16 논의): "뉴스에서 이슈 발견 → 공시로 근거 확인" 흐름에 맞춰, RAG에는 다음 공시만 남긴다.
    (1) A 정기공시 — 뉴스에 없는 신호도 담고 있어 항상 남긴다
    (2) 본문에 'HBM'이 나오는 공시
    (3) HBM 기사와 연결되는 공시 = 기사의 사실을 확인(fact check)할 수 있는 공시.
        단 '실적' 주제로만 연결된 공시는 RAG 선정에 쓰지 않는다 (RAG_EXCLUDE_TOPICS). 잠정실적은 분기마다
        반복돼 거의 모든 기사와 연결되고, 실적 공시는 계절성이라 급증 근거로 쓰지 않기로 했다 (리포트 3.2).
        이 연결은 근거 카드(issue_evidence) 후보에는 그대로 남긴다.
원문이 없는 공시(대상아님·실패)는 연결되더라도 RAG에 넣을 수 없으므로 '원문 필요'로 따로 보고한다.

연결 규칙 (LINK_VERSION, 김한승과 확정 전 초안):
    - 같은 기업: 기사의 '주 대상 기업'(primary_companies)과 공시 corp_name이 같다.
      두 회사를 모두 언급한 기사(연결 기사의 약 60%)가 양쪽 공시에 다 붙지 않도록, news_tag의 제목 포함·본문
      언급 수로 주 대상을 정한다: 제목에 한 회사만 → 그 회사 / 제목에 없으면 본문 언급이 2배 이상인 회사 /
      그 밖(둘 다 제목, 비슷한 언급 수 = 비교 기사)은 두 회사 모두
    - 가까운 시점: 공시 제출일이 기사 발행일 ±WINDOW_DAYS(7)일 안 (link_v1의 ±30일은 분기 공시가 거의 다 걸림)
    - 같은 주제: TOPICS의 주제 하나에 대해 기사 패턴과 공시 패턴이 모두 맞는다
link_v1 → link_v2 (2026-11-17, 한도윤 제안·김한승 합의 대기): ±30일 → ±7일, 주 대상 기업, 실적 연결은 RAG 선정 제외
HBM 기사: news_tag에서 HBM 핵심·관련, 중복 아닌 기사. news_tag가 비어 있으면(preprocess.py 전)
    tagging.tag_article()로 즉석에서 같은 기준을 계산한다 (news_tag에는 쓰지 않는다).

결과:
    - data/processed/disclosure_news_links.csv : 연결 후보 (기사 × 공시 × 주제). Day 3 issue_evidence 후보
    - outputs/reports/disclosure_rag_link_summary.csv : 유형별 새 기준 RAG 대상 수와 현재(유형 필터) 비교
    - --apply일 때만 disclosure.rag_target·filter_reason을 바꾼다 (기본은 미리보기)

실행: python -m src.dart.news_link            (미리보기: CSV만 저장, DB는 그대로)
      python -m src.dart.news_link --apply    (DB의 rag_target 갱신. parse_documents 다음에 실행)

담당: 한도윤 (공시 분석) — 연결 규칙은 김한승과 합의 후 확정
일정: Day 3
"""

import argparse
import re
from datetime import timedelta
from pathlib import Path

import pandas as pd

from src.common import config, db
from src.news import tagging

LINK_VERSION = "link_v2"
WINDOW_DAYS = 7
RAG_EXCLUDE_TOPICS = frozenset({"실적"})  # 이 주제로만 연결된 공시는 RAG 대상 근거로 쓰지 않는다 (근거 카드 후보에는 남김)
PRIMARY_DOMINANCE = 2  # 제목에 기업이 없을 때, 본문 언급이 상대의 이 배수 이상이면 주 대상
HBM_RELEVANCE = ("핵심", "관련")  # 분석 대상 HBM 기사 (사람 검수 반영 추정 정밀도 0.83·재현율 0.85, 2026-11-16)

LINKS_PATH = config.PROCESSED_DIR / "disclosure_news_links.csv"
SUMMARY_PATH = config.OUTPUTS_DIR / "reports" / "disclosure_rag_link_summary.csv"

# 기사 주제 패턴. '투자'처럼 넓은 단어는 HBM 기사 대부분에 나와 쓰지 않는다.
ARTICLE_TOPICS: dict[str, re.Pattern] = {
    "설비투자": re.compile(
        r"증설|공장|팹|FAB|생산\s*라인|생산능력|시설\s*투자|설비\s*투자|M15X|용인|청주|인디애나|웨스트\s*라피엣|평택|천안"
    ),
    "실적": re.compile(r"실적|영업이익|매출|흑자|적자|어닝"),
    "공급·고객": re.compile(r"공급|납품|엔비디아|NVIDIA|퀄\s*테스트|인증|수주|공급\s*계약"),
    "수출규제": re.compile(r"수출\s*(?:통제|규제)|제재|블랙리스트|VEU|검증된\s*최종\s*사용자"),
}

# 공시 주제는 공시 종류로 정한다. 긴 문서(정기보고서·위임장·대규모기업집단현황)는 모든 주제 단어가 들어 있어
# 본문 키워드로 정하면 거의 모든 기사와 연결된다 (첫 실행: 2,717쌍).
# - A·D: 연결하지 않는다 (A는 항상 RAG, D는 HBM 언급으로 판단)
# - I·B: 공시명으로 주제를 정한다. 풍문·조회공시·기타경영사항은 내용이 제각각이라 짧은 본문에 기사 패턴을 적용한다
# - J: 본문에 FAB 건설·설계·생산부속시설 거래가 있을 때만 '설비투자'
NAME_TOPICS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"신규\s*시설\s*투자|유형자산\s*취득|타법인\s*주식|장래사업"), "설비투자"),
    (re.compile(r"유상증자|영업\s*양수|영업\s*양도"), "설비투자"),
    (re.compile(r"영업\s*\(잠정\)\s*실적|손익구조"), "실적"),
    (re.compile(r"단일판매\s*ㆍ?\s*공급계약|공급계약"), "공급·고객"),
)
CONTENT_TOPIC_NAMES = re.compile(r"풍문|조회공시|기타\s*경영사항|투자판단")
# 내용 기준 공시 중 이런 말이 있으면 HBM 사업과 무관한 공시로 보고 연결하지 않는다 (예: '스마트공장' 후원금)
CONTENT_EXCLUDE = re.compile(r"기부|성금|후원|출연|배당|자기주식|자사주|주주환원|증시\s*상장|차입")
J_CAPEX = re.compile(r"신규\s*FAB\s*구축|FAB\s*건설|FAB\s*설계|사업장\s*건설\s*공사|생산\s*부속")
J_EXCLUDE_NAMES = ("대규모기업집단현황공시", "부동산임대")
B_CAPEX_REQUIRES = re.compile(r"시설자금")  # 유상증자는 시설자금 조달일 때만 설비투자로 본다


def hbm_articles(conn) -> tuple[pd.DataFrame, str]:
    """HBM 핵심·관련 기사와 기업 태그. Returns (기사표[news_id, published_at, title, content, companies], 출처)."""
    news = db.read_table(conn, "news", columns=["news_id", "published_at", "title", "content", "is_duplicate"])
    tags = db.read_table(conn, "news_tag")
    source = f"news_tag ({tags['rule_version'].iloc[0]})" if not tags.empty else None
    if tags.empty:  # preprocess.py 전: 같은 규칙으로 즉석 계산
        rows = [r for n in news.itertuples(index=False) for r in tagging.tag_article(n.news_id, n.title, n.content)]
        tags = pd.DataFrame(rows, columns=["news_id", "tag_type", "tag", "relevance", "in_title", "body_count", "rule_version"])
        source = f"tagging.tag_article 즉석 계산 ({tagging.RULE_VERSION}, news_tag 비어 있음)"
    hbm_ids = set(tags[(tags["tag"] == "HBM") & tags["relevance"].isin(HBM_RELEVANCE)]["news_id"])
    company_tags = tags[tags["tag_type"] == "company"]
    companies = company_tags.groupby("news_id")["tag"].apply(lambda s: tuple(sorted(set(s))))
    primary = company_tags.groupby("news_id").apply(
        lambda g: primary_companies(zip(g["tag"], g["in_title"], g["body_count"])), include_groups=False
    )
    art = news[news["news_id"].isin(hbm_ids) & (news["is_duplicate"] == 0)].copy()
    as_tuple = lambda v: v if isinstance(v, tuple) else ()  # noqa: E731 — 기업 태그가 없는 기사
    art["companies"] = art["news_id"].map(companies).apply(as_tuple)
    art["primary_companies"] = art["news_id"].map(primary).apply(as_tuple)
    return art.drop(columns="is_duplicate").reset_index(drop=True), source


def primary_companies(company_rows) -> tuple[str, ...]:
    """기사의 주 대상 기업. company_rows: (기업, 제목 포함 0/1, 본문 언급 수) 목록.

    - 기업이 하나뿐이면 그 기업
    - 제목에 한 기업만 나오면 그 기업
    - 둘 다 제목에 없고, 한쪽 본문 언급이 다른 쪽의 PRIMARY_DOMINANCE배 이상이면 그 기업
    - 그 밖(둘 다 제목, 비슷한 언급 수)은 비교 기사로 보고 모두
    """
    rows = [(tag, bool(in_title), int(count)) for tag, in_title, count in company_rows]
    if len(rows) <= 1:
        return tuple(tag for tag, _, _ in rows)
    titled = [tag for tag, in_title, _ in rows if in_title]
    if len(titled) == 1:
        return (titled[0],)
    if not titled:
        (top, top_n), (_, second_n) = sorted(((t, n) for t, _, n in rows), key=lambda x: -x[1])[:2]
        if top_n >= PRIMARY_DOMINANCE * second_n:
            return (top,)
    return tuple(sorted(tag for tag, _, _ in rows))


def article_topics(text: str) -> set[str]:
    """기사(제목+본문)에 걸리는 주제 집합."""
    return {name for name, pat in ARTICLE_TOPICS.items() if pat.search(text or "")}


def disclosure_topics(pblntf_ty: str, report_nm: str, text) -> set[str]:
    """공시 종류에 맞춰 주제를 정한다 (위 NAME_TOPICS 설명 참고)."""
    text = text if isinstance(text, str) else ""
    if pblntf_ty in ("A", "D"):
        return set()
    if pblntf_ty == "J":
        if any(n in report_nm for n in J_EXCLUDE_NAMES):
            return set()
        return {"설비투자"} if J_CAPEX.search(text) else set()
    topics = {topic for pat, topic in NAME_TOPICS if pat.search(report_nm)}
    if "유상증자" in report_nm and not B_CAPEX_REQUIRES.search(text):
        topics.discard("설비투자")
    if CONTENT_TOPIC_NAMES.search(report_nm) and not CONTENT_EXCLUDE.search(text):
        topics |= article_topics(text)
    return topics


def link(articles: pd.DataFrame, disclosures: pd.DataFrame, window_days: int = WINDOW_DAYS) -> pd.DataFrame:
    """기업·시점·주제가 맞는 (기사, 공시) 연결 후보를 만든다."""
    cols = ["news_id", "published_at", "title", "rcept_no", "corp_name", "rcept_dt", "report_nm",
            "pblntf_ty", "topic", "days_from_article", "match_type", "link_version"]
    if articles.empty or disclosures.empty:
        return pd.DataFrame(columns=cols)
    disc = disclosures.copy()
    disc["dt"] = pd.to_datetime(disc["rcept_dt"])
    disc["topics"] = [disclosure_topics(ty, n, t) for ty, n, t in zip(disc["pblntf_ty"], disc["report_nm"], disc["text"])]
    disc = disc[disc["topics"].map(bool)]
    rows = []
    for a in articles.itertuples(index=False):
        content = a.content if isinstance(a.content, str) else ""
        a_topics = article_topics(f"{a.title} {content}")
        targets = getattr(a, "primary_companies", None) or a.companies  # 주 대상이 없으면(입력에 없을 때) 전체 기업
        if not a_topics or not targets:
            continue
        pub = pd.Timestamp(a.published_at)
        near = disc[(disc["corp_name"].isin(targets))
                    & (disc["dt"] >= pub - timedelta(days=window_days))
                    & (disc["dt"] <= pub + timedelta(days=window_days))]
        for d in near.itertuples(index=False):
            for topic in sorted(a_topics & d.topics):
                rows.append({
                    "news_id": a.news_id, "published_at": a.published_at, "title": a.title,
                    "rcept_no": d.rcept_no, "corp_name": d.corp_name, "rcept_dt": d.rcept_dt,
                    "report_nm": d.report_nm, "pblntf_ty": d.pblntf_ty, "topic": topic,
                    "days_from_article": int((d.dt - pub).days),
                    "match_type": "키워드", "link_version": LINK_VERSION,
                })
    return pd.DataFrame(rows, columns=cols)


def new_rag_target(disclosures: pd.DataFrame, links: pd.DataFrame) -> pd.DataFrame:
    """새 기준의 rag_target과 이유. 원문이 있는 공시만 RAG 대상이 될 수 있다."""
    df = disclosures.copy()
    rag_links = links[~links["topic"].isin(RAG_EXCLUDE_TOPICS)]
    has_text = df["text_status"] == "확보"
    df["by_A"] = df["pblntf_ty"] == "A"
    df["by_hbm"] = df["text"].fillna("").str.contains("HBM")
    df["by_link"] = df["rcept_no"].isin(set(rag_links["rcept_no"]))
    # 실적 주제로만 연결된 공시 (근거 카드 후보에는 있지만 RAG 근거로는 안 씀)
    df["link_excluded_only"] = df["rcept_no"].isin(set(links["rcept_no"])) & ~df["by_link"]
    keep = df["by_A"] | df["by_hbm"] | df["by_link"]
    df["new_rag_target"] = (has_text & keep).astype(int)
    df["new_reason"] = None
    df.loc[has_text & ~keep, "new_reason"] = f"{LINK_VERSION}: HBM 언급·뉴스 연결 없음"
    df["needs_text"] = (~has_text & df["by_link"]).astype(int)  # 연결됐지만 원문이 없어 RAG에 못 넣는 공시
    return df


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("pblntf_ty")
    out = pd.DataFrame({
        "목록": g.size(),
        "현재_RAG대상": g["rag_target"].sum(),
        "새_RAG대상": g["new_rag_target"].sum(),
        "근거_A": g["by_A"].sum(),
        "근거_HBM언급": g["by_hbm"].sum(),
        "근거_뉴스연결": g["by_link"].sum(),
        "실적연결만_RAG제외": g["link_excluded_only"].sum(),
        "연결됐지만_원문없음": g["needs_text"].sum(),
    }).astype(int)
    out.loc["합계"] = out.sum()
    return out.reset_index().rename(columns={"index": "pblntf_ty"})


def apply_to_db(conn, df: pd.DataFrame) -> None:
    """rag_target·filter_reason을 새 기준으로 바꾼다. 대상아님·실패 공시의 기록은 건드리지 않는다."""
    has_text = df[df["text_status"] == "확보"]
    with conn:
        conn.executemany(
            "UPDATE disclosure SET rag_target=?, filter_reason=? WHERE rcept_no=?",
            [(int(r.new_rag_target), r.new_reason, r.rcept_no) for r in has_text.itertuples(index=False)],
        )


def main(apply: bool = False, window_days: int = WINDOW_DAYS, db_path: Path = config.DB_PATH) -> pd.DataFrame:
    conn = db.connect(db_path)
    try:
        articles, source = hbm_articles(conn)
        disclosures = db.read_table(conn, "disclosure", columns=[
            "rcept_no", "corp_name", "report_nm", "rcept_dt", "pblntf_ty", "text", "text_status", "rag_target"])
        links = link(articles, disclosures, window_days)
        result = new_rag_target(disclosures, links)
        if apply:
            apply_to_db(conn, result)
    finally:
        conn.close()

    LINKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    links.to_csv(LINKS_PATH, index=False, encoding="utf-8-sig")
    summary = summarize(result)
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(SUMMARY_PATH, index=False, encoding="utf-8-sig")

    print(f"HBM 기사: {len(articles):,}건 — 출처: {source}")
    print(f"연결 후보: {len(links):,}건 (기사 {links['news_id'].nunique():,} × 공시 {links['rcept_no'].nunique():,}), "
          f"규칙 {LINK_VERSION}, ±{window_days}일")
    if not links.empty:
        print("주제별 연결 공시 수: " + ", ".join(
            f"{t} {n}" for t, n in links.groupby("topic")["rcept_no"].nunique().items()))
    print(summary.to_string(index=False))
    print(f"{'DB rag_target 갱신함' if apply else '미리보기 (DB 그대로, --apply로 반영)'}")
    print(f"저장: {LINKS_PATH}, {SUMMARY_PATH}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HBM 기사-공시 연결과 RAG 대상 재선정")
    parser.add_argument("--apply", action="store_true", help="DB의 rag_target·filter_reason을 바꾼다")
    parser.add_argument("--window", type=int, default=WINDOW_DAYS, help="기사 발행일 기준 ±일수")
    args = parser.parse_args()
    main(apply=args.apply, window_days=args.window)
