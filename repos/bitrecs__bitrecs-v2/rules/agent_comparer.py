import json
import logging
import hashlib
import numpy as np
from typing import Optional
from datetime import datetime, timezone
from models.agent import Agent
from utils.token import get_token_count

logger = logging.getLogger(__name__)

class AgentComparer:
    """
    A class to calculate cosine distance between two Agent instances.
    Uses database-backed embedding cache with one embedding per agent.
    """
    
    def __init__(self, provider, use_db_cache: bool = True):
        if not provider:
            raise ValueError("Provider instance is required")
        
        self.provider = provider
        self.embedding_dim = 768
        self.use_db_cache = use_db_cache
        self._memory_cache: dict[str, np.ndarray] = {}

    @staticmethod
    def get_agent_hash_fields(agent: Agent) -> str:
        """Generate a string representation of the agent fields relevant for hashing."""
        if not agent:
            raise ValueError("Agent instance is required to generate hash fields")
        return "\n".join([
            agent.provider,
            agent.model,
            agent.system_prompt_template,
            agent.user_prompt_template,
            str(agent.sampling_params.temperature if agent.sampling_params.temperature is not None else "0.0"),
        ])
    
    @staticmethod
    def get_agent_hash(agent: Agent) -> str:
        hash_fields = AgentComparer.get_agent_hash_fields(agent)
        return hashlib.sha256(hash_fields.encode('utf-8')).hexdigest()
    
    def _get_agent_text(self, agent: Agent) -> str:
        """Generate concatenated text representation of agent for embedding."""
        # return "\n".join([
        #     agent.provider,
        #     agent.model,
        #     agent.system_prompt_template,
        #     agent.user_prompt_template,
        #     str(agent.sampling_params.temperature if agent.sampling_params.temperature is not None else "0.0"),
        # ])
        return AgentComparer.get_agent_hash_fields(agent)
    
    async def _log_embedding_request(
        self,
        input_text: str,
        status_code: Optional[int] = None,
        num_tokens: Optional[int] = None,
        cost_usd: Optional[float] = None,
        request_received_at: Optional[datetime] = None,
        response_sent_at: Optional[datetime] = None
    ):
        """Log embedding API request to database for tracking/billing."""
        if not self.use_db_cache:
            return
            
        try:
            from utils.database import DB_POOL
            
            if DB_POOL is None:
                return
                
            async with DB_POOL.acquire() as conn:
                await conn.execute("""
                    INSERT INTO embedding_requests 
                        (provider, model, input_text, dimensions, status_code, 
                         num_tokens, cost_usd, request_received_at, response_sent_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                    self.provider.__class__.__name__.lower(),
                    self.provider.model,
                    input_text,
                    self.embedding_dim,
                    status_code,
                    num_tokens,
                    cost_usd,
                    request_received_at or datetime.now(timezone.utc),
                    response_sent_at
                )
                logger.debug(f"Logged embedding request for {self.provider.model}")
        except Exception as e:
            logger.warning(f"Could not log embedding request: {e}")
    
    async def _get_cached_embedding(self, agent_id: str) -> Optional[np.ndarray]:
        """Retrieve embedding from database cache."""
        if not self.use_db_cache:
            return None
            
        try:
            from utils.database import DB_POOL
            
            if DB_POOL is None:
                logger.debug("DB_POOL is None, skipping cache lookup")
                return None
                
            async with DB_POOL.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT embedding_vector
                    FROM agent_embeddings
                    WHERE agent_id = $1
                      AND embedding_model = $2
                """, agent_id, self.provider.model)
                
                if row and row['embedding_vector']:
                    logger.debug(f"Found cached embedding for agent {agent_id}")
                    
                    # pgvector can return as string or list depending on driver
                    embedding_data = row['embedding_vector']
                    
                    if isinstance(embedding_data, str):
                        # Parse string representation: "[0.1, 0.2, ...]"
                        embedding_list = json.loads(embedding_data)
                    elif isinstance(embedding_data, list):
                        embedding_list = embedding_data
                    else:
                        # Try to convert directly
                        embedding_list = list(embedding_data)
                    
                    return np.array(embedding_list, dtype=np.float32)
                else:
                    logger.debug(f"No cached embedding found for agent {agent_id}")
        except Exception as e:
            # If database is unavailable, just return None (will generate fresh embedding)
            logger.warning(f"Database cache unavailable: {e}", exc_info=True)
            
        return None
    
    async def _store_embedding(
        self,
        agent_id: str,
        agent_text: str,
        embedding: np.ndarray
    ):
        """Store embedding in database."""
        if not self.use_db_cache:
            logger.debug("DB cache disabled, skipping store")
            return
            
        try:
            from utils.database import DB_POOL
            
            if DB_POOL is None:
                logger.warning("DB_POOL is None, cannot store embedding")
                return
                
            async with DB_POOL.acquire() as conn:
                logger.debug(f"Storing embedding for agent {agent_id}")
                
                # Convert numpy array to list, then to pgvector string format
                embedding_list = embedding.tolist()
                
                await conn.execute("""
                    INSERT INTO agent_embeddings 
                        (agent_id, agent_text, embedding_provider, embedding_model, embedding_vector)
                    VALUES ($1, $2, $3, $4, $5::vector)
                    ON CONFLICT (agent_id)
                    DO UPDATE SET 
                        agent_text = EXCLUDED.agent_text,
                        embedding_vector = EXCLUDED.embedding_vector,
                        updated_at = NOW()
                """, 
                    agent_id,
                    agent_text,
                    self.provider.__class__.__name__.lower(),
                    self.provider.model,
                    str(embedding_list)  # Convert to string for pgvector
                )
                logger.info(f"Successfully stored embedding for agent {agent_id}")
        except Exception as e:            
            logger.error(f"Could not store embedding in database: {e}", exc_info=True)
            # crash if DB is down
            raise
    
    async def _vectorize_agent(self, agent: Agent) -> np.ndarray:
        """
        Vectorize an agent into a single embedding vector.
        Uses database cache with memory cache fallback.
        """
        agent_id_str = str(agent.agent_id)
        
        # Check memory cache first (fastest)
        if agent_id_str in self._memory_cache:
            logger.debug(f"Using memory cached embedding for agent {agent_id_str}")
            return self._memory_cache[agent_id_str]
        
        # Check database cache
        cached_embedding = await self._get_cached_embedding(agent_id_str)
        if cached_embedding is not None:
            logger.debug(f"Using DB cached embedding for agent {agent_id_str}")
            self._memory_cache[agent_id_str] = cached_embedding
            return cached_embedding
        
        # Generate new embedding
        logger.info(f"Generating new embedding for agent {agent_id_str}")
        agent_text = self._get_agent_text(agent)
        
        # Track timing for logging
        request_start = datetime.now(timezone.utc)
        
        try:
            # Get embedding from API (single call for concatenated text)
            embedding_list = self.provider.get_embeddings(agent_text)
            embedding = np.array(embedding_list, dtype=np.float32)
            
            response_end = datetime.now(timezone.utc)
            
            # Estimate tokens (rough approximation: ~4 chars per token)
            #estimated_tokens = len(agent_text) // 4
            estimated_tokens = get_token_count(agent_text)
            
            # Log the successful API request
            await self._log_embedding_request(
                input_text=agent_text,
                status_code=200,
                num_tokens=estimated_tokens,
                cost_usd=None,  # Add cost calculation if you have pricing info
                request_received_at=request_start,
                response_sent_at=response_end
            )
            
            # Store in database (will silently fail if DB unavailable)
            await self._store_embedding(agent_id_str, agent_text, embedding)
            
            # Cache in memory
            self._memory_cache[agent_id_str] = embedding
            
            return embedding
            
        except Exception as e:
            response_end = datetime.now(timezone.utc)
            
            # Log the failed API request
            await self._log_embedding_request(
                input_text=agent_text,
                status_code=500,  # Assume 500 for general errors
                num_tokens=None,
                cost_usd=None,
                request_received_at=request_start,
                response_sent_at=response_end
            )
            
            # Re-raise the exception
            raise
    
    async def cosine_distance(self, agent1: Agent, agent2: Agent) -> float:
        """
        Calculate the cosine distance between two Agent instances.
        
        Cosine distance = 1 - cosine_similarity.
        Returns 0.0 for identical agents.
        """        
        if agent1.agent_id == agent2.agent_id:
            return 0.0
        
        vec1 = await self._vectorize_agent(agent1)
        vec2 = await self._vectorize_agent(agent2)        
        
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        
        if norm1 == 0 or norm2 == 0:
            similarity = 1.0 if np.allclose(vec1, vec2) else 0.0
        else:
            similarity = dot_product / (norm1 * norm2)            
            similarity = np.clip(similarity, -1.0, 1.0)
        
        distance = 1 - similarity
        distance = max(0.0, min(2.0, distance))        
        
        logger.debug(f"Cosine distance between {agent1.agent_id} and {agent2.agent_id}: {distance:.6f}")

        return float(distance)
    
    async def find_similar_agents(
        self, 
        agent: Agent, 
        threshold: float = 0.1,
        limit: int = 10
    ) -> list[tuple[str, float]]:
        """
        Find agents similar to the given agent using vector similarity search.
        
        #TODO: dimi check join on agent table logic

        Args:
            agent: The agent to compare against
            threshold: Maximum cosine distance (0.0 = identical, 1.0 = opposite)
            limit: Maximum number of results
            
        Returns:
            List of (agent_id, distance) tuples sorted by similarity
        """
        if not self.use_db_cache:
            logger.debug("DB cache disabled, cannot search for similar agents")
            return []
            
        try:
            from utils.database import DB_POOL
            
            if DB_POOL is None:
                logger.warning("DB_POOL is None, cannot search for similar agents")
                return []
                
            vec = await self._vectorize_agent(agent)
            
            async with DB_POOL.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT 
                        ae.agent_id,
                        1 - (ae.embedding_vector <=> $1::vector) as similarity,
                        ae.embedding_vector <=> $1::vector as distance
                    FROM agent_embeddings ae
                    JOIN agents a ON ae.agent_id = a.agent_id
                    WHERE ae.agent_id != $2
                      AND ae.embedding_model = $3
                      AND ae.embedding_vector <=> $1::vector <= $4
                    ORDER BY ae.embedding_vector <=> $1::vector
                    LIMIT $5
                """, 
                    str(vec.tolist()),
                    str(agent.agent_id),
                    self.provider.model,
                    threshold,
                    limit
                )
                
                logger.info(f"Found {len(rows)} similar agents for {agent.agent_id}")
                return [(row['agent_id'], float(row['distance'])) for row in rows]
        except Exception as e:
            logger.error(f"Could not search for similar agents: {e}", exc_info=True)
            return []

    def clear_cache(self):
        """Clear the memory cache."""
        logger.debug("Clearing memory cache")
        self._memory_cache.clear()