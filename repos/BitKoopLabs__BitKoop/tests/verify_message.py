"""
Test module for verifying messages
"""

import unittest
from fiber import (
    Keypair,
)
from bittensor_wallet import (
    Wallet,
)


class TestMessageVerification(unittest.TestCase):
    def setUp(
        self,
    ):
        self.hotkey = "5GEQ4ZkrXcz7y3HK8TAd4V9ZeERJKPNeF21EifKqCJRkZGaY"
        self.keypair = Keypair(self.hotkey)

        self.message = '{"something": "here", "timestamp": 1719908486}'
        self.signature = "2ea83ab125603aa3047c3ecb8c4ceade73de705cbb39c1de04ddd862a58d7c444d9eeaef816bfbf8fae79088fb5ed59a29189693c2cd95183fd99fd6d60d7b8e"
        self.signature_bytes = bytes.fromhex(self.signature)

    def test_verify_message(
        self,
    ):
        """Test that message verification works correctly"""
        verify_result = self.keypair.verify(
            self.message,
            self.signature_bytes,
        )
        self.assertTrue(
            verify_result,
            "Message verification should succeed",
        )


if __name__ == "__main__":
    unittest.main()
