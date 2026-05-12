
--
-- PostgreSQL database dump
--


-- Dumped from database version 18.3
-- Dumped by pg_dump version 18.3

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

ALTER TABLE IF EXISTS ONLY public.unapproved_agent_ids DROP CONSTRAINT IF EXISTS unapproved_agent_ids_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.inferences DROP CONSTRAINT IF EXISTS inferences_evaluation_run_id_fkey;
ALTER TABLE IF EXISTS ONLY public.evaluations DROP CONSTRAINT IF EXISTS evaluations_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.evaluation_runs DROP CONSTRAINT IF EXISTS evaluation_runs_evaluation_id_fkey;
ALTER TABLE IF EXISTS ONLY public.evaluation_payments DROP CONSTRAINT IF EXISTS evaluation_payments_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.embeddings DROP CONSTRAINT IF EXISTS embeddings_evaluation_run_id_fkey;
ALTER TABLE IF EXISTS ONLY public.benchmark_agent_ids DROP CONSTRAINT IF EXISTS benchmark_agent_ids_agent_id_fkey;
ALTER TABLE IF EXISTS ONLY public.approved_agents DROP CONSTRAINT IF EXISTS approved_agents_agent_id_fkey;
DROP TRIGGER IF EXISTS tr_refresh_agent_scores_unapproved_agent_ids ON public.unapproved_agent_ids;
DROP TRIGGER IF EXISTS tr_refresh_agent_scores_delete_agents ON public.agents;
DROP TRIGGER IF EXISTS tr_refresh_agent_scores_banned_hotkeys ON public.banned_hotkeys;
DROP TRIGGER IF EXISTS tr_refresh_agent_scores_approved_agents ON public.approved_agents;
DROP TRIGGER IF EXISTS tr_refresh_agent_scores ON public.evaluations;

DROP INDEX IF EXISTS public.idx_unapproved_agent_ids_agent_id;
DROP INDEX IF EXISTS public.idx_miner_scores_uid;
DROP INDEX IF EXISTS public.idx_miner_scores_evaluation_set_id;
DROP INDEX IF EXISTS public.idx_miner_scores_created_at;
DROP INDEX IF EXISTS public.idx_inferences_created_provider_range;
DROP INDEX IF EXISTS public.idx_evaluations_validator_pattern;
DROP INDEX IF EXISTS public.idx_evaluations_id;
DROP INDEX IF EXISTS public.idx_evaluations_agent_id;
DROP INDEX IF EXISTS public.idx_evaluation_runs_evaluation_id;
DROP INDEX IF EXISTS public.idx_embedding_requests_timestamp;
DROP INDEX IF EXISTS public.idx_banned_hotkeys_miner_hotkey;
DROP INDEX IF EXISTS public.idx_agents_miner_hotkey_version;
DROP INDEX IF EXISTS public.idx_agent_scores_final_score;
DROP INDEX IF EXISTS public.idx_agent_scores_created_at;
DROP INDEX IF EXISTS public.idx_agent_scores_agent_id;
DROP INDEX IF EXISTS public.idx_agent_embeddings_vector;
DROP INDEX IF EXISTS public.idx_agent_embeddings_agent_id;
ALTER TABLE IF EXISTS ONLY public.validators DROP CONSTRAINT IF EXISTS validators_pkey;
ALTER TABLE IF EXISTS ONLY public.validator_weight_sets DROP CONSTRAINT IF EXISTS validator_weight_sets_pkey;
ALTER TABLE IF EXISTS ONLY public.upload_attempts DROP CONSTRAINT IF EXISTS upload_attempts_pkey;
ALTER TABLE IF EXISTS ONLY public.miner_scores DROP CONSTRAINT IF EXISTS unique_run_id;
ALTER TABLE IF EXISTS ONLY public.sessions DROP CONSTRAINT IF EXISTS sessions_pkey;
ALTER TABLE IF EXISTS ONLY public.miner_scores DROP CONSTRAINT IF EXISTS miner_scores_run_id_key;
ALTER TABLE IF EXISTS ONLY public.miner_scores DROP CONSTRAINT IF EXISTS miner_scores_pkey;
ALTER TABLE IF EXISTS ONLY public.inferences DROP CONSTRAINT IF EXISTS inferences_pkey;
ALTER TABLE IF EXISTS ONLY public.hotkey_gist DROP CONSTRAINT IF EXISTS hotkey_gist_pkey;
ALTER TABLE IF EXISTS ONLY public.evaluations DROP CONSTRAINT IF EXISTS evaluations_pkey;
ALTER TABLE IF EXISTS ONLY public.evaluation_sets DROP CONSTRAINT IF EXISTS evaluation_sets_pkey;
ALTER TABLE IF EXISTS ONLY public.evaluation_runs DROP CONSTRAINT IF EXISTS evaluation_runs_pkey;
ALTER TABLE IF EXISTS ONLY public.evaluation_run_logs DROP CONSTRAINT IF EXISTS evaluation_run_logs_pkey;
ALTER TABLE IF EXISTS ONLY public.evaluation_payments DROP CONSTRAINT IF EXISTS evaluation_payments_pkey;
ALTER TABLE IF EXISTS ONLY public.embeddings DROP CONSTRAINT IF EXISTS embeddings_pkey;
ALTER TABLE IF EXISTS ONLY public.embedding_requests DROP CONSTRAINT IF EXISTS embedding_requests_pkey;
ALTER TABLE IF EXISTS ONLY public.benchmark_agent_ids DROP CONSTRAINT IF EXISTS benchmark_agent_ids_pkey;
ALTER TABLE IF EXISTS ONLY public.approved_agents DROP CONSTRAINT IF EXISTS approved_agents_pkey;
ALTER TABLE IF EXISTS ONLY public.approved_agents DROP CONSTRAINT IF EXISTS approved_agents_agent_id_set_id_key;
ALTER TABLE IF EXISTS ONLY public.agents DROP CONSTRAINT IF EXISTS agents_pkey;
ALTER TABLE IF EXISTS ONLY public.agent_scores DROP CONSTRAINT IF EXISTS agent_scores_pkey;
ALTER TABLE IF EXISTS ONLY public.agent_embeddings DROP CONSTRAINT IF EXISTS agent_embeddings_pkey;
ALTER TABLE IF EXISTS ONLY public.agent_embeddings DROP CONSTRAINT IF EXISTS agent_embeddings_agent_id_key;
ALTER TABLE IF EXISTS public.validators ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS public.validator_weight_sets ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS public.sessions ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS public.miner_scores ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS public.hotkey_gist ALTER COLUMN id DROP DEFAULT;
DROP SEQUENCE IF EXISTS public.validators_id_seq;
DROP TABLE IF EXISTS public.validators;
DROP SEQUENCE IF EXISTS public.validator_weight_sets_id_seq;
DROP TABLE IF EXISTS public.validator_weight_sets;
DROP TABLE IF EXISTS public.upload_attempts;
DROP TABLE IF EXISTS public.system_enabled;
DROP SEQUENCE IF EXISTS public.sessions_id_seq;
DROP TABLE IF EXISTS public.sessions;
DROP TABLE IF EXISTS public.unapproved_agent_ids;
DROP SEQUENCE IF EXISTS public.miner_scores_id_seq;
DROP TABLE IF EXISTS public.miner_scores;
DROP TABLE IF EXISTS public.inferences;
DROP SEQUENCE IF EXISTS public.hotkey_gist_id_seq;
DROP TABLE IF EXISTS public.hotkey_gist;
DROP TABLE IF EXISTS public.evaluations;
DROP TABLE IF EXISTS public.evaluation_sets;
DROP TABLE IF EXISTS public.evaluation_runs;
DROP TABLE IF EXISTS public.evaluation_run_logs;
DROP TABLE IF EXISTS public.evaluation_payments;
DROP TABLE IF EXISTS public.embeddings;
DROP TABLE IF EXISTS public.embedding_requests;
DROP TABLE IF EXISTS public.benchmark_agent_ids;
DROP TABLE IF EXISTS public.banned_hotkeys;
DROP TABLE IF EXISTS public.approved_agents;
DROP TABLE IF EXISTS public.agents;
DROP TABLE IF EXISTS public.agent_scores;
DROP TABLE IF EXISTS public.agent_embeddings;

DROP VIEW IF EXISTS public.validator_queue;
DROP VIEW IF EXISTS public.screener_2_queue;
DROP VIEW IF EXISTS public.screener_1_queue;
DROP VIEW IF EXISTS public.evaluations_hydrated;
DROP VIEW IF EXISTS public.evaluation_runs_with_cost;
DROP VIEW IF EXISTS public.evaluation_runs_hydrated;

DROP FUNCTION IF EXISTS public.refresh_agent_scores_for_agent(target_agent_id uuid);
DROP FUNCTION IF EXISTS public.refresh_agent_scores();
DROP FUNCTION IF EXISTS public.populate_agent_scores();
DROP FUNCTION IF EXISTS public.delete_agent_report(p_agent_id uuid, dry_run boolean);
DROP TYPE IF EXISTS public.evaluationstatus;
DROP TYPE IF EXISTS public.evaluationsetgroup;
DROP TYPE IF EXISTS public.evaluationrunstatus;
DROP TYPE IF EXISTS public.evaluationrunlogtype;
DROP TYPE IF EXISTS public.agentstatus;


CREATE SCHEMA IF NOT EXISTS public;

--
-- Name: agentstatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agentstatus AS ENUM (
    'screening_1',
    'failed_screening_1',
    'screening_2',
    'failed_screening_2',
    'evaluating',
    'finished'
);


--
-- Name: evaluationrunlogtype; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.evaluationrunlogtype AS ENUM (
    'agent',
    'eval'
);


--
-- Name: evaluationrunstatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.evaluationrunstatus AS ENUM (
    'pending',
    'initializing_agent',
    'running_agent',
    'initializing_eval',
    'running_eval',
    'finished',
    'error'
);


--
-- Name: evaluationsetgroup; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.evaluationsetgroup AS ENUM (
    'screener_1',
    'screener_2',
    'validator'
);


--
-- Name: evaluationstatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.evaluationstatus AS ENUM (
    'running',
    'success',
    'failure'
);

--
-- Name: delete_agent_report(uuid, boolean); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.delete_agent_report(p_agent_id uuid, dry_run boolean DEFAULT true) RETURNS TABLE(table_name text, row_count bigint, mode text, target_id uuid)
    LANGUAGE plpgsql
    AS $$
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

    -- Count affected rows
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

    -- Return the report as a table (using target_id to avoid ambiguity with agent_id column)
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

END $$;


--
-- Name: populate_agent_scores(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.populate_agent_scores() RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    TRUNCATE TABLE agent_scores;
    INSERT INTO agent_scores (
        agent_id, miner_hotkey, name, version_num, created_at, status,
        set_id, approved, approved_at, validator_count, final_score
    )
    WITH all_agents AS (
        SELECT
            agent_id,
            miner_hotkey,
            name,
            version_num,
            created_at,
            status
        FROM agents
        WHERE miner_hotkey NOT IN (SELECT miner_hotkey FROM banned_hotkeys)
          AND agent_id NOT IN (SELECT agent_id FROM unapproved_agent_ids)
    ),
    agent_evaluations AS (
        SELECT
            aa.agent_id,
            aa.miner_hotkey,
            aa.name,
            aa.version_num,
            aa.created_at,
            aa.status,
            e.set_id,
            e.score,
            e.validator_hotkey,
            (avi.agent_id IS NOT NULL AND avi.approved_at <= NOW()) as approved,
            avi.approved_at
        FROM all_agents aa
        INNER JOIN evaluations_hydrated e ON aa.agent_id = e.agent_id
            AND e.status = 'success'
            AND e.score IS NOT NULL
            AND e.score > 0
            AND e.evaluation_set_group = 'validator'::EvaluationSetGroup
            AND e.set_id IS NOT NULL
        LEFT JOIN approved_agents avi ON aa.agent_id = avi.agent_id AND e.set_id = avi.set_id
    )
    SELECT
        ae.agent_id,
        ae.miner_hotkey,
        ae.name,
        ae.version_num,
        ae.created_at,
        ae.status,
        ae.set_id,
        ae.approved,
        ae.approved_at,
        COUNT(DISTINCT ae.validator_hotkey) AS validator_count,
        AVG(ae.score) AS final_score
    FROM agent_evaluations ae
    WHERE ae.set_id IS NOT NULL
    GROUP BY ae.agent_id, ae.miner_hotkey, ae.name, ae.version_num,
             ae.created_at, ae.status, ae.set_id, ae.approved, ae.approved_at
    -- At least 2 validators
    -- NOTE: THIS PARAMETER IS TIED TO NUM_EVALS_PER_AGENT in api/config.py
    HAVING COUNT(DISTINCT ae.validator_hotkey) >= 2;
END;
$$;


--
-- Name: refresh_agent_scores(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.refresh_agent_scores() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    affected_agent_id UUID;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF TG_TABLE_NAME = 'evaluations' THEN
            affected_agent_id := OLD.agent_id;
        ELSIF TG_TABLE_NAME = 'agents' THEN
            DELETE FROM agent_scores WHERE agent_id = OLD.agent_id;
            RETURN OLD;
        ELSIF TG_TABLE_NAME = 'approved_agents' THEN
            affected_agent_id := OLD.agent_id;
        ELSIF TG_TABLE_NAME = 'banned_hotkeys' THEN
            DELETE FROM agent_scores 
            WHERE agent_id IN (SELECT agent_id FROM agents WHERE miner_hotkey = OLD.miner_hotkey);
            RETURN OLD;
        ELSIF TG_TABLE_NAME = 'unapproved_agent_ids' THEN
            affected_agent_id := OLD.agent_id;
        END IF;
    ELSIF TG_OP = 'TRUNCATE' THEN
        PERFORM populate_agent_scores();
        RETURN NULL;
    ELSE
        IF TG_TABLE_NAME = 'evaluations' THEN
            affected_agent_id := NEW.agent_id;
        ELSIF TG_TABLE_NAME = 'agents' THEN
            affected_agent_id := NEW.agent_id;
        ELSIF TG_TABLE_NAME = 'approved_agents' THEN
            affected_agent_id := NEW.agent_id;
        ELSIF TG_TABLE_NAME = 'banned_hotkeys' THEN
            DELETE FROM agent_scores 
            WHERE agent_id IN (SELECT agent_id FROM agents WHERE miner_hotkey = NEW.miner_hotkey);
            RETURN NEW;
        ELSIF TG_TABLE_NAME = 'unapproved_agent_ids' THEN
            DELETE FROM agent_scores WHERE agent_id = NEW.agent_id;
            RETURN NEW;
        END IF;
    END IF;
    
    IF affected_agent_id IS NOT NULL THEN
        PERFORM refresh_agent_scores_for_agent(affected_agent_id);
    END IF;
    
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    ELSE
        RETURN NEW;
    END IF;
END;
$$;


--
-- Name: refresh_agent_scores_for_agent(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.refresh_agent_scores_for_agent(target_agent_id uuid) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    DELETE FROM agent_scores WHERE agent_id = target_agent_id;
    INSERT INTO agent_scores (
        agent_id, miner_hotkey, name, version_num, created_at, status,
        set_id, approved, approved_at, validator_count, final_score
    )
    WITH agent_evaluations AS (
        SELECT
            a.agent_id,
            a.miner_hotkey,
            a.name,
            a.version_num,
            a.created_at,
            a.status,
            e.set_id,
            e.score,
            e.validator_hotkey,
            e.evaluation_set_group,
            (avi.agent_id IS NOT NULL AND avi.approved_at <= NOW()) as approved,
            avi.approved_at
        FROM agents a
        INNER JOIN evaluations_hydrated e ON a.agent_id = e.agent_id
            AND e.status = 'success'
            AND e.score IS NOT NULL
            AND e.score > 0
            AND e.evaluation_set_group = 'validator'::EvaluationSetGroup
            AND e.set_id IS NOT NULL
        LEFT JOIN approved_agents avi ON a.agent_id = avi.agent_id AND e.set_id = avi.set_id
        WHERE a.agent_id = target_agent_id
          AND a.miner_hotkey NOT IN (SELECT miner_hotkey FROM banned_hotkeys)
          AND a.agent_id NOT IN (SELECT agent_id FROM unapproved_agent_ids)
    )
    SELECT
        ae.agent_id,
        ae.miner_hotkey,
        ae.name,
        ae.version_num,
        ae.created_at,
        ae.status,
        ae.set_id,
        ae.approved,
        ae.approved_at,
        COUNT(DISTINCT ae.validator_hotkey) AS validator_count,
        AVG(ae.score) AS final_score
    FROM agent_evaluations ae
    WHERE ae.set_id IS NOT NULL
    GROUP BY ae.agent_id, ae.miner_hotkey, ae.name, ae.version_num,
             ae.created_at, ae.status, ae.set_id, ae.approved, ae.approved_at
    -- At least 2 validators
    -- NOTE: THIS PARAMETER IS TIED TO NUM_EVALS_PER_AGENT in api/config.py
    HAVING COUNT(DISTINCT ae.validator_hotkey) >= 2;
END;
$$;


SET default_table_access_method = heap;

--
-- Name: agent_embeddings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_embeddings (
    embedding_id uuid DEFAULT gen_random_uuid() NOT NULL,
    agent_id uuid NOT NULL,
    agent_text text NOT NULL,
    embedding_provider text NOT NULL,
    embedding_model text NOT NULL,
    embedding_vector public.vector(768) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: agent_scores; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_scores (
    agent_id uuid NOT NULL,
    miner_hotkey text NOT NULL,
    name text NOT NULL,
    version_num integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    status public.agentstatus NOT NULL,
    set_id integer NOT NULL,
    approved boolean,
    approved_at timestamp with time zone,
    validator_count integer NOT NULL,
    final_score double precision NOT NULL
);


--
-- Name: agents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agents (
    agent_id uuid NOT NULL,
    miner_hotkey text NOT NULL,
    name text NOT NULL,
    version_num integer NOT NULL,
    status public.agentstatus,
    created_at timestamp with time zone NOT NULL,
    ip_address text NOT NULL,
    miner_uid text,
    provider text DEFAULT ''::text NOT NULL,
    model text DEFAULT ''::text NOT NULL,
    system_prompt_template text DEFAULT ''::text NOT NULL,
    user_prompt_template text DEFAULT ''::text NOT NULL,
    sampling_params jsonb DEFAULT '{}'::jsonb NOT NULL,
    fewshot_examples jsonb,
    eval_scores jsonb DEFAULT '{}'::jsonb NOT NULL
);


--
-- Name: approved_agents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approved_agents (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    agent_id uuid,
    set_id integer NOT NULL,
    approved_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: banned_hotkeys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.banned_hotkeys (
    miner_hotkey text NOT NULL,
    banned_reason text,
    banned_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: benchmark_agent_ids; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.benchmark_agent_ids (
    agent_id uuid NOT NULL,
    description text NOT NULL
);


--
-- Name: embedding_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.embedding_requests (
    request_id uuid DEFAULT gen_random_uuid() NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    input_text text NOT NULL,
    dimensions integer DEFAULT 768 NOT NULL,
    status_code integer,
    num_tokens integer,
    cost_usd double precision,
    request_received_at timestamp with time zone DEFAULT now() NOT NULL,
    response_sent_at timestamp with time zone
);


--
-- Name: embeddings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.embeddings (
    embedding_id uuid NOT NULL,
    evaluation_run_id uuid NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    input text NOT NULL,
    status_code integer,
    response jsonb,
    num_input_tokens integer,
    cost_usd double precision,
    request_received_at timestamp with time zone NOT NULL,
    response_sent_at timestamp with time zone
);


--
-- Name: evaluation_payments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.evaluation_payments (
    payment_block_hash text NOT NULL,
    payment_extrinsic_index text NOT NULL,
    agent_id uuid NOT NULL,
    miner_hotkey text NOT NULL,
    miner_coldkey text NOT NULL,
    amount_rao bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: evaluation_run_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.evaluation_run_logs (
    evaluation_run_id uuid NOT NULL,
    logs text,
    type public.evaluationrunlogtype NOT NULL
);


--
-- Name: evaluation_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.evaluation_runs (
    evaluation_run_id uuid NOT NULL,
    evaluation_id uuid NOT NULL,
    problem_name text NOT NULL,
    status public.evaluationrunstatus,
    patch text,
    test_results jsonb,
    error_code integer,
    error_message text,
    created_at timestamp with time zone NOT NULL,
    started_initializing_agent_at timestamp with time zone,
    started_running_agent_at timestamp with time zone,
    started_initializing_eval_at timestamp with time zone,
    started_running_eval_at timestamp with time zone,
    finished_or_errored_at timestamp with time zone
);



--
-- Name: evaluation_sets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.evaluation_sets (
    set_id integer NOT NULL,
    set_group public.evaluationsetgroup NOT NULL,
    problem_name text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: evaluations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.evaluations (
    evaluation_id uuid NOT NULL,
    agent_id uuid NOT NULL,
    validator_hotkey text NOT NULL,
    set_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    evaluation_set_group public.evaluationsetgroup NOT NULL
);




--
-- Name: hotkey_gist; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.hotkey_gist (
    id integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    miner_hotkey character varying(255) NOT NULL,
    gist character varying(255) NOT NULL,
    block integer DEFAULT 0 NOT NULL,
    uid integer DEFAULT 0 NOT NULL,
    artifact_id uuid,
    github_account character varying(255)
);


--
-- Name: hotkey_gist_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.hotkey_gist_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: hotkey_gist_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.hotkey_gist_id_seq OWNED BY public.hotkey_gist.id;


--
-- Name: inferences; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.inferences (
    inference_id uuid DEFAULT gen_random_uuid() NOT NULL,
    evaluation_run_id uuid NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    temperature double precision NOT NULL,
    messages jsonb NOT NULL,
    status_code integer,
    response text,
    num_input_tokens integer,
    num_output_tokens integer,
    cost_usd double precision,
    request_received_at timestamp with time zone DEFAULT now(),
    response_sent_at timestamp with time zone DEFAULT now(),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: miner_scores; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.miner_scores (
    id integer NOT NULL,
    run_id uuid NOT NULL,
    uid integer NOT NULL,
    hotkey text NOT NULL,
    task_name text,
    score real NOT NULL,
    success boolean,
    duration real,
    created_at timestamp with time zone,
    evaluation_set_id integer,
    sample_size integer,
    validator_hotkey text
);


--
-- Name: miner_scores_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.miner_scores_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: miner_scores_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.miner_scores_id_seq OWNED BY public.miner_scores.id;


--
-- Name: unapproved_agent_ids; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.unapproved_agent_ids (
    agent_id uuid NOT NULL,
    unapproved_reason text,
    unapproved_at timestamp with time zone DEFAULT now() NOT NULL
);



--
-- Name: sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sessions (
    session_id text NOT NULL,
    node_name text NOT NULL,
    node_hotkey text,
    ip_address text,
    created_at timestamp with time zone DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'::text) NOT NULL,
    id bigint NOT NULL
);


--
-- Name: sessions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sessions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sessions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sessions_id_seq OWNED BY public.sessions.id;


--
-- Name: system_enabled; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_enabled (
    enabled integer NOT NULL
);


--
-- Name: upload_attempts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.upload_attempts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    upload_type text NOT NULL,
    hotkey text,
    agent_name text,
    filename text,
    file_size_bytes bigint,
    ip_address text,
    success boolean NOT NULL,
    error_type text,
    error_message text,
    ban_reason text,
    http_status_code integer,
    agent_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);



--
-- Name: validator_weight_sets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.validator_weight_sets (
    id integer NOT NULL,
    netuid integer NOT NULL,
    block integer NOT NULL,
    validator_hotkey text NOT NULL,
    wta_uid integer NOT NULL,
    wta_hotkey text NOT NULL,
    wta_weight real NOT NULL,
    weights text NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    evaluation_set_id integer NOT NULL
);


--
-- Name: validator_weight_sets_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.validator_weight_sets_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: validator_weight_sets_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.validator_weight_sets_id_seq OWNED BY public.validator_weight_sets.id;


--
-- Name: validators; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.validators (
    id integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    name character varying(255) NOT NULL,
    hotkey character varying(255) NOT NULL,
    ip character varying(255),
    auth_token character varying(255) NOT NULL,
    enabled boolean DEFAULT false NOT NULL
);


--
-- Name: validators_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.validators_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: validators_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.validators_id_seq OWNED BY public.validators.id;


--
-- Name: hotkey_gist id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hotkey_gist ALTER COLUMN id SET DEFAULT nextval('public.hotkey_gist_id_seq'::regclass);


--
-- Name: miner_scores id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.miner_scores ALTER COLUMN id SET DEFAULT nextval('public.miner_scores_id_seq'::regclass);


--
-- Name: sessions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions ALTER COLUMN id SET DEFAULT nextval('public.sessions_id_seq'::regclass);


--
-- Name: validator_weight_sets id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.validator_weight_sets ALTER COLUMN id SET DEFAULT nextval('public.validator_weight_sets_id_seq'::regclass);


--
-- Name: validators id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.validators ALTER COLUMN id SET DEFAULT nextval('public.validators_id_seq'::regclass);


--
-- Name: agent_embeddings agent_embeddings_agent_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_embeddings
    ADD CONSTRAINT agent_embeddings_agent_id_key UNIQUE (agent_id);


--
-- Name: agent_embeddings agent_embeddings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_embeddings
    ADD CONSTRAINT agent_embeddings_pkey PRIMARY KEY (embedding_id);


--
-- Name: agent_scores agent_scores_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_scores
    ADD CONSTRAINT agent_scores_pkey PRIMARY KEY (agent_id);


--
-- Name: agents agents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_pkey PRIMARY KEY (agent_id);


--
-- Name: approved_agents approved_agents_agent_id_set_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approved_agents
    ADD CONSTRAINT approved_agents_agent_id_set_id_key UNIQUE (agent_id, set_id);


--
-- Name: approved_agents approved_agents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approved_agents
    ADD CONSTRAINT approved_agents_pkey PRIMARY KEY (id);


--
-- Name: benchmark_agent_ids benchmark_agent_ids_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.benchmark_agent_ids
    ADD CONSTRAINT benchmark_agent_ids_pkey PRIMARY KEY (agent_id);


--
-- Name: embedding_requests embedding_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.embedding_requests
    ADD CONSTRAINT embedding_requests_pkey PRIMARY KEY (request_id);


--
-- Name: embeddings embeddings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.embeddings
    ADD CONSTRAINT embeddings_pkey PRIMARY KEY (embedding_id);


--
-- Name: evaluation_payments evaluation_payments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evaluation_payments
    ADD CONSTRAINT evaluation_payments_pkey PRIMARY KEY (payment_block_hash, payment_extrinsic_index);


--
-- Name: evaluation_run_logs evaluation_run_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evaluation_run_logs
    ADD CONSTRAINT evaluation_run_logs_pkey PRIMARY KEY (evaluation_run_id, type);


--
-- Name: evaluation_runs evaluation_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evaluation_runs
    ADD CONSTRAINT evaluation_runs_pkey PRIMARY KEY (evaluation_run_id);


--
-- Name: evaluation_sets evaluation_sets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evaluation_sets
    ADD CONSTRAINT evaluation_sets_pkey PRIMARY KEY (set_id, set_group, problem_name);


--
-- Name: evaluations evaluations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evaluations
    ADD CONSTRAINT evaluations_pkey PRIMARY KEY (evaluation_id);


--
-- Name: hotkey_gist hotkey_gist_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.hotkey_gist
    ADD CONSTRAINT hotkey_gist_pkey PRIMARY KEY (id);


--
-- Name: inferences inferences_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inferences
    ADD CONSTRAINT inferences_pkey PRIMARY KEY (inference_id);


--
-- Name: miner_scores miner_scores_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.miner_scores
    ADD CONSTRAINT miner_scores_pkey PRIMARY KEY (id);


--
-- Name: miner_scores miner_scores_run_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.miner_scores
    ADD CONSTRAINT miner_scores_run_id_key UNIQUE (run_id);


--
-- Name: sessions sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_pkey PRIMARY KEY (id);


--
-- Name: miner_scores unique_run_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.miner_scores
    ADD CONSTRAINT unique_run_id UNIQUE (run_id);


--
-- Name: upload_attempts upload_attempts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.upload_attempts
    ADD CONSTRAINT upload_attempts_pkey PRIMARY KEY (id);


--
-- Name: validator_weight_sets validator_weight_sets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.validator_weight_sets
    ADD CONSTRAINT validator_weight_sets_pkey PRIMARY KEY (id);


--
-- Name: validators validators_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.validators
    ADD CONSTRAINT validators_pkey PRIMARY KEY (id);


--
-- Name: idx_agent_embeddings_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_embeddings_agent_id ON public.agent_embeddings USING btree (agent_id);


--
-- Name: idx_agent_embeddings_vector; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_embeddings_vector ON public.agent_embeddings USING ivfflat (embedding_vector public.vector_cosine_ops) WITH (lists='100');


--
-- Name: idx_agent_scores_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_agent_scores_agent_id ON public.agent_scores USING btree (agent_id);


--
-- Name: idx_agent_scores_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_scores_created_at ON public.agent_scores USING btree (created_at);


--
-- Name: idx_agent_scores_final_score; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_scores_final_score ON public.agent_scores USING btree (final_score);


--
-- Name: idx_agents_miner_hotkey_version; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agents_miner_hotkey_version ON public.agents USING btree (miner_hotkey, agent_id);


--
-- Name: idx_banned_hotkeys_miner_hotkey; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_banned_hotkeys_miner_hotkey ON public.banned_hotkeys USING btree (miner_hotkey);


--
-- Name: idx_embedding_requests_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_embedding_requests_timestamp ON public.embedding_requests USING btree (request_received_at);


--
-- Name: idx_evaluation_runs_evaluation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_evaluation_runs_evaluation_id ON public.evaluation_runs USING btree (evaluation_id);


--
-- Name: idx_evaluations_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_evaluations_agent_id ON public.evaluations USING btree (agent_id);


--
-- Name: idx_evaluations_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_evaluations_id ON public.evaluations USING btree (evaluation_id);


--
-- Name: idx_evaluations_validator_pattern; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_evaluations_validator_pattern ON public.evaluations USING btree (validator_hotkey text_pattern_ops);


--
-- Name: idx_inferences_created_provider_range; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_inferences_created_provider_range ON public.inferences USING btree (request_received_at, provider) INCLUDE (response_sent_at, status_code, num_input_tokens, num_output_tokens, cost_usd) WHERE ((response_sent_at IS NOT NULL) AND (provider IS NOT NULL));


--
-- Name: idx_miner_scores_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_miner_scores_created_at ON public.miner_scores USING btree (created_at);


--
-- Name: idx_miner_scores_evaluation_set_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_miner_scores_evaluation_set_id ON public.miner_scores USING btree (evaluation_set_id);


--
-- Name: idx_miner_scores_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_miner_scores_uid ON public.miner_scores USING btree (uid);


--
-- Name: idx_unapproved_agent_ids_agent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_unapproved_agent_ids_agent_id ON public.unapproved_agent_ids USING btree (agent_id);





--
-- Name: evaluation_runs_hydrated; Type: VIEW; Schema: public; Owner: -
--

CREATE OR REPLACE VIEW public.evaluation_runs_hydrated AS
 SELECT evaluation_run_id,
    evaluation_id,
    problem_name,
    status,
    patch,
    test_results,
    error_code,
    error_message,
    created_at,
    started_initializing_agent_at,
    started_running_agent_at,
    started_initializing_eval_at,
    started_running_eval_at,
    finished_or_errored_at,
        CASE
            WHEN (test_results IS NULL) THEN NULL::boolean
            WHEN (jsonb_array_length(test_results) = 0) THEN NULL::boolean
            WHEN (( SELECT count(*) FILTER (WHERE ((test.value ->> 'status'::text) = 'pass'::text)) AS count
               FROM jsonb_array_elements(evaluation_runs.test_results) test(value)) = jsonb_array_length(test_results)) THEN true
            ELSE false
        END AS solved
   FROM public.evaluation_runs;


CREATE OR REPLACE VIEW public.evaluations_hydrated AS
 SELECT evaluations.evaluation_id,
    evaluations.agent_id,
    evaluations.validator_hotkey,
    evaluations.set_id,
    evaluations.created_at,
    evaluations.finished_at,
    evaluations.evaluation_set_group,
    (
        CASE
            WHEN every(((erh.status = 'finished'::public.evaluationrunstatus) OR ((erh.status = 'error'::public.evaluationrunstatus) AND ((erh.error_code >= 1000) AND (erh.error_code <= 2999))))) THEN 'success'::text
            WHEN every((erh.status = ANY (ARRAY['finished'::public.evaluationrunstatus, 'error'::public.evaluationrunstatus]))) THEN 'failure'::text
            ELSE 'running'::text
        END)::public.evaluationstatus AS status,
    ((count(*) FILTER (WHERE erh.solved))::double precision / (count(*))::double precision) AS score
   FROM (public.evaluations
     JOIN public.evaluation_runs_hydrated erh USING (evaluation_id))
  GROUP BY evaluations.evaluation_id;


--
-- Name: screener_1_queue; Type: VIEW; Schema: public; Owner: -
--

CREATE OR REPLACE VIEW public.screener_1_queue AS
 SELECT agent_id,
    status
   FROM public.agents
  WHERE ((status = 'screening_1'::public.agentstatus) AND (NOT (EXISTS ( SELECT 1
           FROM public.evaluations_hydrated
          WHERE ((evaluations_hydrated.agent_id = agents.agent_id) AND (evaluations_hydrated.status = ANY (ARRAY['success'::public.evaluationstatus, 'running'::public.evaluationstatus])) AND (evaluations_hydrated.evaluation_set_group = 'screener_1'::public.evaluationsetgroup))))) AND (NOT (agent_id IN ( SELECT benchmark_agent_ids.agent_id
           FROM public.benchmark_agent_ids))) AND (NOT (miner_hotkey IN ( SELECT banned_hotkeys.miner_hotkey
           FROM public.banned_hotkeys))) AND (NOT (agent_id IN ( SELECT unapproved_agent_ids.agent_id
           FROM public.unapproved_agent_ids))))
  ORDER BY created_at;


--
-- Name: screener_2_queue; Type: VIEW; Schema: public; Owner: -
--

CREATE OR REPLACE VIEW public.screener_2_queue AS
 SELECT agent_id,
    status
   FROM public.agents
  WHERE ((status = 'screening_2'::public.agentstatus) AND (NOT (EXISTS ( SELECT 1
           FROM public.evaluations_hydrated
          WHERE ((evaluations_hydrated.agent_id = agents.agent_id) AND (evaluations_hydrated.status = ANY (ARRAY['success'::public.evaluationstatus, 'running'::public.evaluationstatus])) AND (evaluations_hydrated.evaluation_set_group = 'screener_2'::public.evaluationsetgroup))))) AND (NOT (agent_id IN ( SELECT benchmark_agent_ids.agent_id
           FROM public.benchmark_agent_ids))) AND (NOT (miner_hotkey IN ( SELECT banned_hotkeys.miner_hotkey
           FROM public.banned_hotkeys))) AND (NOT (agent_id IN ( SELECT unapproved_agent_ids.agent_id
           FROM public.unapproved_agent_ids))))
  ORDER BY created_at;



--
-- Name: evaluation_runs_with_cost _RETURN; Type: RULE; Schema: public; Owner: -
--

CREATE OR REPLACE VIEW public.evaluation_runs_with_cost AS
 SELECT er.evaluation_run_id,
    er.evaluation_id,
    er.problem_name,
    er.status,
    er.patch,
    er.test_results,
    er.error_code,
    er.error_message,
    er.created_at,
    er.started_initializing_agent_at,
    er.started_running_agent_at,
    er.started_initializing_eval_at,
    er.started_running_eval_at,
    er.finished_or_errored_at,
    COALESCE(sum(i.cost_usd), (0)::double precision) AS total_cost_usd,
    COALESCE(sum(i.num_input_tokens), (0)::bigint) AS total_input_tokens,
    COALESCE(sum(i.num_output_tokens), (0)::bigint) AS total_output_tokens,
    count(*) AS num_inferences
   FROM (public.evaluation_runs er
     LEFT JOIN public.inferences i ON ((er.evaluation_run_id = i.evaluation_run_id)))
  GROUP BY er.evaluation_run_id;



--
-- Name: validator_queue; Type: VIEW; Schema: public; Owner: -
--

CREATE OR REPLACE VIEW public.validator_queue AS
 WITH validator_eval_counts AS (
         SELECT evaluations_hydrated.agent_id,
            count(*) FILTER (WHERE (evaluations_hydrated.status = 'running'::public.evaluationstatus)) AS num_running_evals,
            count(*) FILTER (WHERE (evaluations_hydrated.status = 'success'::public.evaluationstatus)) AS num_finished_evals
           FROM public.evaluations_hydrated
          WHERE ((evaluations_hydrated.status = ANY (ARRAY['success'::public.evaluationstatus, 'running'::public.evaluationstatus])) AND (evaluations_hydrated.evaluation_set_group = 'validator'::public.evaluationsetgroup))
          GROUP BY evaluations_hydrated.agent_id
        ), validator_total_eval_counts AS (
         SELECT evaluations.agent_id,
            count(*) AS num_total_evals
           FROM public.evaluations
          WHERE (evaluations.evaluation_set_group = 'validator'::public.evaluationsetgroup)
          GROUP BY evaluations.agent_id
        ), screener_2_scores AS (
         SELECT evaluations_hydrated.agent_id,
            max(evaluations_hydrated.score) AS score
           FROM public.evaluations_hydrated
          WHERE ((evaluations_hydrated.evaluation_set_group = 'screener_2'::public.evaluationsetgroup) AND (evaluations_hydrated.status = 'success'::public.evaluationstatus))
          GROUP BY evaluations_hydrated.agent_id
        )
 SELECT agents.agent_id,
    agents.status,
    COALESCE(validator_eval_counts.num_running_evals, (0)::bigint) AS num_running_evals,
    COALESCE(validator_eval_counts.num_finished_evals, (0)::bigint) AS num_finished_evals
   FROM (((public.agents
     JOIN screener_2_scores USING (agent_id))
     LEFT JOIN validator_eval_counts USING (agent_id))
     LEFT JOIN validator_total_eval_counts USING (agent_id))
  WHERE ((agents.status = 'evaluating'::public.agentstatus) AND ((COALESCE(validator_eval_counts.num_running_evals, (0)::bigint) + COALESCE(validator_eval_counts.num_finished_evals, (0)::bigint)) < 3) AND (COALESCE(validator_total_eval_counts.num_total_evals, (0)::bigint) < 9) AND (NOT (agents.agent_id IN ( SELECT benchmark_agent_ids.agent_id
           FROM public.benchmark_agent_ids))) AND (NOT (agents.miner_hotkey IN ( SELECT banned_hotkeys.miner_hotkey
           FROM public.banned_hotkeys))) AND (NOT (agents.agent_id IN ( SELECT unapproved_agent_ids.agent_id
           FROM public.unapproved_agent_ids))))
  ORDER BY screener_2_scores.score DESC, agents.created_at, COALESCE(validator_eval_counts.num_finished_evals, (0)::bigint) DESC;


--
-- Name: evaluations tr_refresh_agent_scores; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER tr_refresh_agent_scores AFTER INSERT OR DELETE OR UPDATE ON public.evaluations FOR EACH ROW EXECUTE FUNCTION public.refresh_agent_scores();


--
-- Name: approved_agents tr_refresh_agent_scores_approved_agents; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER tr_refresh_agent_scores_approved_agents AFTER INSERT OR DELETE OR UPDATE ON public.approved_agents FOR EACH ROW EXECUTE FUNCTION public.refresh_agent_scores();


--
-- Name: banned_hotkeys tr_refresh_agent_scores_banned_hotkeys; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER tr_refresh_agent_scores_banned_hotkeys AFTER INSERT OR DELETE OR UPDATE ON public.banned_hotkeys FOR EACH ROW EXECUTE FUNCTION public.refresh_agent_scores();


--
-- Name: agents tr_refresh_agent_scores_delete_agents; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER tr_refresh_agent_scores_delete_agents AFTER INSERT OR DELETE OR UPDATE ON public.agents FOR EACH ROW EXECUTE FUNCTION public.refresh_agent_scores();


--
-- Name: unapproved_agent_ids tr_refresh_agent_scores_unapproved_agent_ids; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER tr_refresh_agent_scores_unapproved_agent_ids AFTER INSERT OR DELETE OR UPDATE ON public.unapproved_agent_ids FOR EACH ROW EXECUTE FUNCTION public.refresh_agent_scores();


--
-- Name: approved_agents approved_agents_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approved_agents
    ADD CONSTRAINT approved_agents_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(agent_id);


--
-- Name: benchmark_agent_ids benchmark_agent_ids_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.benchmark_agent_ids
    ADD CONSTRAINT benchmark_agent_ids_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(agent_id);


--
-- Name: embeddings embeddings_evaluation_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.embeddings
    ADD CONSTRAINT embeddings_evaluation_run_id_fkey FOREIGN KEY (evaluation_run_id) REFERENCES public.evaluation_runs(evaluation_run_id);


--
-- Name: evaluation_payments evaluation_payments_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evaluation_payments
    ADD CONSTRAINT evaluation_payments_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(agent_id);


--
-- Name: evaluation_runs evaluation_runs_evaluation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evaluation_runs
    ADD CONSTRAINT evaluation_runs_evaluation_id_fkey FOREIGN KEY (evaluation_id) REFERENCES public.evaluations(evaluation_id);


--
-- Name: evaluations evaluations_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evaluations
    ADD CONSTRAINT evaluations_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(agent_id);


--
-- Name: inferences inferences_evaluation_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.inferences
    ADD CONSTRAINT inferences_evaluation_run_id_fkey FOREIGN KEY (evaluation_run_id) REFERENCES public.evaluation_runs(evaluation_run_id);


--
-- Name: unapproved_agent_ids unapproved_agent_ids_agent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.unapproved_agent_ids
    ADD CONSTRAINT unapproved_agent_ids_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(agent_id);


--
-- PostgreSQL database dump complete
--








