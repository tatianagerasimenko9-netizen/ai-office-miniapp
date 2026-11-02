-- Сирі унікальні плани B&R: seq|sym|dir|created_ts|entry|sl|tp1:S/R,tp2,tp3 (S=structure,R=R-multiple)|EVENT@touched_ts,...
select string_agg(line, E'\n' order by seq) csv from (
 select s.seq, concat_ws('|', s.seq, replace(s.symbol,'USDT',''), left(s.direction,1), round(s.created_ts)::bigint,
  trim_scale(round(s.entry::numeric,6)), trim_scale(round(s.sl::numeric,6)),
  (select string_agg(trim_scale(round((t->>'p')::numeric,6))::text||':'||case when t->>'src' like 'structure%' then 'S' else 'R' end, ',' order by o)
     from json_array_elements(s.targets_json::json) with ordinality as x(t,o)),
  (select string_agg(e.level||'@'||round(e.touched_ts)::bigint, ',' order by e.touched_ts) from br_test_event e where e.sig_id=s.sig_id)) line
 from (select distinct on (symbol,direction,round(created_ts),round(entry::numeric,6),round(sl::numeric,6)) *
       from br_test_signal order by symbol,direction,round(created_ts),round(entry::numeric,6),round(sl::numeric,6),seq) s) q;
