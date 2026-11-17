-- 01. 월별 수집 기사·중복(재배포) 기사·중복률
--
-- 질문: 매달 수집된 기사 중 같은 기사의 재배포가 얼마나 섞여 있었나? 중복을 빼면 분석 대상은 몇 건인가?
--       기사 수집량이 달마다 크게 달라서(68~657건) 비중으로 분석한다는 판단의 근거 표이기도 하다.
--
-- 기준
-- - 기간: 분석 기간 2023-10-19 ~ 2026-10-19. 기사가 없는 달도 0으로 남긴다 (재귀 CTE로 달 목록을 만든다).
--   첫 달이 1일에 시작하지 않거나 마지막 달이 말일에 끝나지 않으면 partial = 1 (disclosure_trend.is_partial과 같은 기준).
-- - 중복: preprocess.py가 표시한 news.is_duplicate = 1 (정규화 제목이 7일 안에 같은 기사). 대표 기사는 0으로 남는다.
-- - articles = 중복 제외 기사 수 = 이후 모든 뉴스 분석의 분모.
--
-- 실행: python -m src.eda.news_sql_report  (결과: outputs/reports/sql01_news_monthly_dedup.csv)
-- 담당: 김한승 (이슈 분석) / Day 3

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
monthly AS (
    SELECT substr(published_at, 1, 7) AS month,
           COUNT(*)                   AS raw_articles,
           SUM(is_duplicate)          AS duplicates
    FROM news
    GROUP BY 1
)
SELECT m.month,
       CASE WHEN (m.month = substr(p.start_date, 1, 7) AND substr(p.start_date, 9, 2) <> '01')
              OR (m.month = substr(p.end_date, 1, 7) AND strftime('%m', p.end_date, '+1 day') = strftime('%m', p.end_date))
            THEN 1 ELSE 0 END                                   AS partial,
       COALESCE(s.raw_articles, 0)                              AS raw_articles,
       COALESCE(s.duplicates, 0)                                AS duplicates,
       COALESCE(s.raw_articles, 0) - COALESCE(s.duplicates, 0)  AS articles,
       ROUND(1.0 * s.duplicates / NULLIF(s.raw_articles, 0), 4) AS dup_rate
FROM months AS m
CROSS JOIN params AS p
LEFT JOIN monthly AS s ON s.month = m.month
ORDER BY m.month;
