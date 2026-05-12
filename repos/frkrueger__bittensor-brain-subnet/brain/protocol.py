# The MIT License (MIT)
# Copyright © 2023 Bittensor "Brain" Subnet

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the "Software"), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import bittensor
import pydantic
from typing import List, Optional, Dict, Any, Union

class Statement(pydantic.BaseModel):
    """
    Represents a statement to be verified by the miners.
    """
    id: str
    text: str
    timestamp: str  # ISO format timestamp
    context: Optional[Dict[str, Any]] = None
    
class PredictionResult(pydantic.BaseModel):
    """
    Represents the result of a prediction market verification.
    """
    statement_id: str
    is_true: bool
    confidence: float  # 0.0 to 1.0
    explanation: str
    evidence: List[Dict[str, Any]]
    methodology: str  # Description of how the result was determined
    
class VerificationRequest(bittensor.Synapse):
    """
    Represents a request from a validator to a miner to verify a statement.
    """
    statement: Statement
    
    def deserialize(self) -> 'VerificationRequest':
        return self
        
class VerificationResponse(bittensor.Synapse):
    """
    Represents a response from a miner to a validator with the verification result.
    """
    result: PredictionResult
    computation_time: float  # Time taken to compute the result in seconds
    version: str  # Version of the miner software
    
    def deserialize(self) -> 'VerificationResponse':
        return self

class ValidationRequest(bittensor.Synapse):
    """
    Represents a request from a validator to a miner to validate another miner's result.
    """
    statement: Statement
    miner_result: PredictionResult
    
    def deserialize(self) -> 'ValidationRequest':
        return self
        
class ValidationResponse(bittensor.Synapse):
    """
    Represents a response from a miner to a validator with the validation result.
    """
    is_valid: bool
    confidence: float  # 0.0 to 1.0
    explanation: str
    alternative_result: Optional[PredictionResult] = None
    
    def deserialize(self) -> 'ValidationResponse':
        return self
