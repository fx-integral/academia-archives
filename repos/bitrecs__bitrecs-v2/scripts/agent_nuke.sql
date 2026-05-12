--DROP FUNCTION IF EXISTS delete_agent_report(UUID, BOOLEAN);

CREATE OR REPLACE FUNCTION delete_agent_report(p_agent_id UUID, dry_run BOOLEAN DEFAULT TRUE)
RETURNS TABLE(table_name TEXT, row_count BIGINT, mode TEXT, target_id UUID) AS $$
DECLARE
    v_agent_scores_count BIGINT;
    v_agent_embeddings_count BIGINT;
    v_approved_agents_count BIGINT;
    v_unapproved_agent_ids_count BIGINT;
    v_benchmark_agent_ids_count BIGINT;
    v_evaluation_payments_count BIGINT;
    v_inferences_count BIGINT;
    v_embeddings_count BIGINT;
    v_evaluation_run_logs_count BIGINT;
    v_evaluation_runs_count BIGINT;
    v_evaluations_count BIGINT;
    v_upload_attempts_count BIGINT;
    v_agents_count BIGINT;
    v_hotkey_gist_count BIGINT;
    v_mode TEXT;
BEGIN
    v_mode := CASE WHEN dry_run THEN 'DRY RUN (no changes made)' ELSE '*** LIVE DELETE ***' END;
    
    SELECT COUNT(*) INTO v_agent_scores_count FROM agent_scores a_s WHERE a_s.agent_id = p_agent_id;
    SELECT COUNT(*) INTO v_agent_embeddings_count FROM agent_embeddings ae WHERE ae.agent_id = p_agent_id;
    SELECT COUNT(*) INTO v_approved_agents_count FROM approved_agents aa WHERE aa.agent_id = p_agent_id;
    SELECT COUNT(*) INTO v_unapproved_agent_ids_count FROM unapproved_agent_ids ua WHERE ua.agent_id = p_agent_id;
    SELECT COUNT(*) INTO v_benchmark_agent_ids_count FROM benchmark_agent_ids ba WHERE ba.agent_id = p_agent_id;
    SELECT COUNT(*) INTO v_evaluation_payments_count FROM evaluation_payments ep WHERE ep.agent_id = p_agent_id;
    SELECT COUNT(*) INTO v_upload_attempts_count FROM upload_attempts u_a WHERE u_a.agent_id = p_agent_id;
    SELECT COUNT(*) INTO v_evaluations_count FROM evaluations ev WHERE ev.agent_id = p_agent_id;
    SELECT COUNT(*) INTO v_agents_count FROM agents ag WHERE ag.agent_id = p_agent_id;
    SELECT COUNT(*) INTO v_hotkey_gist_count FROM hotkey_gist hg WHERE hg.artifact_id = p_agent_id;

    SELECT COUNT(*) INTO v_inferences_count
    FROM inferences i
    INNER JOIN evaluation_runs er ON i.evaluation_run_id = er.evaluation_run_id
    INNER JOIN evaluations e ON er.evaluation_id = e.evaluation_id
    WHERE e.agent_id = p_agent_id;

    SELECT COUNT(*) INTO v_embeddings_count
    FROM embeddings emb
    INNER JOIN evaluation_runs er ON emb.evaluation_run_id = er.evaluation_run_id
    INNER JOIN evaluations e ON er.evaluation_id = e.evaluation_id
    WHERE e.agent_id = p_agent_id;

    SELECT COUNT(*) INTO v_evaluation_run_logs_count
    FROM evaluation_run_logs erl
    INNER JOIN evaluation_runs er ON erl.evaluation_run_id = er.evaluation_run_id
    INNER JOIN evaluations e ON er.evaluation_id = e.evaluation_id
    WHERE e.agent_id = p_agent_id;

    SELECT COUNT(*) INTO v_evaluation_runs_count
    FROM evaluation_runs er
    INNER JOIN evaluations e ON er.evaluation_id = e.evaluation_id
    WHERE e.agent_id = p_agent_id;
    
    RETURN QUERY SELECT 'agent_scores'::TEXT,        v_agent_scores_count,          v_mode, p_agent_id::UUID;
    RETURN QUERY SELECT 'agent_embeddings'::TEXT,    v_agent_embeddings_count,      v_mode, p_agent_id::UUID;
    RETURN QUERY SELECT 'approved_agents'::TEXT,     v_approved_agents_count,       v_mode, p_agent_id::UUID;
    RETURN QUERY SELECT 'unapproved_agent_ids'::TEXT,v_unapproved_agent_ids_count,  v_mode, p_agent_id::UUID;
    RETURN QUERY SELECT 'benchmark_agent_ids'::TEXT, v_benchmark_agent_ids_count,   v_mode, p_agent_id::UUID;
    RETURN QUERY SELECT 'evaluation_payments'::TEXT, v_evaluation_payments_count,   v_mode, p_agent_id::UUID;
    RETURN QUERY SELECT 'upload_attempts'::TEXT,     v_upload_attempts_count,       v_mode, p_agent_id::UUID;
    RETURN QUERY SELECT 'hotkey_gist'::TEXT,         v_hotkey_gist_count,           v_mode, p_agent_id::UUID;
    RETURN QUERY SELECT 'inferences'::TEXT,          v_inferences_count,            v_mode, p_agent_id::UUID;
    RETURN QUERY SELECT 'embeddings'::TEXT,          v_embeddings_count,            v_mode, p_agent_id::UUID;
    RETURN QUERY SELECT 'evaluation_run_logs'::TEXT, v_evaluation_run_logs_count,   v_mode, p_agent_id::UUID;
    RETURN QUERY SELECT 'evaluation_runs'::TEXT,     v_evaluation_runs_count,       v_mode, p_agent_id::UUID;
    RETURN QUERY SELECT 'evaluations'::TEXT,         v_evaluations_count,           v_mode, p_agent_id::UUID;
    RETURN QUERY SELECT 'agents'::TEXT,              v_agents_count,                v_mode, p_agent_id::UUID;

    IF v_agents_count = 0 THEN
        RETURN QUERY SELECT 'WARNING'::TEXT, 0::BIGINT, 'No agent found with ID ' || p_agent_id::TEXT, p_agent_id::UUID;
        RETURN;
    END IF;

    IF NOT dry_run THEN
        DELETE FROM agent_scores WHERE agent_id = p_agent_id;
        DELETE FROM agent_embeddings WHERE agent_id = p_agent_id;
        DELETE FROM approved_agents WHERE agent_id = p_agent_id;
        DELETE FROM unapproved_agent_ids WHERE agent_id = p_agent_id;
        DELETE FROM benchmark_agent_ids WHERE agent_id = p_agent_id;
        DELETE FROM evaluation_payments WHERE agent_id = p_agent_id;
        DELETE FROM upload_attempts WHERE agent_id = p_agent_id;
        DELETE FROM hotkey_gist WHERE artifact_id = p_agent_id;

        DELETE FROM inferences
        WHERE evaluation_run_id IN (
            SELECT er.evaluation_run_id
            FROM evaluation_runs er
            INNER JOIN evaluations e ON er.evaluation_id = e.evaluation_id
            WHERE e.agent_id = p_agent_id
        );

        DELETE FROM embeddings
        WHERE evaluation_run_id IN (
            SELECT er.evaluation_run_id
            FROM evaluation_runs er
            INNER JOIN evaluations e ON er.evaluation_id = e.evaluation_id
            WHERE e.agent_id = p_agent_id
        );

        DELETE FROM evaluation_run_logs
        WHERE evaluation_run_id IN (
            SELECT er.evaluation_run_id
            FROM evaluation_runs er
            INNER JOIN evaluations e ON er.evaluation_id = e.evaluation_id
            WHERE e.agent_id = p_agent_id
        );

        DELETE FROM evaluation_runs
        WHERE evaluation_id IN (
            SELECT evaluation_id FROM evaluations WHERE agent_id = p_agent_id
        );

        DELETE FROM evaluations WHERE agent_id = p_agent_id;
        DELETE FROM agents WHERE agent_id = p_agent_id;

        RETURN QUERY SELECT 'SUCCESS'::TEXT, 1::BIGINT, 'Agent ' || p_agent_id::TEXT || ' deleted successfully.', p_agent_id::UUID;
    ELSE
        RETURN QUERY SELECT 'DRY RUN'::TEXT, 0::BIGINT, 'Dry run complete. Set dry_run to FALSE to execute.', p_agent_id::UUID;
    END IF;

END $$ LANGUAGE plpgsql;