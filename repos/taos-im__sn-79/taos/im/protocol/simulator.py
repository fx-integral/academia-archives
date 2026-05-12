# SPDX-FileCopyrightText: 2025 Rayleigh Research <to@rayleigh.re>
# SPDX-License-Identifier: MIT
from taos.common.protocol import BaseModel
from typing import Any

"""
The models required to construct response messages compatible with the validator are defined here.
"""

class SimulatorAgentResponse(BaseModel):
    """
    Represents a response from an agent.

    Attributes:
        agentId (int): Identifier for the agent sending the response.
        delay (int): Delay to be applied in processing the response.
        type (str): Type of the response.
        payload (dict[str, Any] | None): Additional data related to the response.
    """
    agentId: int
    delay: int
    type: str
    payload: dict[str, Any] | None  

    def serialize(self) -> dict:
        """
        Serializes the response into a dictionary format.
        """
        return {
            "agentId": self.agentId,
            "delay": self.delay,
            "type": self.type,
            "payload": self.payload,
        }

class SimulatorResponseBatch(BaseModel):
    """
    Represents a batch of responses from agents.

    Attributes:
        responses (list[SimulatorAgentResponse]): List of agent responses.
    """
    responses: list[SimulatorAgentResponse]

    def __init__(self, responses: list[SimulatorAgentResponse]):
        """
        Initializes the response batch.

        Args:
        - responses: List of agent responses to be included in the batch.
        """
        instructions = []
        for response in responses:
            if response:
                instructions.extend(response.serialize())
        super().__init__(responses=instructions)

    def serialize(self) -> dict:
        """
        Serializes the batch of responses into a dictionary format.

        Returns:
        - A dictionary representation of the response batch.
        """
        return {
            "responses": [response.serialize() for response in self.responses]
        }