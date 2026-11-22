-- 事实卡查询模板 · 课程数据库（SQLite，只读）
--
-- 这个文件是课程写好的现成查询，配合《数据事实卡模板》E 栏用。里面只有四段：
--   E4 区级市场基准、E5 评分“当期”、E6 同比舍入：每段把两种读法各算一遍，输出里有一列 abs_diff，是两种读法的差；
--   E8 模拟数据声明：只取 `meta` 表 `notice` 原文。
-- E1、E2、E3、E7 不配查询，只从口径表或运营手册读出歧义，写进事实卡。
-- 学员不改、不重写这些查询：把文件交给 DSH 里的 agent，请它只读地一段一段原样运行，输出存进 records/fact_runs.txt，
-- 你看输出填事实卡 E 栏。
--
-- 只读打开（请 agent 用下面任一种，都不要用可写方式打开）：
--   Python：sqlite3.connect("file:<库文件路径>?mode=ro", uri=True)
--   命令行：sqlite3 -readonly <库文件路径>，进了提示符再 .read 本文件
-- 用 mode=ro 打开后，写语句会被 SQLite 自己拒掉；跑完不要再用写模式打开一次。
--
-- 库文件指纹（前后对比用）：
--   python v2/lab/tools/db_fingerprint.py <库文件路径>
--   输出四行：db_fingerprint v1 / db / bytes / sha256。把这次输出存成文件。
--   python v2/lab/tools/db_fingerprint.py <库文件路径> 上次输出.txt
--   再跑一次并带上刚才那个文件，会多打印 compare_sha256 与 result 两行。
--   退出码：0 未比对或结果不变；1 结果已变；2 参数或读文件出错。
--   课程库全程只读，收工那一次末行应当是“不变”。
--
-- 示例窗口：区只用 D08，时间窗只用 2026Q3（2026-07-01 至 2026-09-30）与 2025Q3（2025-07-01 至 2025-09-30）。

-- ============================================================
-- E4 区级市场基准：一个区一个数，由同区同房型的月度值合成没写死（M-09，核实）理解A：各房型简单平均
-- E4 区级市场基准：一个区一个数，由同区同房型的月度值合成没写死（M-09，核实）理解B：按房型房源数加权平均（D08，2026Q3）
WITH w AS (
  SELECT room_type, COUNT(*) AS n
  FROM listings
  WHERE district_id = 'D08'
    AND online_date <= '2026-09-30' AND (offline_date IS NULL OR offline_date > '2026-09-30')
  GROUP BY room_type
),
b AS (
  SELECT m.occupancy_rate AS occ, COALESCE(w.n, 0) AS n
  FROM market_benchmark m LEFT JOIN w ON w.room_type = m.room_type
  WHERE m.district_id = 'D08' AND m.month BETWEEN '2026-07' AND '2026-09'
)
SELECT ROUND(AVG(occ), 4)                                     AS simple_avg,
       ROUND(SUM(occ * n) * 1.0 / SUM(n), 4)                  AS weighted_avg,
       ROUND(ABS(AVG(occ) - SUM(occ * n) * 1.0 / SUM(n)), 4)  AS abs_diff
FROM b;

-- ============================================================
-- E5 评分“当期”按哪个日期归期（M-07、Q-05，核实）理解A：按评论日期 review_date 落在期内
-- E5 评分“当期”按哪个日期归期（M-07、Q-05，核实）理解B：按评论所属订单的入住日 checkin_date 落在期内（D08，2026Q3）
WITH a AS (
  SELECT r.rating
  FROM reviews r JOIN listings l ON l.listing_id = r.listing_id
  WHERE l.district_id = 'D08' AND r.rating IS NOT NULL
    AND r.review_date BETWEEN '2026-07-01' AND '2026-09-30'
),
b AS (
  SELECT r.rating
  FROM reviews r
  JOIN listings l ON l.listing_id = r.listing_id
  JOIN bookings k ON k.booking_id = r.booking_id
  WHERE l.district_id = 'D08' AND r.rating IS NOT NULL
    AND k.checkin_date BETWEEN '2026-07-01' AND '2026-09-30'
)
SELECT (SELECT COUNT(*) FROM a)                AS n_by_review_date,
       ROUND((SELECT AVG(rating) FROM a), 4)   AS avg_by_review_date,
       (SELECT COUNT(*) FROM b)                AS n_by_checkin_date,
       ROUND((SELECT AVG(rating) FROM b), 4)   AS avg_by_checkin_date,
       ROUND(ABS((SELECT AVG(rating) FROM a) - (SELECT AVG(rating) FROM b)), 4) AS abs_diff;

-- ============================================================
-- E6 同比：先算差再舍入，还是先舍入再算差（T-03、C-06，核实）理解A：原值相减，最后舍入到 3 位小数（即百分数一位）
-- E6 同比：先算差再舍入，还是先舍入再算差（T-03、C-06，核实）理解B：两期各自先舍入到 3 位小数，再相减（D08，2026Q3 对 2025Q3）
WITH RECURSIVE days(d) AS (
  SELECT '2025-07-01' UNION ALL SELECT date(d, '+1 day') FROM days WHERE d < '2026-09-30'
),
period_days AS (
  SELECT d,
         CASE WHEN d BETWEEN '2026-07-01' AND '2026-09-30' THEN 'cur'
              WHEN d BETWEEN '2025-07-01' AND '2025-09-30' THEN 'prev' END AS series
  FROM days
),
sellable AS (
  SELECT pd.series, COUNT(*) AS sellable_nights
  FROM listings l
  JOIN period_days pd ON pd.series IS NOT NULL
                     AND pd.d >= l.online_date AND (l.offline_date IS NULL OR pd.d < l.offline_date)
  WHERE l.district_id = 'D08'
    AND NOT EXISTS (SELECT 1 FROM owner_blocks o
                    WHERE o.listing_id = l.listing_id AND pd.d BETWEEN o.start_date AND o.end_date)
  GROUP BY pd.series
),
sold AS (
  SELECT CASE WHEN k.checkin_date BETWEEN '2026-07-01' AND '2026-09-30' THEN 'cur'
              WHEN k.checkin_date BETWEEN '2025-07-01' AND '2025-09-30' THEN 'prev' END AS series,
         SUM(k.nights) AS sold_nights
  FROM bookings k JOIN listings l ON l.listing_id = k.listing_id
  WHERE l.district_id = 'D08' AND k.status = '完成'
    AND (k.checkin_date BETWEEN '2026-07-01' AND '2026-09-30'
         OR k.checkin_date BETWEEN '2025-07-01' AND '2025-09-30')
  GROUP BY series
),
occ AS (
  SELECT s.series, 1.0 * so.sold_nights / s.sellable_nights AS v
  FROM sellable s JOIN sold so ON so.series = s.series
),
x AS (
  SELECT (SELECT v FROM occ WHERE series = 'cur')  AS cur,
         (SELECT v FROM occ WHERE series = 'prev') AS prev
)
SELECT ROUND(cur, 6)                                    AS occ_2026q3_raw,
       ROUND(prev, 6)                                   AS occ_2025q3_raw,
       ROUND(cur - prev, 3)                             AS yoy_round_after_subtract,
       ROUND(ROUND(cur, 3) - ROUND(prev, 3), 3)         AS yoy_round_before_subtract,
       ROUND(ABS(ROUND(cur - prev, 3) - (ROUND(cur, 3) - ROUND(prev, 3))), 3) AS abs_diff
FROM x;

-- ============================================================
-- E8 模拟数据声明在库里的位置，页面须逐字显示（`meta` 表 `notice` 字段）只取原文
SELECT value AS notice FROM meta WHERE key = 'notice';

-- ============================================================
-- 看输出时：
--   1. abs_diff 与默认容差比：比例类 0.001，金额类 0.01 元，评分按比例档 0.001；大于容差记“超”，否则记“没超”。
--   2. 不论超不超，E4、E5、E6 都点名进任务书第 5 栏，选哪种读法由 lead 列 A/B 问你；这个文件里只留查询和输出，不写结论。
--   3. E8 不算差值，原文逐字抄进事实卡 E 栏。
--   4. 收工前带上第一次的指纹输出，再跑一次 db_fingerprint.py，末行应是“不变”。
