import asyncio
import time
import pytest

from bittensor.utils.balance import Balance
from tests.e2e_tests.utils import (
    TestSubnet,
    AdminUtils,
    NETUID,
    ACTIVATE_SUBNET,
    REGISTER_NEURON,
    REGISTER_SUBNET,
    SUDO_SET_ADMIN_FREEZE_WINDOW,
    SUDO_SET_COMMIT_REVEAL_WEIGHTS_ENABLED,
    SUDO_SET_WEIGHTS_SET_RATE_LIMIT,
)


def test_incentive(subtensor, templates, alice_wallet, bob_wallet):
    """
    Test the incentive mechanism and interaction of miners/validators

    Steps:
        1. Register a subnet as Alice and register Bob
        2. Run Alice as validator & Bob as miner. Wait Epoch
        3. Verify miner has correct: trust, rank, consensus, incentive
        4. Verify validator has correct: validator_permit, validator_trust, dividends, stake
    Raises:
        AssertionError: If any of the checks or verifications fail
    """
    alice_sn = TestSubnet(subtensor)
    steps = [
        SUDO_SET_ADMIN_FREEZE_WINDOW(alice_wallet, AdminUtils, True, 0),
        REGISTER_SUBNET(alice_wallet),
        SUDO_SET_COMMIT_REVEAL_WEIGHTS_ENABLED(
            alice_wallet, AdminUtils, True, NETUID, False
        ),
        ACTIVATE_SUBNET(alice_wallet),
        REGISTER_NEURON(bob_wallet),
    ]
    alice_sn.execute_steps(steps)

    # Assert two neurons are in network
    assert len(subtensor.neurons.neurons(netuid=alice_sn.netuid)) == 2, (
        "Alice & Bob not registered in the subnet"
    )

    # Stake so Alice has active_stake for Yuma3 dividend calculation
    assert subtensor.staking.add_stake(
        wallet=alice_wallet,
        netuid=alice_sn.netuid,
        hotkey_ss58=alice_wallet.hotkey.ss58_address,
        amount=Balance.from_tao(10_000),
    ).success

    # Wait for the first epoch to pass
    subtensor.wait_for_block(
        subtensor.subnets.get_next_epoch_start_block(alice_sn.netuid) + 5
    )

    # Get current miner/validator stats
    alice_neuron = subtensor.neurons.neurons(netuid=alice_sn.netuid)[0]

    assert alice_neuron.validator_permit is True
    assert alice_neuron.dividends == 0
    assert alice_neuron.validator_trust == 0
    assert alice_neuron.incentive == 0
    assert alice_neuron.consensus == 0

    bob_neuron = subtensor.neurons.neurons(netuid=alice_sn.netuid)[1]

    assert bob_neuron.incentive == 0
    assert bob_neuron.consensus == 0

    # update weights_set_rate_limit for fast-blocks
    tempo = subtensor.subnets.tempo(alice_sn.netuid)
    alice_sn.execute_one(
        SUDO_SET_WEIGHTS_SET_RATE_LIMIT(alice_wallet, AdminUtils, True, NETUID, tempo)
    )

    # max attempts to run miner and validator
    max_attempt = 3
    while True:
        try:
            with templates.miner(bob_wallet, alice_sn.netuid):
                time.sleep(5)
                with templates.validator(alice_wallet, alice_sn.netuid):
                    time.sleep(5)

            break
        except asyncio.TimeoutError:
            if max_attempt > 0:
                max_attempt -= 1
                continue
            raise

    # wait one tempo (fast block)
    next_epoch_start_block = subtensor.subnets.get_next_epoch_start_block(
        alice_sn.netuid
    )
    subtensor.wait_for_block(next_epoch_start_block + tempo + 1)

    validators = subtensor.metagraphs.get_metagraph_info(
        alice_sn.netuid, selected_indices=[72]
    ).validators

    alice_uid = subtensor.subnets.get_uid_for_hotkey_on_subnet(
        hotkey_ss58=alice_wallet.hotkey.ss58_address, netuid=alice_sn.netuid
    )
    assert validators[alice_uid] == 1

    bob_uid = subtensor.subnets.get_uid_for_hotkey_on_subnet(
        hotkey_ss58=bob_wallet.hotkey.ss58_address, netuid=alice_sn.netuid
    )
    assert validators[bob_uid] == 0

    max_retries = 30
    last_error = None
    for _ in range(max_retries):
        time.sleep(1)
        try:
            neurons = subtensor.neurons.neurons(netuid=alice_sn.netuid)

            # Get current emissions and validate that Alice has gotten tao
            alice_neuron = neurons[0]

            assert alice_neuron.validator_permit is True
            assert alice_neuron.dividends == 1.0, f"dividends={alice_neuron.dividends}"
            assert alice_neuron.stake.tao > 0, f"stake={alice_neuron.stake.tao}"
            assert alice_neuron.validator_trust > 0.99, (
                f"vtrust={alice_neuron.validator_trust}"
            )
            assert alice_neuron.incentive < 0.5, f"incentive={alice_neuron.incentive}"
            assert alice_neuron.consensus < 0.5, f"consensus={alice_neuron.consensus}"

            bob_neuron = neurons[1]

            assert bob_neuron.incentive > 0.5, f"bob.incentive={bob_neuron.incentive}"
            assert bob_neuron.consensus > 0.5, f"bob.consensus={bob_neuron.consensus}"

            bonds = subtensor.subnets.bonds(alice_sn.netuid)

            assert len(bonds) == 2, f"bonds={bonds}"
            assert bonds[0][0] == 0, f"bonds={bonds}"
            assert len(bonds[0][1]) == 1, f"bonds={bonds}"
            assert bonds[0][1][0][0] == 1, f"bonds={bonds}"
            assert bonds[0][1][0][1] > 0, f"bonds={bonds}"
            assert bonds[1] == (1, []), f"bonds={bonds}"

            break
        except Exception as e:
            last_error = e
            subtensor.wait_for_block(subtensor.block)
            continue
    else:
        pytest.fail(f"Neuron metrics did not reach expected values: {last_error}")


@pytest.mark.asyncio
async def test_incentive_async(async_subtensor, templates, alice_wallet, bob_wallet):
    """
    Test the incentive mechanism and interaction of miners/validators

    Steps:
        1. Register a subnet as Alice and register Bob
        2. Run Alice as validator & Bob as miner. Wait Epoch
        3. Verify miner has correct: trust, rank, consensus, incentive
        4. Verify validator has correct: validator_permit, validator_trust, dividends, stake
    Raises:
        AssertionError: If any of the checks or verifications fail
    """
    alice_sn = TestSubnet(async_subtensor)
    steps = [
        SUDO_SET_ADMIN_FREEZE_WINDOW(alice_wallet, AdminUtils, True, 0),
        REGISTER_SUBNET(alice_wallet),
        SUDO_SET_COMMIT_REVEAL_WEIGHTS_ENABLED(
            alice_wallet, AdminUtils, True, NETUID, False
        ),
        ACTIVATE_SUBNET(alice_wallet),
        REGISTER_NEURON(bob_wallet),
    ]
    await alice_sn.async_execute_steps(steps)

    # Assert two neurons are in network
    assert len(await async_subtensor.neurons.neurons(netuid=alice_sn.netuid)) == 2, (
        "Alice & Bob not registered in the subnet"
    )

    # Stake so Alice has active_stake for Yuma3 dividend calculation
    assert (
        await async_subtensor.staking.add_stake(
            wallet=alice_wallet,
            netuid=alice_sn.netuid,
            hotkey_ss58=alice_wallet.hotkey.ss58_address,
            amount=Balance.from_tao(10_000),
        )
    ).success

    # Wait for the first epoch to pass
    next_epoch_start_block = await async_subtensor.subnets.get_next_epoch_start_block(
        netuid=alice_sn.netuid
    )
    await async_subtensor.wait_for_block(next_epoch_start_block + 5)

    # Get current miner/validator stats
    alice_neuron = (await async_subtensor.neurons.neurons(netuid=alice_sn.netuid))[0]

    assert alice_neuron.validator_permit is True
    assert alice_neuron.dividends == 0
    assert alice_neuron.validator_trust == 0
    assert alice_neuron.incentive == 0
    assert alice_neuron.consensus == 0

    bob_neuron = (await async_subtensor.neurons.neurons(netuid=alice_sn.netuid))[1]

    assert bob_neuron.incentive == 0
    assert bob_neuron.consensus == 0

    # update weights_set_rate_limit for fast-blocks
    tempo = await async_subtensor.subnets.tempo(alice_sn.netuid)
    await alice_sn.async_execute_one(
        SUDO_SET_WEIGHTS_SET_RATE_LIMIT(alice_wallet, AdminUtils, True, NETUID, tempo)
    )

    # max attempts to run miner and validator
    max_attempt = 3
    while True:
        try:
            async with templates.miner(bob_wallet, alice_sn.netuid) as miner:
                await asyncio.wait_for(miner.started.wait(), 60)

                async with templates.validator(
                    alice_wallet, alice_sn.netuid
                ) as validator:
                    # wait for the Validator to process and set_weights
                    await asyncio.wait_for(validator.set_weights.wait(), 60)
            break
        except asyncio.TimeoutError:
            if max_attempt > 0:
                max_attempt -= 1
                continue
            raise

    # wait one tempo (fast block)
    next_epoch_start_block = await async_subtensor.subnets.get_next_epoch_start_block(
        alice_sn.netuid
    )
    await async_subtensor.wait_for_block(next_epoch_start_block + tempo + 1)

    validators = (
        await async_subtensor.metagraphs.get_metagraph_info(
            alice_sn.netuid, selected_indices=[72]
        )
    ).validators

    alice_uid = await async_subtensor.subnets.get_uid_for_hotkey_on_subnet(
        hotkey_ss58=alice_wallet.hotkey.ss58_address, netuid=alice_sn.netuid
    )
    assert validators[alice_uid] == 1

    bob_uid = await async_subtensor.subnets.get_uid_for_hotkey_on_subnet(
        hotkey_ss58=bob_wallet.hotkey.ss58_address, netuid=alice_sn.netuid
    )
    assert validators[bob_uid] == 0

    max_retries = 30
    last_error = None
    for _ in range(max_retries):
        await asyncio.sleep(1)
        try:
            neurons = await async_subtensor.neurons.neurons(netuid=alice_sn.netuid)

            # Get current emissions and validate that Alice has gotten tao
            alice_neuron = neurons[0]

            assert alice_neuron.validator_permit is True
            assert alice_neuron.dividends == 1.0, f"dividends={alice_neuron.dividends}"
            assert alice_neuron.stake.tao > 0, f"stake={alice_neuron.stake.tao}"
            assert alice_neuron.validator_trust > 0.99, (
                f"vtrust={alice_neuron.validator_trust}"
            )
            assert alice_neuron.incentive < 0.5, f"incentive={alice_neuron.incentive}"
            assert alice_neuron.consensus < 0.5, f"consensus={alice_neuron.consensus}"

            bob_neuron = neurons[1]

            assert bob_neuron.incentive > 0.5, f"bob.incentive={bob_neuron.incentive}"
            assert bob_neuron.consensus > 0.5, f"bob.consensus={bob_neuron.consensus}"

            bonds = await async_subtensor.subnets.bonds(alice_sn.netuid)

            assert len(bonds) == 2, f"bonds={bonds}"
            assert bonds[0][0] == 0, f"bonds={bonds}"
            assert len(bonds[0][1]) == 1, f"bonds={bonds}"
            assert bonds[0][1][0][0] == 1, f"bonds={bonds}"
            assert bonds[0][1][0][1] > 0, f"bonds={bonds}"
            assert bonds[1] == (1, []), f"bonds={bonds}"

            break
        except Exception as e:
            last_error = e
            await async_subtensor.wait_for_block(await async_subtensor.block)
            continue
    else:
        pytest.fail(f"Neuron metrics did not reach expected values: {last_error}")
