-- 02. 월별 HBM 기사 수·비중과 추세 (윈도 함수)
--
-- 질문: HBM 보도 비중은 달마다 어떻게 변했나? 전월보다 얼마나 뛰었고, 3개월 흐름과 비교하면 어떤가?
--       급증 탐지(spike_detection.py)의 입력과 같은 숫자를 SQL만으로 재현해 교차 확인한다.
--
-- 기준 (src/eda/news_trend.py monthly_hbm과 같다 — tests/test_news_sql.py가 대조)
-- - 기간·partial: 01과 같다. 기사가 없는 달의 비중은 0.
-- - 분모 total: 중복 제외 기사 수 (news.is_duplicate = 0).
-- - HBM 기사 hbm: news_tag HBM 관련도 '핵심' 또는 '관련'. hbm_core는 '핵심'(제목 포함)만 — 보수적 교차 지표.
-- - share_change: 전월 대비 비중 차이 (LAG). share_ma3: 그 달 포함 최근 3개월 단순 평균 (부분 월 포함, 참고용).
-- - share_rank: 부분 월을 뺀 달 중 비중 순위 (RANK, 1 = 가장 높음). 부분 월은 NULL.
-- - 급증 판정은 여기서 하지 않는다. 판정 기준(rolling6m_2sigma_exclude_spikes_min10_v1)은 Python과 issues 테이블이 정본.
--
-- 실행: python -m src.eda.news_sql_report  (결과: outputs/reports/sql02_hbm_monthly_share.csv)
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
articles AS (
    SELECT substr(n.published_at, 1, 7) AS month,
           t.relevance                  AS hbm
    FROM news AS n
    LEFT JOIN news_tag AS t
           ON t.news_id = n.news_id AND t.tag_type = 'tech' AND t.tag = 'HBM'
    WHERE n.is_duplicate = 0
),
monthly AS (
    SELECT month,
           COUNT(*)                                                AS total,
           SUM(CASE WHEN hbm IN ('핵심', '관련') THEN 1 ELSE 0 END) AS hbm,
           SUM(CASE WHEN hbm = '핵심' THEN 1 ELSE 0 END)            AS hbm_core
    FROM articles
    GROUP BY month
),
base AS (
    SELECT m.month,
           CASE WHEN (m.month = substr(p.start_date, 1, 7) AND substr(p.start_date, 9, 2) <> '01')
                  OR (m.month = substr(p.end_date, 1, 7) AND strftime('%m', p.end_date, '+1 day') = strftime('%m', p.end_date))
                THEN 1 ELSE 0 END                                       AS partial,
           COALESCE(s.total, 0)                                         AS total,
           COALESCE(s.hbm, 0)                                           AS hbm,
           COALESCE(s.hbm_core, 0)                                      AS hbm_core,
           COALESCE(1.0 * s.hbm / NULLIF(s.total, 0), 0.0)              AS share,
           COALESCE(1.0 * s.hbm_core / NULLIF(s.total, 0), 0.0)         AS share_core
    FROM months AS m
    CROSS JOIN params AS p
    LEFT JOIN monthly AS s ON s.month = m.month
)
SELECT month, partial, total, hbm, hbm_core, share, share_core,
       share - LAG(share) OVER (ORDER BY month)                            AS share_change,
       AVG(share) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS share_ma3,
       CASE WHEN partial = 0
            THEN RANK() OVER (PARTITION BY partial ORDER BY share DESC) END AS share_rank
FROM base
ORDER BY month;
