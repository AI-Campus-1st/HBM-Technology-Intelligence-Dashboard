-- 05_2. 기업·공시 성격별 건수의 12개월 구간 비교 (직전 구간 대비 증감) + 원문 확보·RAG 대상 건수
--
-- 질문: 투자·설비, 풍문·해명 같은 공시가 해마다 늘었나 줄었나? 그중 원문을 확보해 RAG에 쓰는 건 몇 건인가?
--
-- 기준
-- - 분석 기간 3년(2023-10-19 ~ 2026-10-19)을 12개월씩 Y1·Y2·Y3로 나눈다.
--   달력 연도로 나누면 2023년(2.5개월)·2026년(9.5개월)이 일부 기간이라 비교가 틀어진다.
-- - 공시가 없는 기업·구간·성격 조합도 0으로 남겨 LAG가 바로 앞 구간과 비교하게 한다.
-- - 공시 성격 CASE는 05_1과 같다 (원본: src/eda/disclosure_trend.py CATEGORY_RULES, 사건성 = is_event 1).
--   05_1에서는 비사건성을 하나로 묶었지만 여기서는 비사건성 성격도 나눠서 센다.
-- - rag_target은 news_link --apply 이후 값이다 (link_v2: A + HBM 언급 + 실적 외 주제로 기사와 연결된 공시).
--
-- 실행: python -m src.dart.sql_report  (결과: outputs/reports/sql05_2_disclosure_category_yoy.csv)
-- 담당: 한도윤 (공시 분석) / Day 3

WITH
periods(period, start_date, end_date) AS (
    VALUES ('Y1', '2023-10-19', '2024-10-18'),
           ('Y2', '2024-10-19', '2025-10-18'),
           ('Y3', '2025-10-19', '2026-10-19')
),
categories(category, is_event, sort_key) AS (
    VALUES ('투자·설비', 1, 1), ('실적', 1, 2), ('사업계획', 1, 3), ('풍문·해명', 1, 4), ('공급계약', 1, 5),
           ('자본·주주환원', 0, 6), ('지배구조·주총', 0, 7), ('지분변동', 0, 8), ('정기보고서', 0, 9),
           ('공정위 거래', 0, 10), ('기타', 0, 11)
),
categorized AS (
    SELECT
        d.corp_name,
        p.period,
        d.text_status,
        d.rag_target,
        CASE
            WHEN report_nm LIKE '%신규시설투자%' OR report_nm LIKE '%투자판단관련%'
              OR report_nm LIKE '%유형자산취득%' OR report_nm LIKE '%타법인주식및출자증권취득%'
              OR report_nm LIKE '%영업양수%' OR report_nm LIKE '%영업양도%'           THEN '투자·설비'
            WHEN report_nm LIKE '%영업(잠정)실적%' OR report_nm LIKE '%매출액또는손익구조%' THEN '실적'
            WHEN report_nm LIKE '%장래사업%' OR report_nm LIKE '%기업가치제고계획%'      THEN '사업계획'
            WHEN report_nm LIKE '%조회공시요구%' OR report_nm LIKE '%풍문또는보도%'      THEN '풍문·해명'
            WHEN report_nm LIKE '%단일판매%' OR report_nm LIKE '%공급계약%'              THEN '공급계약'
            WHEN report_nm LIKE '%자기주식%' OR report_nm LIKE '%주식소각%' OR report_nm LIKE '%배당%'
              OR report_nm LIKE '%주주명부%' OR report_nm LIKE '%유상증자%' OR report_nm LIKE '%증권예탁증권%'
              OR report_nm LIKE '%해외증권시장%' OR report_nm LIKE '%교환사채%' OR report_nm LIKE '%전환가액%'
              OR report_nm LIKE '%주식관련사채%'                                        THEN '자본·주주환원'
            WHEN report_nm LIKE '%주주총회%' OR report_nm LIKE '%대표이사%' OR report_nm LIKE '%지배구조%'
              OR report_nm LIKE '%의결권대리행사%'                                      THEN '지배구조·주총'
            WHEN report_nm LIKE '%최대주주등소유주식변동%'                               THEN '지분변동'
            WHEN report_nm LIKE '%사업보고서%' OR report_nm LIKE '%반기보고서%'
              OR report_nm LIKE '%분기보고서%' OR report_nm LIKE '%감사보고서제출%'      THEN '정기보고서'
            WHEN report_nm LIKE '%계열회사%' OR report_nm LIKE '%특수관계인%'
              OR report_nm LIKE '%대규모기업집단%' OR report_nm LIKE '%지급수단별%'      THEN '공정위 거래'
            ELSE '기타'
        END AS category
    FROM disclosure AS d
    JOIN periods AS p ON d.rcept_dt BETWEEN p.start_date AND p.end_date
),
grid AS (
    SELECT co.corp_name, p.period, c.category, c.is_event, c.sort_key
    FROM (SELECT DISTINCT corp_name FROM disclosure) AS co
    CROSS JOIN periods AS p
    CROSS JOIN categories AS c
),
counts AS (
    SELECT
        g.corp_name, g.period, g.category, g.is_event, g.sort_key,
        COUNT(x.category)                         AS disclosures,
        COALESCE(SUM(x.text_status = '확보'), 0)  AS with_text,
        COALESCE(SUM(x.rag_target), 0)            AS rag_targets
    FROM grid AS g
    LEFT JOIN categorized AS x
           ON x.corp_name = g.corp_name AND x.period = g.period AND x.category = g.category
    GROUP BY g.corp_name, g.period, g.category
)
SELECT
    corp_name,
    category,
    is_event,
    period,
    disclosures,
    LAG(disclosures) OVER w               AS prev_disclosures,
    disclosures - LAG(disclosures) OVER w AS change,
    with_text,
    rag_targets
FROM counts
WINDOW w AS (PARTITION BY corp_name, category ORDER BY period)
ORDER BY corp_name, sort_key, period;
