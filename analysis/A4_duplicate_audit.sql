-- A4: READ ONLY. Identify duplicate B&R plans, no suppression and no live writes.
-- Exact definition from handoff (symbol, direction, second, entry at 6dp, SL at 6dp).
WITH marked AS (
 SELECT seq,sig_id,symbol,direction,created_ts,entry,sl,
 row_number() OVER (
   PARTITION BY symbol,direction,round(created_ts),round(entry::numeric,6),round(sl::numeric,6)
   ORDER BY seq
 ) AS duplicate_rank
 FROM br_test_signal
)
SELECT count(*) AS total,
       count(*) FILTER (WHERE duplicate_rank=1) AS unique_plans,
       count(*) FILTER (WHERE duplicate_rank>1) AS duplicate_rows,
       count(DISTINCT (symbol,direction,floor(created_ts/900),direction))
           FILTER (WHERE duplicate_rank>1) AS duplicate_15m_clusters
FROM marked;
