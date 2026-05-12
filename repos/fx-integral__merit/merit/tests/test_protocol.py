import unittest
from merit.protocol.merit_protocol import PingRequest, PingResponse

class TestMeritProtocol(unittest.TestCase):
    def test_ping_request_fields(self):
        req = PingRequest(hotkey="test_hotkey")
        self.assertEqual(req.hotkey, "test_hotkey")

    def test_ping_response_fields(self):
        res = PingResponse(token="123456")
        self.assertEqual(res.token, "123456")

if __name__ == "__main__":
    unittest.main()
