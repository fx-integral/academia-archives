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

import os
import time
import torch
import argparse
import bittensor
import datetime
import traceback
import json
import random
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor

from brain.protocol import (
    Statement,
    PredictionResult,
    VerificationRequest,
    VerificationResponse,
    ValidationRequest,
    ValidationResponse
)
from brain.forward import get_verification_responses
from brain.reward import calculate_verification_reward, calculate_validation_reward

class BrainValidator:
    """
    Implementation of the Brain subnet validator that evaluates miners' verification of prediction market statements.
    """
    
    def __init__(self, config=None):
        """Initialize the Brain validator."""
        # Set up config
        if config is None:
            config = self.get_config()
        self.config = config
        
        # Set up logging
        self.logger = bittensor.logging.get_logger(config.logging.debug)
        
        # Build subtensor connection
        self.subtensor = bittensor.subtensor(
            config=config
        )
        
        # Build wallet
        self.wallet = bittensor.wallet(
            config=config
        )
        
        # Build metagraph
        self.metagraph = self.subtensor.metagraph(
            netuid=config.netuid
        )
        
        # Build dendrite
        self.dendrite = bittensor.dendrite(wallet=self.wallet)
        
        # Set up statement database
        self.statements_db = self.load_statements()
        
        # Set up ground truth database if available
        self.ground_truth_db = self.load_ground_truth()
        
        # Set up rewards history
        self.rewards_history = {}
        
        # Tracking for last update block
        self.last_update_block = 0
        
        # Tracking for last epoch
        self.last_epoch = 0
        
        self.logger.info("Brain validator initialized")
        
    def load_statements(self) -> List[Statement]:
        """
        Load statements from a database or file.
        
        Returns:
            List of statements to verify.
        """
        # This is a placeholder implementation
        # In a real validator, this would load from a database or file
        
        # Example statements
        statements = [
            Statement(
                id="1",
                text="The Dow Jones Industrial Average closed above 30,000 points for the first time on November 24, 2020.",
                timestamp="2020-11-24T00:00:00Z"
            ),
            Statement(
                id="2",
                text="Bitcoin reached an all-time high price of over $60,000 in March 2021.",
                timestamp="2021-03-15T00:00:00Z"
            ),
            Statement(
                id="3",
                text="The Federal Reserve raised interest rates by 0.75 percentage points in June 2022.",
                timestamp="2022-06-15T00:00:00Z"
            )
        ]
        
        return statements
    
    def load_ground_truth(self) -> Dict[str, Any]:
        """
        Load ground truth data for statements if available.
        
        Returns:
            Dictionary mapping statement IDs to ground truth data.
        """
        # This is a placeholder implementation
        # In a real validator, this would load from a database or file
        
        # Example ground truth
        ground_truth = {
            "1": {
                "is_true": True,
                "source": "https://www.cnbc.com/2020/11/24/dow-jones-industrial-average-tops-30000-for-the-first-time.html"
            },
            "2": {
                "is_true": True,
                "source": "https://www.coindesk.com/markets/2021/03/13/bitcoin-reaches-all-time-high-above-60k/"
            },
            "3": {
                "is_true": True,
                "source": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20220615a.htm"
            }
        }
        
        return ground_truth
    
    def get_random_statement(self) -> Statement:
        """
        Get a random statement from the database.
        
        Returns:
            A randomly selected statement.
        """
        return random.choice(self.statements_db)
    
    def run_step(self):
        """Run a single step of the validator."""
        try:
            # Get the current block
            current_block = self.subtensor.get_current_block()
            self.logger.info(f"Current block: {current_block}")
            
            # Check if we need to update the metagraph
            if current_block - self.last_update_block > self.config.validator.metagraph_update_interval:
                self.metagraph = self.subtensor.metagraph(
                    netuid=self.config.netuid
                )
                self.last_update_block = current_block
                self.logger.info(f"Updated metagraph: {len(self.metagraph.axons)} axons found")
            
            # Check if we need to set weights
            current_epoch = current_block // self.config.validator.epoch_length
            if current_epoch > self.last_epoch:
                self.set_weights()
                self.last_epoch = current_epoch
            
            # Select a statement to verify
            statement = self.get_random_statement()
            self.logger.info(f"Selected statement: {statement.text}")
            
            # Get verification responses from miners
            responses, times, uids = get_verification_responses(
                metagraph=self.metagraph,
                dendrite=self.dendrite,
                statement=statement,
                timeout=self.config.validator.verification_timeout
            )
            
            self.logger.info(f"Received {len(responses)} verification responses")
            
            if len(responses) == 0:
                self.logger.warning("No responses received, skipping step")
                return
            
            # Calculate rewards for verification responses
            ground_truth = self.ground_truth_db.get(statement.id)
            verification_rewards = calculate_verification_reward(responses, ground_truth)
            
            # Log the rewards
            for i, (uid, reward) in enumerate(zip(uids, verification_rewards)):
                self.logger.info(f"Miner {uid} verification reward: {reward.item():.4f}")
                
                # Update rewards history
                if uid not in self.rewards_history:
                    self.rewards_history[uid] = []
                self.rewards_history[uid].append((current_block, reward.item()))
            
            # Optionally, get validation responses from miners
            if self.config.validator.run_validation:
                validation_responses = self.get_validation_responses(statement, responses[0], uids)
                
                if len(validation_responses) > 0:
                    # Calculate rewards for validation responses
                    validation_rewards = calculate_validation_reward(
                        validation_responses=validation_responses,
                        verification_responses=[responses[0]],
                        verification_rewards=verification_rewards[0:1]
                    )
                    
                    # Log the validation rewards
                    for i, (uid, reward) in enumerate(zip(uids, validation_rewards)):
                        self.logger.info(f"Miner {uid} validation reward: {reward.item():.4f}")
                        
                        # Update rewards history
                        if uid not in self.rewards_history:
                            self.rewards_history[uid] = []
                        self.rewards_history[uid].append((current_block, reward.item()))
            
        except Exception as e:
            self.logger.error(f"Error in run_step: {str(e)}")
            self.logger.error(traceback.format_exc())
    
    def get_validation_responses(
        self,
        statement: Statement,
        verification_response: VerificationResponse,
        exclude_uids: List[int]
    ) -> List[ValidationResponse]:
        """
        Get validation responses from miners.
        
        Args:
            statement: The statement that was verified.
            verification_response: The verification response to validate.
            exclude_uids: UIDs to exclude from validation requests.
            
        Returns:
            List of validation responses.
        """
        # Get UIDs of miners that are serving the network
        serving_axons = [
            uid for uid, axon in enumerate(self.metagraph.axons) 
            if axon.is_serving and uid not in exclude_uids
        ]
        
        # Create the validation request
        request = ValidationRequest(
            statement=statement,
            miner_result=verification_response.result
        )
        
        # Get responses from the network
        responses = self.dendrite.query(
            axons=[self.metagraph.axons[uid] for uid in serving_axons],
            synapse=request,
            deserialize=True,
            timeout=self.config.validator.validation_timeout
        )
        
        # Process responses and filter out failures
        successful_responses = []
        
        for i, response in enumerate(responses):
            if isinstance(response, ValidationResponse):
                successful_responses.append(response)
        
        return successful_responses
    
    def set_weights(self):
        """Set weights for the miners based on their performance."""
        # Initialize weights
        weights = torch.zeros(len(self.metagraph.uids))
        
        # Calculate weights based on rewards history
        for uid in self.rewards_history:
            # Get recent rewards (last 10 blocks)
            recent_rewards = [reward for block, reward in self.rewards_history[uid][-10:]]
            
            if len(recent_rewards) > 0:
                # Calculate average reward
                avg_reward = sum(recent_rewards) / len(recent_rewards)
                
                # Set weight based on average reward
                weights[uid] = avg_reward
        
        # Normalize weights
        if weights.sum() > 0:
            weights = weights / weights.sum()
        
        # Set weights on the network
        try:
            # Convert weights to uint16 format expected by subtensor
            uint_weights = torch.zeros(len(self.metagraph.uids), dtype=torch.int64)
            for uid, weight in enumerate(weights):
                uint_weights[uid] = int(weight * 65535)
            
            # Set weights
            self.subtensor.set_weights(
                netuid=self.config.netuid,
                wallet=self.wallet,
                uids=self.metagraph.uids,
                weights=uint_weights,
                wait_for_inclusion=False
            )
            
            self.logger.info(f"Set weights: {weights}")
            
        except Exception as e:
            self.logger.error(f"Failed to set weights: {str(e)}")
    
    @staticmethod
    def get_config() -> 'bittensor.config':
        """
        Get the configuration for the validator.
        
        Returns:
            bittensor.config: The configuration object.
        """
        parser = argparse.ArgumentParser()
        
        # Add bittensor specific arguments
        bittensor.subtensor.add_args(parser)
        bittensor.logging.add_args(parser)
        bittensor.wallet.add_args(parser)
        
        # Add custom arguments
        parser.add_argument('--netuid', type=int, default=1, help='The chain subnet UID')
        parser.add_argument('--validator.name', type=str, default="brain_validator", help='Name of the validator')
        parser.add_argument('--validator.verification_timeout', type=float, default=30.0, help='Timeout for verification requests in seconds')
        parser.add_argument('--validator.validation_timeout', type=float, default=30.0, help='Timeout for validation requests in seconds')
        parser.add_argument('--validator.run_validation', action='store_true', help='Whether to run validation requests')
        parser.add_argument('--validator.metagraph_update_interval', type=int, default=100, help='Interval in blocks to update the metagraph')
        parser.add_argument('--validator.epoch_length', type=int, default=100, help='Length of an epoch in blocks')
        
        # Parse the config
        config = bittensor.config(parser)
        
        return config

def main():
    """Main function to run the validator."""
    # Get the config
    config = BrainValidator.get_config()
    
    # Create and start the validator
    validator = BrainValidator(config)
    
    # Keep the validator running
    while True:
        try:
            # Run a step
            validator.run_step()
            
            # Sleep for a bit
            time.sleep(60)
            
        except KeyboardInterrupt:
            validator.logger.info("Keyboard interrupt detected, exiting")
            break
            
        except Exception as e:
            validator.logger.error(f"Error in main loop: {str(e)}")
            validator.logger.error(traceback.format_exc())
            time.sleep(60)

if __name__ == "__main__":
    main()
