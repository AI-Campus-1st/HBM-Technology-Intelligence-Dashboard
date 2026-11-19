-- 04. 기업별 HBM 보도 감성 월별 추이 (LLM 분류 결과)
--
-- 질문: SK하이닉스·삼성전자의 HBM 보도 논조는 시기별로 어떻게 달라졌나? 급증 구간 달에는 어땠나?
--       대시보드 탭 1의 감성 추이 차트와 리포트 4장의 입력.
--
-- 기준
-- - 기간·partial: 01·02와 같다. 기사가 없는 달도 두 기업 모두 0으로 남긴다 (월 × 기업 격자).
-- - 기사: 중복 제외(is_duplicate = 0), HBM 관련도 '핵심'·'관련' (LLM 분류 대상과 같다).
-- - 감성: news_analysis의 프롬프트 버전 sent_v2 (src/llm/prompts.py PROMPT_VERSION과 같아야 한다 — 테스트가 확인).
--   '해당없음'(그 기업이 기사에 나오지 않음)은 그 기업의 기사 수·비율에서 뺀다. articles = 그 기업이 등장한 HBM 기사 수.
-- - net_sentiment = (긍정 − 부정) / 등장 기사 수 (−1 ~ 1). 등장 기사가 없으면 NULL.
-- - net_ma3: 그 달 포함 최근 3개월의 긍정·부정·기사 수 합계로 계산한 순감성 (월 기사 수가 적어 흔들리는 것을 줄임).
--   단순히 월별 net_sentiment를 평균하지 않고 합계로 계산해, 기사가 많은 달이 더 큰 비중을 갖는다.
-- - is_issue_month: 그 달이 급증 구간(issues, HBM)에 걸치면 1.
-- - 주의: LLM 판정이며 표본 검수 정확도(리포트 4장)를 함께 봐야 한다. 감성 ≠ 실제 사업 성과.
--
-- 실행: python -m src.eda.news_sql_report  (classify 다음. 결과: outputs/reports/sql04_company_sentiment_monthly.csv)
-- 담당: 김한승 (이슈 분석) / Day 5

WITH RECURSIVE
params(start_date, end_date, prompt_version) AS (
    VALUES ('2023-10-19', '2026-10-19', 'sent_v2')
),
months(month) AS (
    SELECT substr(start_date, 1, 7) FROM params
    UNION ALL
    SELECT strftime('%Y-%m', month || '-01', '+1 month')
    FROM months, params
    WHERE month < substr(end_date, 1, 7)
),
companies(company) AS (
    VALUES ('SK하이닉스'), ('삼성전자')
),
labeled AS (   -- 기사 1건 → 기업별 2행 (세로로 펼침)
    SELECT substr(n.published_at, 1, 7) AS month, 'SK하이닉스' AS company, a.sentiment_skh AS label
    FROM news AS n
    JOIN news_tag AS t ON t.news_id = n.news_id AND t.tag_type = 'tech' AND t.tag = 'HBM'
                      AND t.relevance IN ('핵심', '관련')
    JOIN news_analysis AS a ON a.news_id = n.news_id
    JOIN params AS p ON a.prompt_version = p.prompt_version
    WHERE n.is_duplicate = 0
    UNION ALL
    SELECT substr(n.published_at, 1, 7), '삼성전자', a.sentiment_sec
    FROM news AS n
    JOIN news_tag AS t ON t.news_id = n.news_id AND t.tag_type = 'tech' AND t.tag = 'HBM'
                      AND t.relevance IN ('핵심', '관련')
    JOIN news_analysis AS a ON a.news_id = n.news_id
    JOIN params AS p ON a.prompt_version = p.prompt_version
    WHERE n.is_duplicate = 0
),
monthly AS (
    SELECT month, company,
           SUM(CASE WHEN label = '긍정' THEN 1 ELSE 0 END) AS positive,
           SUM(CASE WHEN label = '중립' THEN 1 ELSE 0 END) AS neutral,
           SUM(CASE WHEN label = '부정' THEN 1 ELSE 0 END) AS negative
    FROM labeled
    WHERE label <> '해당없음'
    GROUP BY month, company
),
grid AS (
    SELECT m.month, c.company,
           CASE WHEN (m.month = substr(p.start_date, 1, 7) AND substr(p.start_date, 9, 2) <> '01')
                  OR (m.month = substr(p.end_date, 1, 7) AND strftime('%m', p.end_date, '+1 day') = strftime('%m', p.end_date))
                THEN 1 ELSE 0 END AS partial,
           COALESCE(s.positive, 0) AS positive,
           COALESCE(s.neutral, 0)  AS neutral,
           COALESCE(s.negative, 0) AS negative,
           CASE WHEN EXISTS (SELECT 1 FROM issues AS i
                             WHERE i.tech_tag = 'HBM'
                               AND m.month BETWEEN substr(i.start_date, 1, 7) AND substr(i.end_date, 1, 7))
                THEN 1 ELSE 0 END AS is_issue_month
    FROM months AS m
    CROSS JOIN companies AS c
    CROSS JOIN params AS p
    LEFT JOIN monthly AS s ON s.month = m.month AND s.company = c.company
),
windowed AS (
    SELECT *,
           positive + neutral + negative AS articles,
           SUM(positive) OVER w AS pos_3m,
           SUM(negative) OVER w AS neg_3m,
           SUM(positive + neutral + negative) OVER w AS n_3m
    FROM grid
    WINDOW w AS (PARTITION BY company ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)
)
SELECT month, company, partial, articles, positive, neutral, negative,
       1.0 * (positive - negative) / NULLIF(articles, 0) AS net_sentiment,
       1.0 * positive / NULLIF(articles, 0)              AS positive_share,
       1.0 * negative / NULLIF(articles, 0)              AS negative_share,
       1.0 * (pos_3m - neg_3m) / NULLIF(n_3m, 0)         AS net_ma3,
       is_issue_month
FROM windowed
ORDER BY company, month;
