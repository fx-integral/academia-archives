import json
from uuid import UUID
from typing import Optional, List, Dict, Any
from datetime import datetime
from utils.database import db_operation, DatabaseConnection

@db_operation
async def insert_inference(
    conn: DatabaseConnection,
    evaluation_run_id: UUID,
    provider: str,
    model: str,
    temperature: float,
    messages: List[Dict[str, Any]],
    status_code: Optional[int] = None,
    response: Optional[str] = None,
    num_input_tokens: Optional[int] = None,
    num_output_tokens: Optional[int] = None,
    cost_usd: Optional[float] = None,
    request_received_at: Optional[datetime] = None,
    response_sent_at: Optional[datetime] = None
) -> UUID:
    """
    Insert a new inference record and return the generated inference_id.
    """
    result = await conn.fetchrow(
        """
        INSERT INTO inferences (
            evaluation_run_id, provider, model, temperature, messages,
            status_code, response, num_input_tokens, num_output_tokens,
            cost_usd, request_received_at, response_sent_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        RETURNING inference_id
        """,
        evaluation_run_id, provider, model, temperature, json.dumps(messages),
        status_code, response, num_input_tokens, num_output_tokens,
        cost_usd, request_received_at, response_sent_at
    )
    return result['inference_id']


@db_operation
async def get_cost_report_for_agent(conn: DatabaseConnection, agent_id: str) -> Dict[str, Any]:
    rows = await conn.fetch(
        """
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
        WHERE a.agent_id = $1
        """,
        agent_id
    )
    return [dict(row) for row in rows]