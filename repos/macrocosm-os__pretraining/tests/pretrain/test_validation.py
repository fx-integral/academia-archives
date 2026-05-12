import unittest
import pretrain as pt
from taoverse.model.competition.epsilon import LinearDecay


class TestValidation(unittest.TestCase):
    def test_compute_competitive_uids_filters_clones(self):
        # Check that if the current top model submits a few clones, they are filtered out.
        uid_to_average_loss = {100: 0.5, 50: 0.5, 75: 0.499}
        uid_to_block = {100: 1000, 50: 2000, 75: 2001}
        epsilon_func = LinearDecay(0.005, 0.0001, 1000)
        self.assertEqual(
            sorted(
                pt.validation.compute_competitive_uids(
                    uid_to_average_loss, uid_to_block, epsilon_func
                )
            ),
            [75, 100],
        )

        # Check that if a new top model submits clones, they are filtered out.
        uid_to_average_loss = {100: 0.5, 50: 0.499, 75: 0.499}
        uid_to_block = {100: 1000, 50: 2000, 75: 2001}
        epsilon_func = LinearDecay(0.005, 0.0001, 1000)
        self.assertEqual(
            sorted(
                pt.validation.compute_competitive_uids(
                    uid_to_average_loss, uid_to_block, epsilon_func
                )
            ),
            [50, 100],
        )

    def test_compute_competitive_uids_better_models_sequentially_better(self):
        # Each uploaded model is better than the previous. Expect to keep all of them.
        uid_to_average_loss = {100: 0.5, 50: 0.499, 75: 0.498}
        uid_to_block = {100: 1000, 50: 2000, 75: 2500}
        epsilon_func = LinearDecay(0.005, 0.0001, 1000)
        self.assertEqual(
            sorted(
                pt.validation.compute_competitive_uids(
                    uid_to_average_loss, uid_to_block, epsilon_func
                )
            ),
            [50, 75, 100],
        )

    def test_compute_competitive_uids_less_than_epsilon_better(self):
        # Models are sequentially better, but less than epislon at full decay. Expect to only keep the first.
        uid_to_average_loss = {100: 0.5, 50: 0.4999, 75: 0.499}
        uid_to_block = {100: 1000, 50: 2000, 75: 2500}
        epsilon_func = LinearDecay(0.005, 0.01, 1000)
        self.assertEqual(
            sorted(
                pt.validation.compute_competitive_uids(
                    uid_to_average_loss, uid_to_block, epsilon_func
                )
            ),
            [100],
        )

    def test_compute_competitive_uids_later_worse_model_filtered(self):
        # Models are sequentially better, but the last one is worse than a previous model.
        uid_to_average_loss = {100: 0.5, 50: 0.498, 75: 0.499}
        uid_to_block = {100: 1000, 50: 2000, 75: 2500}
        epsilon_func = LinearDecay(0.005, 0.0001, 1000)
        self.assertEqual(
            sorted(
                pt.validation.compute_competitive_uids(
                    uid_to_average_loss, uid_to_block, epsilon_func
                )
            ),
            [50, 100],
        )

    def test_compute_competitive_uids_few_models(self):
        # Make sure the function works with none or only a few models.
        epsilon_func = LinearDecay(0.005, 0.0001, 1000)
        self.assertEqual(
            pt.validation.compute_competitive_uids({}, {}, epsilon_func), []
        )
        self.assertEqual(
            pt.validation.compute_competitive_uids(
                {100: 0.5}, {100: 1000}, epsilon_func
            ),
            [100],
        )
        self.assertEqual(
            pt.validation.compute_competitive_uids(
                {100: 0.5, 50: 0.7}, {100: 1000, 50: 2000}, epsilon_func
            ),
            [100],
        )

    def test_compute_competitive_uids_same_block(self):
        # Make sure that if two models are uploaded at the same block, the one with the lower average loss is kept.
        uid_to_average_loss = {100: 0.5, 50: 0.4}
        uid_to_block = {100: 1000, 50: 1000}
        epsilon_func = LinearDecay(0.005, 0.0001, 1000)
        self.assertEqual(
            sorted(
                pt.validation.compute_competitive_uids(
                    uid_to_average_loss, uid_to_block, epsilon_func
                )
            ),
            [50],
        )

        # Check that if a new top model submits clones, they are filtered out.
        uid_to_average_loss = {100: 0.5, 50: 0.499, 75: 0.499}
        uid_to_block = {100: 1000, 50: 2000, 75: 2001}
        epsilon_func = LinearDecay(0.005, 0.0001, 1000)
        self.assertEqual(
            sorted(
                pt.validation.compute_competitive_uids(
                    uid_to_average_loss, uid_to_block, epsilon_func
                )
            ),
            [50, 100],
        )

    def test_compute_wins_one_uid(self):
        # Verifies compute_wins works with a single uid.
        wins, win_rates = pt.validation.compute_wins(
            [100], {100: 0.5}, {100: 1000}, LinearDecay(0.005, 0.0001, 1000), 1000
        )
        self.assertEqual(wins, {100: 0})
        self.assertEqual(win_rates, {100: 1.0})

    def test_compute_filtered_win_rates(self):
        # Mimic what the validator does by first filtering the models and then computing win rates.

        # The current top model with submitted clones.
        uid_to_average_loss = {100: 0.5, 50: 0.5, 75: 0.499}
        uid_to_block = {100: 1000, 50: 2000, 75: 2001}
        curr_block = 2001
        epsilon_func = LinearDecay(0.005, 0.0001, 2000)
        competitive_uids = pt.validation.compute_competitive_uids(
            uid_to_average_loss, uid_to_block, epsilon_func
        )
        wins, win_rates = pt.validation.compute_wins(
            competitive_uids,
            uid_to_average_loss,
            uid_to_block,
            epsilon_func,
            curr_block,
        )
        self.assertEqual(wins, {100: 1, 75: 0})
        self.assertEqual(win_rates, {100: 1.0, 75: 0.0})

        # Verify the case where a new top model submits a few clones.
        uid_to_average_loss = {100: 0.5, 50: 0.499, 75: 0.499, 80: 0.499}
        uid_to_block = {100: 1000, 50: 2000, 75: 2001, 80: 2002}
        curr_block = 2002
        epsilon_func = LinearDecay(0.005, 0.0001, 2000)
        competitive_uids = pt.validation.compute_competitive_uids(
            uid_to_average_loss, uid_to_block, epsilon_func
        )
        wins, win_rates = pt.validation.compute_wins(
            competitive_uids,
            uid_to_average_loss,
            uid_to_block,
            epsilon_func,
            curr_block,
        )
        self.assertEqual(wins, {100: 1, 50: 0})
        self.assertEqual(win_rates, {100: 1.0, 50: 0.0})
