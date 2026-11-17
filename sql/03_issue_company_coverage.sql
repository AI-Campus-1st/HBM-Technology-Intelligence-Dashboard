-- 03. 급증 구간별 HBM 기사의 기업 점유 vs 구간 밖
--
-- 질문: HBM 보도가 몰린 구간마다 SK하이닉스·삼성전자 중 누가 더 많이 다뤄졌나?
--       급증 구간 밖의 평소 점유와 비교하면 어느 쪽 이슈였나? (보조 질문: 기업별 보도 비교)
--
-- 기준 (기업 점유 정의는 src/eda/news_trend.py company_monthly와 같다)
-- - HBM 기사: 중복 제외(is_duplicate = 0), HBM 관련도 '핵심'·'관련'.
-- - 구간: issues(tech_tag = 'HBM')의 start_date ~ end_date. 어떤 구간에도 들지 않으면 '(급증 구간 밖)'.
--   구간 밖에는 판정하지 않은 부분 월(2023-10, 2026-10)과 이력 부족 달도 들어간다.
-- - 기업: 그 기사의 기업 태그 관련도가 '핵심'·'관련'일 때만 센다 ('언급'은 정밀도가 낮아 제외).
--   두 기업이 함께 나오면 양쪽에 센다 (skh_share + sec_share가 1을 넘을 수 있다). both·neither를 같이 둔다.
-- - 분모는 그 구간의 HBM 기사 수. 구간 행의 hbm_articles는 issues.article_count와 같아야 한다.
-- - 기사 제목 기반 태깅이라 '최태원 SK회장'처럼 기업명 없는 기사는 SK하이닉스로 잡히지 않는다(과소 집계 가능).
--
-- 실행: python -m src.eda.news_sql_report  (spike_detection으로 issues를 만든 다음. 결과: outputs/reports/sql03_issue_company_coverage.csv)
-- 담당: 김한승 (이슈 분석) / Day 3

WITH
hbm AS (
    SELECT n.news_id, n.published_at
    FROM news AS n
    JOIN news_tag AS t
      ON t.news_id = n.news_id AND t.tag_type = 'tech' AND t.tag = 'HBM'
     AND t.relevance IN ('핵심', '관련')
    WHERE n.is_duplicate = 0
),
company AS (
    SELECT news_id,
           MAX(CASE WHEN tag = 'SK하이닉스' THEN 1 ELSE 0 END) AS skh,
           MAX(CASE WHEN tag = '삼성전자' THEN 1 ELSE 0 END)   AS sec
    FROM news_tag
    WHERE tag_type = 'company' AND relevance IN ('핵심', '관련')
    GROUP BY news_id
),
labeled AS (
    SELECT COALESCE(i.issue_id, '(급증 구간 밖)')   AS period,
           CASE WHEN i.issue_id IS NULL THEN 0 ELSE 1 END AS is_issue,
           i.start_date, i.end_date,
           COALESCE(c.skh, 0) AS skh,
           COALESCE(c.sec, 0) AS sec
    FROM hbm AS h
    LEFT JOIN issues AS i
           ON i.tech_tag = 'HBM' AND h.published_at BETWEEN i.start_date AND i.end_date
    LEFT JOIN company AS c ON c.news_id = h.news_id
)
SELECT period, is_issue, start_date, end_date,
       COUNT(*)                                             AS hbm_articles,
       SUM(skh)                                             AS skh_articles,
       SUM(sec)                                             AS sec_articles,
       SUM(CASE WHEN skh = 1 AND sec = 1 THEN 1 ELSE 0 END) AS both_articles,
       SUM(CASE WHEN skh = 0 AND sec = 0 THEN 1 ELSE 0 END) AS neither_articles,
       ROUND(1.0 * SUM(skh) / COUNT(*), 4)                  AS skh_share,
       ROUND(1.0 * SUM(sec) / COUNT(*), 4)                  AS sec_share
FROM labeled
GROUP BY period, is_issue, start_date, end_date
ORDER BY is_issue = 0, start_date;
