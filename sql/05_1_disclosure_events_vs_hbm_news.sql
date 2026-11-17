-- 05_1. 기업·월별 사건성 공시 건수와 HBM 기사 수 (같은 월 축)
--
-- 질문: HBM 기사가 몰린 달에 회사도 투자·실적·해명 같은 공시를 냈나?
--       급증 구간(issues)이 나오면 이 표에서 그 달의 사건성 공시를 바로 찾는다 (issue_evidence 후보).
--
-- 기준
-- - 기간: 분석 기간 2023-10-19 ~ 2026-10-19. 공시가 없는 달도 0으로 남긴다 (재귀 CTE로 달 목록을 만든다).
--   첫 달·마지막 달은 일부 기간이라 partial = 1.
-- - 공시: disclosure 전체 (원문 확보·RAG 여부와 관계없이). 공시 성격은 공시명으로 정한다.
--   CASE 순서·패턴은 src/eda/disclosure_trend.py CATEGORY_RULES와 같다 (tests/test_sql.py가 대조).
--   사건성 공시 = 투자·설비 / 실적 / 사업계획 / 풍문·해명 / 공급계약 (EVENT_CATEGORIES).
-- - 기사: HBM 태그 관련도 핵심·관련, 중복(재배포) 제외(is_duplicate = 0).
--   기업은 그 기사의 기업 태그로 센다. 두 기업이 모두 태그된 기사는 양쪽에 한 번씩 들어간다.
--
-- 실행: python -m src.dart.sql_report  (결과: outputs/reports/sql05_1_disclosure_events_vs_hbm_news.csv)
-- 담당: 한도윤 (공시 분석) / Day 3

WITH RECURSIVE
params(start_date, end_date) AS (
    VALUES ('2023-10-19', '2026-10-19')
),
months(month) AS (
    SELECT substr(start_date, 1, 7) FROM params
    UNION ALL
    SELECT strftime('%Y-%m', month || '-01', '+1 month')
    FROM months, params
    WHERE month < substr(end_date, 1, 7)
),
companies(corp_name) AS (
    SELECT DISTINCT corp_name FROM disclosure
),
categorized AS (
    SELECT
        corp_name,
        substr(rcept_dt, 1, 7) AS month,
        CASE
            WHEN report_nm LIKE '%신규시설투자%' OR report_nm LIKE '%투자판단관련%'
              OR report_nm LIKE '%유형자산취득%' OR report_nm LIKE '%타법인주식및출자증권취득%'
              OR report_nm LIKE '%영업양수%' OR report_nm LIKE '%영업양도%'           THEN '투자·설비'
            WHEN report_nm LIKE '%영업(잠정)실적%' OR report_nm LIKE '%매출액또는손익구조%' THEN '실적'
            WHEN report_nm LIKE '%장래사업%' OR report_nm LIKE '%기업가치제고계획%'      THEN '사업계획'
            WHEN report_nm LIKE '%조회공시요구%' OR report_nm LIKE '%풍문또는보도%'      THEN '풍문·해명'
            WHEN report_nm LIKE '%단일판매%' OR report_nm LIKE '%공급계약%'              THEN '공급계약'
            ELSE '기타(비사건성)'
        END AS category
    FROM disclosure, params
    WHERE rcept_dt BETWEEN start_date AND end_date
),
disclosure_monthly AS (
    SELECT
        corp_name,
        month,
        COUNT(*) AS disclosures,
        SUM(category <> '기타(비사건성)') AS event_disclosures,
        GROUP_CONCAT(DISTINCT CASE WHEN category <> '기타(비사건성)' THEN category END) AS event_categories
    FROM categorized
    GROUP BY corp_name, month
),
hbm_news AS (
    -- 중복 제외 HBM 핵심·관련 기사 (기사 단위로 한 번만)
    SELECT n.news_id, substr(n.published_at, 1, 7) AS month
    FROM news AS n
    JOIN news_tag AS t ON t.news_id = n.news_id
    CROSS JOIN params
    WHERE t.tag_type = 'tech' AND t.tag = 'HBM' AND t.relevance IN ('핵심', '관련')
      AND n.is_duplicate = 0
      AND n.published_at BETWEEN start_date AND end_date
),
news_monthly AS (
    SELECT c.tag AS corp_name, h.month, COUNT(DISTINCT h.news_id) AS hbm_news
    FROM hbm_news AS h
    JOIN news_tag AS c ON c.news_id = h.news_id AND c.tag_type = 'company'
    GROUP BY c.tag, h.month
)
SELECT
    m.month,
    co.corp_name,
    (m.month = substr(p.start_date, 1, 7) OR m.month = substr(p.end_date, 1, 7)) AS partial,
    COALESCE(d.disclosures, 0)       AS disclosures,
    COALESCE(d.event_disclosures, 0) AS event_disclosures,
    d.event_categories,
    COALESCE(nm.hbm_news, 0)         AS hbm_news
FROM months AS m
CROSS JOIN companies AS co
CROSS JOIN params AS p
LEFT JOIN disclosure_monthly AS d ON d.corp_name = co.corp_name AND d.month = m.month
LEFT JOIN news_monthly AS nm      ON nm.corp_name = co.corp_name AND nm.month = m.month
ORDER BY co.corp_name, m.month;
