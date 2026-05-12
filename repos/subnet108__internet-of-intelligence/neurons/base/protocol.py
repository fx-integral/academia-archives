# The MIT License (MIT)
# Copyright © 2023 Yuma Rao
# Copyright © 2023 Internet Of Intelligence

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

from typing import Dict, Any, Optional
import bittensor as bt

# This is the protocol for the dummy miner and validator.
# It is a simple request-response protocol where the validator sends a request
# to the miner, and the miner responds with a dummy response.

# ---- miner ----
# Example usage:
#   def ai_agent( synapse: AIAgentProtocol ) -> AIAgentProtocol:
#       synapse.output = synapse.input
#       return synapse
#   axon = bt.axon().attach( dummy ).serve(netuid=...).start()

# ---- validator ---
# Example usage:
#   dendrite = bt.dendrite()
#   output = dendrite.query( AIAgentProtocol( input = {"message": ""} ) )
#   assert output == {"result": ""}


class AIAgentProtocol(bt.Synapse):
    """
    A simple AIAgent protocol representation which uses bt.Synapse as its base.
    This protocol helps in handling dummy request and response communication between
    the miner and the validator.

    Attributes:
    - input: An integer value representing the input request sent by the validator.
    - output: An optional integer value which, when filled, represents the response from the miner.
    """

    # Required request input, filled by sending dendrite caller.
    input: Optional[Dict[str, Any]] = None


    # Optional request output, filled by receiving axon.
    output: Optional[Dict[str, Any]] = None

    def deserialize(self) -> Optional[Dict[str, Any]]:
        """
        Deserialize the AIAgentProtocol output. This method retrieves the response from
        the miner in the form of output, deserializes it and returns it
        as the output of the dendrite.query() call.

        Returns:
        - int: The deserialized response, which in this case is the value of output.

        Example:
        Assuming a Dummy instance has a dummy_output value of 5:
        >>> ai_agent_instance = AIAgentProtocol(input=4)
        >>> ai_agent_instance.output = 5
        >>> ai_agent_instance.deserialize()
        5
        """
        return self.output
