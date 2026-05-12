import unittest

from flamewire.gateway.types import CheckStats, MinerNode
from flamewire.gateway.rpc import storage_key
from flamewire.utils.scoring import (
    NodeScore,
    MinerScore,
    calculate_miner_scores,
    calculate_node_scores,
    scores_to_weights,
)


class TestScoringModel(unittest.TestCase):
    def test_storage_key_matches_substrate_reference(self):
        self.assertEqual(
            storage_key("System", "Events"),
            "0x26aa394eea5630e07c48ae0c9558cef780d41e5e16056765bc8461851072c9d7",
        )

    def test_node_scores_follow_40_30_30_weights(self):
        nodes = [
            MinerNode(
                miner_hotkey="miner_a",
                node_id="a_us",
                region="us",
                health=CheckStats(total=10, passed=9),
                data_verified=True,
                avg_latency_ms=100.0,
            ),
            MinerNode(
                miner_hotkey="miner_a",
                node_id="a_eu",
                region="eu",
                health=CheckStats(total=10, passed=10),
                data_verified=False,
                avg_latency_ms=150.0,
            ),
            MinerNode(
                miner_hotkey="miner_b",
                node_id="b_us",
                region="us",
                health=CheckStats(total=10, passed=8),
                data_verified=True,
                avg_latency_ms=200.0,
            ),
        ]

        node_scores = calculate_node_scores(nodes)
        by_node = {score.node_id: score for score in node_scores}

        self.assertAlmostEqual(by_node["a_us"].total, 0.97, places=6)
        self.assertAlmostEqual(by_node["a_eu"].total, 0.0, places=6)
        self.assertAlmostEqual(by_node["b_us"].total, 0.64, places=6)
        self.assertEqual(by_node["a_eu"].correctness, 0.0)

    def test_incorrect_data_zeroes_full_node_score(self):
        nodes = [
            MinerNode(
                miner_hotkey="miner_a",
                node_id="a_us",
                region="us",
                health=CheckStats(total=10, passed=10),
                data_verified=False,
                avg_latency_ms=10.0,
            )
        ]

        node_scores = calculate_node_scores(nodes)
        self.assertEqual(len(node_scores), 1)
        self.assertAlmostEqual(node_scores[0].correctness, 0.0, places=6)
        self.assertAlmostEqual(node_scores[0].total, 0.0, places=6)

    def test_miner_scores_apply_multiplier_diminishing_and_diversity(self):
        node_scores = [
            NodeScore("miner_a", "a_eu", "eu", 1.0, 1.0, 1.0, 0.9),
            NodeScore("miner_a", "a_us", "us", 1.0, 1.0, 1.0, 0.8),
            NodeScore("miner_a", "a_as", "as", 1.0, 1.0, 1.0, 0.7),
            NodeScore("miner_b", "b_eu_1", "eu", 1.0, 1.0, 1.0, 0.6),
            NodeScore("miner_b", "b_eu_2", "eu", 1.0, 1.0, 1.0, 0.6),
            NodeScore("miner_b", "b_us", "us", 1.0, 1.0, 1.0, 0.4),
            NodeScore("miner_c", "c_as", "as", 1.0, 1.0, 1.0, 0.5),
        ]

        miner_scores = calculate_miner_scores(node_scores)
        by_miner = {score.miner_hotkey: score for score in miner_scores}

        self.assertAlmostEqual(by_miner["miner_a"].region_multipliers["eu"], 0.7777777777777778, places=6)
        self.assertAlmostEqual(by_miner["miner_a"].region_multipliers["us"], 1.1666666666666667, places=6)
        self.assertAlmostEqual(by_miner["miner_a"].region_multipliers["as"], 1.1666666666666667, places=6)

        self.assertAlmostEqual(by_miner["miner_b"].region_base_scores["eu"], 0.9, places=6)
        self.assertAlmostEqual(by_miner["miner_b"].regions["eu"], 0.7, places=6)

        self.assertEqual(by_miner["miner_a"].regions_covered, 3)
        self.assertEqual(by_miner["miner_b"].regions_covered, 2)
        self.assertEqual(by_miner["miner_c"].regions_covered, 1)
        self.assertAlmostEqual(by_miner["miner_a"].diversity_bonus, 1.2, places=6)
        self.assertAlmostEqual(by_miner["miner_b"].diversity_bonus, 1.1, places=6)
        self.assertAlmostEqual(by_miner["miner_c"].diversity_bonus, 1.0, places=6)

        self.assertAlmostEqual(by_miner["miner_a"].total, 2.94, places=6)
        self.assertAlmostEqual(by_miner["miner_b"].total, 1.2833333333333334, places=6)
        self.assertAlmostEqual(by_miner["miner_c"].total, 0.5833333333333334, places=6)

    def test_regional_multiplier_bounds_are_clamped(self):
        node_scores = []
        for i in range(10):
            node_scores.append(NodeScore("miner_eu", f"eu_{i}", "eu", 1.0, 1.0, 1.0, 1.0))
        node_scores.append(NodeScore("miner_us", "us_0", "us", 1.0, 1.0, 1.0, 1.0))
        node_scores.append(NodeScore("miner_as", "as_0", "as", 1.0, 1.0, 1.0, 1.0))

        miner_scores = calculate_miner_scores(node_scores)
        any_score = miner_scores[0]
        self.assertAlmostEqual(any_score.region_multipliers["eu"], 0.5, places=6)
        self.assertAlmostEqual(any_score.region_multipliers["us"], 2.0, places=6)
        self.assertAlmostEqual(any_score.region_multipliers["as"], 2.0, places=6)

    def test_scores_to_weights_is_pro_rata(self):
        miner_scores = [
            MinerScore(
                miner_hotkey="miner_a",
                regions={"us": 1.0, "eu": 0.0, "as": 0.0},
                region_base_scores={"us": 1.0, "eu": 0.0, "as": 0.0},
                region_multipliers={"us": 1.0, "eu": 1.0, "as": 1.0},
                regions_covered=1,
                diversity_bonus=1.0,
                total=3.0,
            ),
            MinerScore(
                miner_hotkey="miner_b",
                regions={"us": 0.0, "eu": 1.0, "as": 0.0},
                region_base_scores={"us": 0.0, "eu": 1.0, "as": 0.0},
                region_multipliers={"us": 1.0, "eu": 1.0, "as": 1.0},
                regions_covered=1,
                diversity_bonus=1.0,
                total=1.0,
            ),
        ]

        weights = scores_to_weights(miner_scores, ["miner_a", "miner_b", "miner_c"])
        self.assertAlmostEqual(float(weights[0]), 0.75, places=6)
        self.assertAlmostEqual(float(weights[1]), 0.25, places=6)
        self.assertAlmostEqual(float(weights[2]), 0.0, places=6)

if __name__ == "__main__":
    unittest.main()
