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

import time
import torch
import bittensor
from typing import List, Tuple, Dict, Any, Optional
from brain.protocol import Statement, VerificationRequest, VerificationResponse

def get_verification_responses(
    metagraph: 'bittensor.metagraph.Metagraph',
    dendrite: 'bittensor.dendrite.Dendrite',
    statement: Statement,
    timeout: float = 12.0,
    exclude: Optional[List[int]] = None
) -> Tuple[List[VerificationResponse], List[float], List[int]]:
    """
    Gets verification responses from miners in the network.
    
    Args:
        metagraph: Bittensor metagraph containing network state.
        dendrite: Bittensor dendrite for making RPC calls.
        statement: The statement to be verified.
        timeout: Timeout for the request in seconds.
        exclude: List of axon indices to exclude from the request.
        
    Returns:
        responses: List of verification responses.
        times: List of response times.
        uids: List of UIDs that were queried.
    """
    if exclude is None:
        exclude = []
        
    # Get UIDs of miners that are serving the network.
    serving_axons = [
        uid for uid, axon in enumerate(metagraph.axons) 
        if axon.is_serving and uid not in exclude
    ]
    
    # Create the verification request.
    request = VerificationRequest(statement=statement)
    
    # Get responses from the network.
    responses = dendrite.query(
        axons=[metagraph.axons[uid] for uid in serving_axons],
        synapse=request,
        deserialize=True,
        timeout=timeout
    )
    
    # Process responses and filter out failures.
    successful_responses = []
    successful_times = []
    successful_uids = []
    
    for i, (response, uid) in enumerate(zip(responses, serving_axons)):
        if isinstance(response, VerificationResponse):
            successful_responses.append(response)
            successful_times.append(response.dendrite.process_time)
            successful_uids.append(uid)
    
    return successful_responses, successful_times, successful_uids
