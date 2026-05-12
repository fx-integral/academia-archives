import json
import utils.logger as logger
import api.config as config
from uuid import UUID
from datetime import datetime
from typing import List, Optional
from models.evaluation import EvaluationStatus
from models.evaluation_set import EvaluationSetGroup
from utils.database import db_operation, DatabaseConnection
from models.agent import Agent, AgentStatus, AgentScored, BenchmarkAgentScored, PossiblyBenchmarkAgent


@db_operation
async def get_agent_count(conn: DatabaseConnection) -> int:
    result = await conn.fetchval(
        """
        SELECT COUNT(*) FROM agents
        """
    )
    return result


@db_operation
async def get_agents_by_top_limit(conn: DatabaseConnection, top: int=100) -> Optional[List[Agent]]:
    results = await conn.fetch(
        """
        SELECT * FROM agents
        ORDER BY created_at DESC
        LIMIT $1
        """,
        top
    )
    return [Agent.parse_agent_from_db_row(row) for row in results]   


@db_operation
async def get_agent_by_id(conn: DatabaseConnection, agent_id: UUID) -> Optional[Agent]:
    result = await conn.fetchrow(
        """
        SELECT *
        FROM agents 
        WHERE agent_id = $1
        LIMIT 1
        """,
        agent_id
    )

    if result is None:
        return None

    return Agent.parse_agent_from_db_row(result)

@db_operation
async def get_possibly_benchmark_agent_by_id(conn: DatabaseConnection, agent_id: UUID) -> Optional[PossiblyBenchmarkAgent]:
    result = await conn.fetchrow(
        """
        SELECT
            a.*,
            (bai.agent_id IS NOT NULL) AS is_benchmark_agent,
            bai.description AS benchmark_description
        FROM agents a
        LEFT JOIN benchmark_agent_ids bai ON a.agent_id = bai.agent_id
        WHERE a.agent_id = $1
        LIMIT 1
        """,
        agent_id
    )
    
    if result is None:
        return None
    
    agent = Agent.parse_agent_from_db_row(result)
    return PossiblyBenchmarkAgent(
        **agent.model_dump(),  # Includes all parsed Agent fields
        is_benchmark_agent=result['is_benchmark_agent'],
        benchmark_description=result['benchmark_description']
    )


@db_operation
async def get_agent_by_evaluation_run_id(conn: DatabaseConnection, evaluation_run_id: UUID) -> Optional[Agent]:
    result = await conn.fetchrow(
        """
        SELECT * FROM agents
        WHERE agent_id = (
            SELECT agent_id FROM evaluations WHERE evaluation_id = (
                SELECT evaluation_id FROM evaluation_runs WHERE evaluation_run_id = $1 LIMIT 1
            ) LIMIT 1
        )
        """,
        evaluation_run_id
    )
    
    if result is None:
        return None  
    
    return Agent.parse_agent_from_db_row(result)


@db_operation
async def get_all_agents_by_miner_hotkey(conn: DatabaseConnection, miner_hotkey: str) -> List[Agent]:
    result = await conn.fetch(
        """
        SELECT * FROM agents 
        WHERE miner_hotkey = $1
        ORDER BY created_at DESC
        """,
        miner_hotkey
    )
    
    return [Agent.parse_agent_from_db_row(row) for row in result]



@db_operation
async def get_latest_agent_for_miner_hotkey(conn: DatabaseConnection, miner_hotkey: str) -> Optional[Agent]:
    result = await conn.fetchrow(
        """
        SELECT * FROM agents 
        WHERE miner_hotkey = $1
        ORDER BY created_at DESC
        LIMIT 1
        """,
        miner_hotkey
    )

    if result is None:
        return None 
    
    return Agent.parse_agent_from_db_row(result)



@db_operation
async def get_latest_agent_created_at_for_miner_hotkey_in_latest_set_id(conn: DatabaseConnection, miner_hotkey: str) -> Optional[datetime]:
    result = await conn.fetchval(
        """
        SELECT MAX(a.created_at)
        FROM agents a
        WHERE a.miner_hotkey = $1
        AND a.created_at > (SELECT MAX(created_at) FROM evaluation_sets)
        """,
        miner_hotkey
    )
    
    return result



@db_operation
async def create_agent(conn: DatabaseConnection, agent: Agent) -> UUID:
    result = await conn.fetchval(
        """
        INSERT INTO agents (
            agent_id, miner_hotkey, name, version_num, status, created_at, ip_address,
            miner_uid, provider, model, system_prompt_template, user_prompt_template,
            sampling_params, fewshot_examples, eval_scores
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
        RETURNING agent_id
        """,
        agent.agent_id,
        agent.miner_hotkey,
        agent.name,
        agent.version_num,
        agent.status.value,
        agent.created_at,
        agent.ip_address,
        agent.miner_uid,
        agent.provider,
        agent.model,
        agent.system_prompt_template,
        agent.user_prompt_template,
        json.dumps(agent.sampling_params.model_dump()),
        json.dumps([ex.model_dump() for ex in agent.fewshot_examples]) if agent.fewshot_examples else None,
        json.dumps(agent.eval_scores)
    )
    return result


@db_operation
async def update_agent_status(conn: DatabaseConnection, agent_id: UUID, status: AgentStatus) -> None:
    await conn.execute(
        """
        UPDATE agents
        SET status = $2
        WHERE agent_id = $1
        """,
        agent_id,
        status.value
    )

    if status == AgentStatus.failed_screening_1:
        # delete vector embeddings associated with this agent
        await conn.execute(
            """
            DELETE FROM agent_embeddings
            WHERE agent_id = $1
            """,
            agent_id
        )
        logger.info(f"Deleted vector embeddings for agent {agent_id} due to failed_screening_1.")        



@db_operation
async def get_benchmark_agents(conn: DatabaseConnection) -> List[BenchmarkAgentScored]:
    result = await conn.fetch(
        """
        SELECT
            a.*,
            ass.final_score,
            ass.created_at as score_created_at,
            ass.set_id,
            ass.approved,
            ass.validator_count,
            bai.description AS benchmark_description
        FROM agents a
        JOIN agent_scores ass ON a.agent_id = ass.agent_id
        LEFT JOIN benchmark_agent_ids bai ON a.agent_id = bai.agent_id
        WHERE a.agent_id IN (SELECT agent_id FROM benchmark_agent_ids)
        ORDER BY ass.created_at DESC, ass.final_score DESC
        """
    )

    agents = []
    for row in result:
        row = dict(row)
        row['sampling_params'] = json.loads(row['sampling_params']) if row['sampling_params'] else {}
        row['fewshot_examples'] = json.loads(row['fewshot_examples']) if row['fewshot_examples'] else []
        row['eval_scores'] = json.loads(row['eval_scores']) if row['eval_scores'] else {}
        agents.append(BenchmarkAgentScored(**row))
    return agents



@db_operation
async def record_upload_attempt(conn: DatabaseConnection, upload_type: str, success: bool, **kwargs) -> None:
    """Record an upload attempt in the upload_attempts table."""
    try:
        await conn.execute(
            """INSERT INTO upload_attempts (upload_type, success, hotkey, agent_name, filename,
                                            file_size_bytes, ip_address, error_type, error_message, ban_reason, http_status_code, agent_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)""",
            upload_type, success, kwargs.get('hotkey'), kwargs.get('agent_name'), kwargs.get('filename'),
            kwargs.get('file_size_bytes'), kwargs.get('ip_address'), kwargs.get('error_type'),
            kwargs.get('error_message'), kwargs.get('ban_reason'), kwargs.get('http_status_code'), kwargs.get('agent_id')
        )
        logger.debug(f"Recorded upload attempt: type={upload_type}, success={success}, error_type={kwargs.get('error_type')}")
    except Exception as e:
        logger.error(f"Failed to record upload attempt: {e}")




@db_operation
async def get_top_agents(
    conn: DatabaseConnection, 
    number_of_agents: int = 10,
    page: int = 1
) -> list[AgentScored]:
    offset = (page - 1) * number_of_agents

    results = await conn.fetch(
        """
        SELECT a.*, ass.final_score, ass.created_at as score_created_at, ass.set_id, ass.approved, ass.validator_count
        FROM agents a
        JOIN agent_scores ass ON a.agent_id = ass.agent_id
        WHERE ass.set_id = (SELECT MAX(set_id) FROM evaluation_sets)
        AND a.agent_id NOT IN (SELECT agent_id FROM benchmark_agent_ids)
        ORDER BY ROUND(ass.final_score::numeric, 8) DESC, a.created_at ASC
        LIMIT $1 OFFSET $2
        """, number_of_agents, offset
    )

    agents = []
    for result in results:
        result = dict(result)
        result['sampling_params'] = json.loads(result['sampling_params']) if result['sampling_params'] else {}
        result['fewshot_examples'] = json.loads(result['fewshot_examples']) if result['fewshot_examples'] else []
        result['eval_scores'] = json.loads(result['eval_scores']) if result['eval_scores'] else {}
        agents.append(AgentScored(**result))
    return agents


@db_operation
async def get_current_agents(conn: DatabaseConnection) -> list[Agent]:
    results = await conn.fetch("""
        SELECT *, '' AS system_prompt_template, '' as user_prompt_template 
        FROM AGENTS WHERE created_at >= (
        SELECT MIN(created_at) FROM evaluation_sets
        WHERE set_id = (SELECT MAX(set_id) FROM evaluation_sets))
        ORDER BY created_at DESC;
    """)
    return [Agent.parse_agent_from_db_row(row) for row in results]


@db_operation
async def get_agents_in_queue(conn: DatabaseConnection, queue_stage: EvaluationSetGroup) -> list[Agent]:
    queue_to_query = f"{queue_stage.value}_queue"

    if queue_stage == EvaluationSetGroup.screener_1:
        queue = await conn.fetch(f"""
            SELECT a.*
            from agents a
            join {queue_to_query} q on q.agent_id = a.agent_id
            order by a.created_at asc
        """)
        return [Agent.parse_agent_from_db_row(agent) for agent in queue]
    elif queue_stage == EvaluationSetGroup.screener_2:
        queue = await conn.fetch(f"""
            SELECT a.*
            from agents a
            join {queue_to_query} q on q.agent_id = a.agent_id
            order by a.created_at asc
        """)
        return [Agent.parse_agent_from_db_row(agent) for agent in queue]
    else:
        queue = await conn.fetch(f"""
            SELECT a.*
            from agents a
            join {queue_to_query} q on q.agent_id = a.agent_id
        """)
        return [Agent.parse_agent_from_db_row(agent) for agent in queue]

      

@db_operation
async def get_next_agent_id_awaiting_evaluation_for_validator_hotkey(conn: DatabaseConnection, validator_hotkey: str) -> Optional[UUID]:
    if validator_hotkey.startswith("screener-1"):
        result = await conn.fetchrow("""
            SELECT agent_id FROM screener_1_queue LIMIT 1
        """)
    elif validator_hotkey.startswith("screener-2"):
        result = await conn.fetchrow("""
             SELECT agent_id FROM screener_2_queue LIMIT 1
        """)
    else:
        result = await conn.fetchrow(
            f"""
            WITH
                validator_eval_counts AS (
                    SELECT
                        agent_id,
                        BOOL_OR(validator_hotkey = $1) AS already_evaluated,
                        COUNT(*) FILTER (WHERE status = '{EvaluationStatus.running.value}') AS num_running_evals,
                        COUNT(*) FILTER (WHERE status = '{EvaluationStatus.success.value}') AS num_finished_evals
                    FROM evaluations_hydrated
                    WHERE evaluations_hydrated.status IN ('{EvaluationStatus.success.value}', '{EvaluationStatus.running.value}')
                      AND evaluation_set_group = '{EvaluationSetGroup.validator.value}'::EvaluationSetGroup
                    GROUP BY agent_id
                ),
                screener_2_scores AS (
                    SELECT agent_id, COALESCE(MAX(score), 0) AS score FROM evaluations_hydrated
                    WHERE evaluation_set_group = '{EvaluationSetGroup.screener_2.value}'::EvaluationSetGroup
                      AND evaluations_hydrated.status = '{EvaluationStatus.success.value}'
                    GROUP BY agent_id
                )
            SELECT
                agent_id,
                COALESCE(num_running_evals, 0) as num_running_evals,
                COALESCE(num_finished_evals, 0) as num_finished_evals
            FROM agents
                 LEFT JOIN screener_2_scores USING (agent_id)
                 LEFT JOIN validator_eval_counts USING (agent_id)
            WHERE
                agents.status = '{AgentStatus.evaluating.value}'
              AND NOT COALESCE(already_evaluated, false)
              AND COALESCE(num_running_evals, 0) + COALESCE(num_finished_evals, 0) < $2
              AND agents.agent_id NOT IN (SELECT agent_id FROM benchmark_agent_ids)
            ORDER BY
                screener_2_scores.score DESC,
                agents.created_at ASC
            LIMIT 1
            """,
            validator_hotkey,
            config.NUM_EVALS_PER_AGENT
        )

    if result is None:
        return None

    return result["agent_id"]
