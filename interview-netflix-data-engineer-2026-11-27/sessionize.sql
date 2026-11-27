-- Netflix Data Engineer interview, reported and representative question.
-- Sessionize play_events with a 30 minute inactivity gap.
-- Dialect: standard SQL with window functions (Spark SQL / BigQuery style).

WITH deduped AS (
  SELECT DISTINCT user_id, content_id, event_type, event_timestamp,
         position_sec, runtime_sec
  FROM play_events
),
flagged AS (
  SELECT *,
         CASE
           WHEN LAG(event_timestamp) OVER w IS NULL THEN 1
           WHEN event_timestamp - LAG(event_timestamp) OVER w > INTERVAL 30 MINUTE THEN 1
           ELSE 0
         END AS is_new_session
  FROM deduped
  WINDOW w AS (PARTITION BY user_id, content_id ORDER BY event_timestamp)
),
numbered AS (
  SELECT *,
         SUM(is_new_session) OVER (
           PARTITION BY user_id, content_id
           ORDER BY event_timestamp
           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
         ) AS session_seq
  FROM flagged
)
SELECT user_id,
       content_id,
       session_seq,
       MIN(event_timestamp) AS session_start,
       MAX(event_timestamp) AS session_end,
       MAX(position_sec) AS watch_sec,
       MAX(position_sec) >= 0.9 * MAX(runtime_sec) AS completed
FROM numbered
GROUP BY user_id, content_id, session_seq
ORDER BY user_id, content_id, session_seq;
