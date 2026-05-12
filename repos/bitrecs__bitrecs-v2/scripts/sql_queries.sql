SELECT ags.*, ag.model, ag.provider, ag.miner_uid
FROM agent_scores AS ags
LEFT JOIN agents ag ON ags.agent_id = ag.agent_id
WHERE ags.set_id = (SELECT MAX(set_id) FROM evaluation_sets)
AND ags.agent_id NOT IN (SELECT agent_id FROM benchmark_agent_ids)
ORDER BY ags.created_at DESC;


SELECT a.name, a.miner_uid, ass.final_score, a.*,  ass.created_at as score_created_at, ass.set_id, ass.approved, ass.validator_count
FROM agents a
JOIN agent_scores ass ON a.agent_id = ass.agent_id
WHERE ass.set_id = (SELECT MAX(set_id) FROM evaluation_sets)
AND a.agent_id NOT IN (SELECT agent_id FROM benchmark_agent_ids)
ORDER BY ROUND(ass.final_score::numeric, 6) DESC, a.created_at ASC


SELECT 
    schemaname,
    relname                  AS table_name,
    pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
    pg_size_pretty(pg_table_size(relid))          AS table_size,
    pg_size_pretty(pg_indexes_size(relid))        AS indexes_size,
    n_live_tup                                    AS row_count_live_est,
    n_dead_tup                                    AS dead_tuples
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC
LIMIT 20;


-- INSERT INTO evaluation_sets (set_id, set_group, problem_name)
-- VALUES 
--   (7, 'screener_1', 'bitrecs_basic_daily'),
--   (7, 'screener_1', 'bitrecs_artifact_pricing'),
--   (7, 'screener_2', 'bitrecs_safe_daily'),
--   (7, 'screener_2', 'bitrecs_haystack_daily'),
--   (7, 'screener_2', 'bitrecs_qos_daily'),
--   (7, 'validator', 'bitrecs_prompt_daily'),
--   (7, 'validator', 'bitrecs_reason_daily'),
--   (7, 'validator', 'bitrecs_sku_daily'),
--   (7, 'validator', 'bitrecs_predict_daily'),  
--   (7, 'validator', 'amazon_health_and_personal_care_100'),  
--   (7, 'validator', 'ndcg_at10_curated_all_beauty_100'),
--   (7, 'validator', 'ndcg_at10_curated_electronics_100');


SELECT miner_hotkey, MIN(block) as first_block 
FROM hotkey_gist 
WHERE block != 0
GROUP BY miner_hotkey
ORDER BY first_block


SELECT * FROM AGENTS WHERE created_at >= (
SELECT MIN(created_at) FROM evaluation_sets
WHERE set_id = (SELECT MAX(set_id) FROM evaluation_sets))
ORDER BY created_at DESC



SELECT 
    e.agent_id,  
    a.name,
    r.evaluation_run_id,
    r.evaluation_id,
    r.problem_name,
    r.status,
    r.test_results,
    r.created_at,
    i.provider,
    i.model,
    i.temperature,
    i.status_code,
    i.num_input_tokens,
    i.num_output_tokens,
    i.cost_usd  
FROM evaluation_runs r
LEFT JOIN inferences i ON r.evaluation_run_id = i.evaluation_run_id
LEFT JOIN evaluations e ON r.evaluation_id = e.evaluation_id
INNER JOIN agents a ON e.agent_id = a.agent_id
WHERE a.agent_id = ''



SELECT 
    DATE(created_at) AS day,
    SUM(COALESCE(num_input_tokens, 0) + COALESCE(num_output_tokens, 0)) AS total_tokens
FROM 
    public.inferences
GROUP BY 
    DATE(created_at)
ORDER BY 
    day desc;


WITH zero_vec AS (
  SELECT array_agg(0)::vector AS zero_vector
  FROM generate_series(1, 768)
)
SELECT 
  embedding_id,
  agent_text,
  embedding_provider,
  embedding_model,
  embedding_vector <-> zero_vector AS l2_norm
FROM public.agent_embeddings, zero_vec
ORDER BY embedding_vector <-> zero_vector DESC
LIMIT 20;


SELECT 
  a.name,
  ae2.embedding_id,
  ae2.agent_id,  
  ae2.embedding_provider,
  ae2.embedding_model,
  (ae1.embedding_vector <=> ae2.embedding_vector) AS cosine_distance,
  (ae1.embedding_vector <-> ae2.embedding_vector) AS euclidean_distance
FROM public.agent_embeddings ae1
JOIN public.agent_embeddings ae2 
  ON ae1.embedding_id <> ae2.embedding_id
LEFT JOIN agents a ON ae2.agent_id = a.agent_id
WHERE ae1.agent_id = 'XXX'::uuid
ORDER BY ae1.embedding_vector <=> ae2.embedding_vector ASC
LIMIT 100;


WITH sampled_pairs AS (
  SELECT 
    a.embedding_vector AS v1,
    b.embedding_vector AS v2
  FROM public.agent_embeddings a
  JOIN public.agent_embeddings b 
    ON a.embedding_id < b.embedding_id          -- guarantees unique pairs, no self-matches
  ORDER BY random()                             -- random shuffle
  LIMIT 10000                                   -- change this number as needed (5000–20000 is usually fine)
)
SELECT 
  COUNT(*) AS num_pairs_sampled,
  AVG(v1 <=> v2)                                      AS avg_cosine_distance,
  MIN(v1 <=> v2)                                      AS closest_pair_distance,
  MAX(v1 <=> v2)                                      AS farthest_pair_distance,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY v1 <=> v2) AS median_cosine_distance,
  STDDEV(v1 <=> v2)                                   AS stddev_cosine_distance,
  AVG(CASE WHEN v1 <=> v2 < 0.2 THEN 1.0 ELSE 0.0 END) * 100 AS percent_very_similar
FROM sampled_pairs;



WITH centroid_cte AS (
  SELECT AVG(embedding_vector) AS global_centroid
  FROM public.agent_embeddings
)
SELECT 
  embedding_id,
  agent_text,
  embedding_provider,
  embedding_model,
  (embedding_vector <=> global_centroid) AS cosine_distance_to_centroid
FROM public.agent_embeddings, centroid_cte  
ORDER BY embedding_vector <=> global_centroid ASC   -- smallest = most central
LIMIT 10;


WITH centroid_cte AS (
  SELECT AVG(embedding_vector) AS global_centroid
  FROM public.agent_embeddings
)
SELECT DISTINCT ON (ae.agent_id)          -- One row per agent
  ae.embedding_id,
  a.name AS agent_name,
  ae.agent_id,
  ae.agent_text,
  ae.embedding_provider,
  ae.embedding_model,
  (ae.embedding_vector <=> global_centroid) AS cosine_distance_to_centroid
FROM public.agent_embeddings ae
CROSS JOIN centroid_cte
LEFT JOIN agents a ON ae.agent_id = a.agent_id
ORDER BY ae.agent_id, ae.embedding_vector <=> global_centroid ASC;
