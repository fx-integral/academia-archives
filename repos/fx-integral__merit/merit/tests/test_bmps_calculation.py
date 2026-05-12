import unittest

class TestBMPSCalculation(unittest.TestCase):
    def test_normalized_weights_sum_to_one(self):
        bmps_scores = [1.0, 2.0, 3.0]
        total_bmps = sum(bmps_scores)
        normalized_weights = [score / total_bmps for score in bmps_scores]
        self.assertAlmostEqual(sum(normalized_weights), 1.0, places=5)

    def test_zero_total_bmps(self):
        bmps_scores = [0.0, 0.0, 0.0]
        total_bmps = sum(bmps_scores)
        normalized_weights = [score / total_bmps if total_bmps > 0 else 0 for score in bmps_scores]
        self.assertEqual(sum(normalized_weights), 0.0)

if __name__ == "__main__":
    unittest.main()
