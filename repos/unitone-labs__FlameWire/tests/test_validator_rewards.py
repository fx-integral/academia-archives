import unittest

import numpy as np

from neurons.validator import apply_reward_ema


class TestRewardEma(unittest.TestCase):
    def test_inactive_miners_are_zeroed_immediately(self):
        rewards = np.array([0.9, 0.0, 0.4], dtype=np.float32)
        uids = np.array([10, 11, 12], dtype=np.int64)
        previous_scores = np.array([0.8, 0.7, 0.3], dtype=np.float32)
        ema_alpha = 0.1
        initialized = {10, 11, 12}
        active_uids = {10, 12}

        smoothed, next_initialized = apply_reward_ema(
            rewards=rewards,
            uids=uids,
            previous_scores=previous_scores,
            ema_alpha=ema_alpha,
            ema_initialized_uids=initialized,
            active_uids=active_uids,
        )

        self.assertAlmostEqual(float(smoothed[0]), 0.81, places=6)
        self.assertAlmostEqual(float(smoothed[1]), 0.0, places=6)
        self.assertAlmostEqual(float(smoothed[2]), 0.31, places=6)
        self.assertEqual(next_initialized, {10, 12})

    def test_uninitialized_active_uid_uses_raw_score(self):
        rewards = np.array([0.0, 0.5], dtype=np.float32)
        uids = np.array([20, 21], dtype=np.int64)
        previous_scores = np.array([0.9, 0.1], dtype=np.float32)
        ema_alpha = 0.1
        initialized = {20}
        active_uids = {21}

        smoothed, next_initialized = apply_reward_ema(
            rewards=rewards,
            uids=uids,
            previous_scores=previous_scores,
            ema_alpha=ema_alpha,
            ema_initialized_uids=initialized,
            active_uids=active_uids,
        )

        self.assertAlmostEqual(float(smoothed[0]), 0.0, places=6)
        self.assertAlmostEqual(float(smoothed[1]), 0.5, places=6)
        self.assertEqual(next_initialized, {21})


if __name__ == "__main__":
    unittest.main()
