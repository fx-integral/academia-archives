import json
import yaml
import utils.logger as logger
from enum import Enum
from uuid import UUID
from typing import Dict, List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from utils.database import DatabaseConnection, db_operation
from utils.token import get_token_count

class AgentStatus(str, Enum):
    screening_1 = 'screening_1'
    failed_screening_1 = 'failed_screening_1'
    screening_2 = 'screening_2'
    failed_screening_2 = 'failed_screening_2'
    evaluating = 'evaluating'
    finished = 'finished'

class SamplingParams(BaseModel):
    temperature: float = Field(ge=0, le=2)
    top_p: Optional[float] = Field(None, ge=0, le=1)
    max_tokens: Optional[int] = Field(None, gt=0)
    stop_sequences: Optional[List[str]] = None

class MessageExample(BaseModel):
    role: str = Field(pattern="^(user|assistant|system)$")
    content: str = Field(max_length=8192)

class Agent(BaseModel):    
    agent_id: Optional[UUID] = None  
    miner_hotkey: str
    name: str
    version_num: int
    status: AgentStatus
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="ISO8601 timestamp of submission creation"
    )
    ip_address: Optional[str] = None   
    miner_uid: Optional[str] = None
    provider: str = Field(description="LLM provider name")
    model: str = Field(description="LLM model name")
    system_prompt_template: str = Field(description="Jinja2 template for system prompt")
    user_prompt_template: str = Field(description="Jinja2 template for user prompt")
    sampling_params: SamplingParams = Field(description="Sampling parameters for LLM")
    fewshot_examples: Optional[List[MessageExample]] = Field(None, max_length=64)
    eval_scores: Dict[str, float] = Field(description="Evaluation scores claimed by the miner", default_factory=dict)

    @staticmethod
    def token_count(agent: "Agent") -> int:
        if not agent:
            return 0
        system_tokens = get_token_count(agent.system_prompt_template if agent.system_prompt_template else "")
        user_tokens = get_token_count(agent.user_prompt_template if agent.user_prompt_template else "")
        fewshot_tokens = sum(get_token_count(example.content) for example in agent.fewshot_examples) if agent.fewshot_examples else 0
        total_tokens = system_tokens + user_tokens + fewshot_tokens
        return total_tokens

    @staticmethod
    def from_yaml(yaml_content: str) -> "Agent":        
        data = yaml.safe_load(yaml_content)
        return Agent(**data)
    
    @staticmethod
    def to_yaml(agent: "Agent") -> str:        
        return yaml.safe_dump(agent.model_dump(mode='json'))
    
    @staticmethod
    def from_path(path: str) -> "Agent":
        with open(path, 'r', encoding='utf-8') as f:
            yaml_content = f.read()
        return Agent.from_yaml(yaml_content)

    @staticmethod
    @db_operation
    async def from_db(conn: DatabaseConnection, agent_id: str) -> "Agent":
        try:
            row = await conn.fetchrow("SELECT * FROM agents WHERE agent_id = $1", agent_id)
            if row:
                return Agent.parse_agent_from_db_row(row)
            else:
                raise ValueError(f"Agent with id {agent_id} not found")
        except Exception as e:
            logger.error(f"Error fetching agent {agent_id}: {e}")
            raise

    @staticmethod
    def parse_agent_from_db_row(row: dict) -> "Agent":
        """Parse JSON fields from a DB row and return an Agent instance."""
        result = dict(row)
        result['sampling_params'] = json.loads(result['sampling_params']) if result['sampling_params'] else {}
        result['fewshot_examples'] = json.loads(result['fewshot_examples']) if result['fewshot_examples'] else []
        result['eval_scores'] = json.loads(result['eval_scores']) if result['eval_scores'] else {}
        return Agent(**result)
    

class PossiblyBenchmarkAgent(Agent):
    is_benchmark_agent: bool
    benchmark_description: Optional[str] = None

class BenchmarkAgentScored(Agent):
    benchmark_description: Optional[str] = None
    set_id: int
    approved: bool
    validator_count: int
    final_score: float

class AgentScored(Agent):
    set_id: int
    approved: bool
    validator_count: int
    final_score: float