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

import torch
import numpy as np
from typing import List, Dict, Any, Tuple
from brain.protocol import VerificationResponse, ValidationResponse, PredictionResult

def calculate_verification_reward(
    responses: List[VerificationResponse],
    ground_truth: Dict[str, Any] = None
) -> torch.FloatTensor:
    """
    Calculate rewards for verification responses.
    
    Args:
        responses: List of verification responses from miners.
        ground_truth: Optional ground truth data if available for evaluation.
        
    Returns:
        rewards: Tensor of rewards for each response.
    """
    if len(responses) == 0:
        return torch.tensor([])
        
    # Initialize rewards
    rewards = torch.zeros(len(responses))
    
    # If ground truth is available, use it to calculate accuracy rewards
    if ground_truth is not None:
        for i, response in enumerate(responses):
            # Check if the miner's prediction matches ground truth
            if response.result.is_true == ground_truth.get('is_true', False):
                # Reward based on confidence - higher confidence for correct answers gets higher reward
                accuracy_score = response.result.confidence
            else:
                # Penalize high confidence for wrong answers
                accuracy_score = 1.0 - response.result.confidence
                
            # Evaluate quality of evidence and explanation
            evidence_quality = min(1.0, len(response.result.evidence) / 5.0)  # Normalize, max 5 pieces of evidence
            explanation_quality = min(1.0, len(response.result.explanation) / 500.0)  # Normalize based on length
            
            # Combine scores with weights
            rewards[i] = 0.6 * accuracy_score + 0.25 * evidence_quality + 0.15 * explanation_quality
    else:
        # Without ground truth, use consensus and quality metrics
        # Extract predictions and confidences
        predictions = [r.result.is_true for r in responses]
        confidences = [r.result.confidence for r in responses]
        
        # Calculate consensus (majority vote)
        consensus = sum(predictions) > len(predictions) / 2
        
        for i, response in enumerate(responses):
            # Reward agreement with consensus
            consensus_agreement = 1.0 if response.result.is_true == consensus else 0.0
            
            # Evaluate quality of evidence and explanation
            evidence_quality = min(1.0, len(response.result.evidence) / 5.0)
            explanation_quality = min(1.0, len(response.result.explanation) / 500.0)
            
            # Evaluate methodology
            methodology_score = min(1.0, len(response.result.methodology) / 300.0)
            
            # Combine scores with weights
            rewards[i] = 0.4 * consensus_agreement + 0.3 * evidence_quality + 0.15 * explanation_quality + 0.15 * methodology_score
    
    return rewards

def calculate_validation_reward(
    validation_responses: List[ValidationResponse],
    verification_responses: List[VerificationResponse],
    verification_rewards: torch.FloatTensor
) -> torch.FloatTensor:
    """
    Calculate rewards for validation responses.
    
    Args:
        validation_responses: List of validation responses from miners.
        verification_responses: List of verification responses that were validated.
        verification_rewards: Tensor of rewards for verification responses.
        
    Returns:
        rewards: Tensor of rewards for each validation response.
    """
    if len(validation_responses) == 0:
        return torch.tensor([])
        
    # Initialize rewards
    rewards = torch.zeros(len(validation_responses))
    
    # For each validation response
    for i, val_response in enumerate(validation_responses):
        # Get the verification response being validated
        ver_response = verification_responses[i % len(verification_responses)]
        ver_reward = verification_rewards[i % len(verification_rewards)]
        
        # Higher reward for correctly identifying high-quality responses
        if val_response.is_valid and ver_reward > 0.7:
            quality_score = 0.9
        # Higher reward for correctly identifying low-quality responses
        elif not val_response.is_valid and ver_reward < 0.3:
            quality_score = 0.9
        # Penalize incorrect validation
        elif val_response.is_valid and ver_reward < 0.3:
            quality_score = 0.1
        elif not val_response.is_valid and ver_reward > 0.7:
            quality_score = 0.1
        else:
            quality_score = 0.5
            
        # Reward for providing detailed explanation
        explanation_quality = min(1.0, len(val_response.explanation) / 300.0)
        
        # Reward for providing alternative result when validation fails
        alternative_quality = 0.0
        if not val_response.is_valid and val_response.alternative_result is not None:
            alternative_quality = 0.2
            
        # Combine scores with weights
        rewards[i] = 0.6 * quality_score + 0.3 * explanation_quality + 0.1 * alternative_quality
    
    return rewards
