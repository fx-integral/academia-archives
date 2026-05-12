import os
import pytest
from flaky import flaky
import bittensor as bt
from bitsec.utils.data import create_challenge, PredictionResponse, verify_solidity_compilation

################################################################################
# NOTE: Most tests require Forge, see miner_and_validator_setup.md to install it
################################################################################

SPEND_MONEY = os.environ.get("SPEND_MONEY", False)
if SPEND_MONEY:
    bt.logging.set_debug()

@flaky(max_runs=7)
def test_create_challenge_non_vulnerable():
    if not SPEND_MONEY:
        pytest.skip("Skipping test because SPEND_MONEY is False")

    """Test creating a non-vulnerable challenge."""
    code, expected_response = create_challenge(vulnerable=False)
    
    # Basic type checks
    assert isinstance(code, str), f"Expected str, got {type(code)}"
    assert isinstance(expected_response, PredictionResponse), f"Expected PredictionResponse, got {type(expected_response)}"
    
    # Code should not be empty
    assert len(code) > 0, f"Expected code to not be empty, got '{code}'"
    # assert verify_solidity_compilation(code), f"Code does not compile: {code}"
    
    # Response should match expectations for non-vulnerable code
    assert not expected_response.prediction, f"Expected response should be non-vulnerable, got {expected_response}. Code: {code}"  # True means vulnerable
    assert len(expected_response.vulnerabilities) == 0, f"Expected response should have no vulnerabilities, got {expected_response}. Code: {code}"

@flaky(max_runs=7)
def test_create_challenge_vulnerable():
    """Test creating a vulnerable challenge."""
    if not SPEND_MONEY:
        pytest.skip("Skipping test because SPEND_MONEY is False")

    code, expected_response = create_challenge(vulnerable=True)
    
    # Basic type checks
    assert isinstance(code, str), f"Expected str, got {type(code)}"
    assert isinstance(expected_response, PredictionResponse), f"Expected PredictionResponse, got {type(expected_response)}"
    
    # Code should not be empty
    assert len(code) > 0, f"Expected code to not be empty, got '{code}'"
    # assert verify_solidity_compilation(code), f"Code does not compile: {code}"

    # Response should match expectations for vulnerable code
    assert expected_response.prediction, f"Expected response should be vulnerable, got {expected_response}. Code: {code}"  # True means vulnerable
    assert len(expected_response.vulnerabilities) > 0, f"Expected response should have vulnerabilities, got {expected_response}. Code: {code}"

@flaky(max_runs=7)
def test_create_challenge_return_type():
    """Test that create_challenge returns the correct type."""
    if not SPEND_MONEY:
        pytest.skip("Skipping test because SPEND_MONEY is False")
    
    result = create_challenge(vulnerable=False)
    assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
    assert len(result) == 2, f"Expected tuple of length 2, got {len(result)}"
    assert isinstance(result[0], str), f"Expected str, got {type(result[0])}"  # code
    assert isinstance(result[1], PredictionResponse), f"Expected PredictionResponse, got {type(result[1])}"  # response

@flaky(max_runs=7)
def test_create_challenge_different_outputs():
    """Test that create_challenge generates different challenges."""
    if not SPEND_MONEY:
        pytest.skip("Skipping test because SPEND_MONEY is False")
    
    code1, response1 = create_challenge(vulnerable=False)
    assert not response1.prediction, f"Expected R1 response should not be vulnerable: {response1}"
    # assert verify_solidity_compilation(code1), f"Code does not compile: {code1}"
    
    code2, response2 = create_challenge(vulnerable=False)

    # Save some money by just retrying code2 until it's different from code1
    i = 0
    while code1 == code2:
        bt.logging.info(f"test_create_challenge_different_outputs: Generated same code sample {i} times in a row. Retrying...")
        i += 1
        if i > 10:
            raise ValueError("Failed to generate different code samples")

        code2, response2 = create_challenge(vulnerable=False)
        # if not verify_solidity_compilation(code2):
        #     code2 = code1  # Retry if the code doesn't compile
    
    assert code1 != code2, f"Code samples should be different\nC1: {code1}\nC2: {code2}"
    
    # But they should maintain the same vulnerability status
    assert response1.prediction == response2.prediction, f"Expected R1 and R2 responses to have the same vulnerability status: {response1} != {response2}"


def test_verify_solidity_quality_checks():
    """Test that verify_solidity_compilation correctly identifies compilable code."""

    # These tests only check basic syntax and should work without Forge
    no_license = """
    pragma solidity ^0.8.0;
    contract Test {
        function test() public pure returns (uint256) { return 1; }
    }
    """
    assert not verify_solidity_compilation(no_license), f"Code without license should not pass validation: {no_license}"

    no_pragma = """
    // SPDX-License-Identifier: MIT
    contract Test {
        function test() public pure returns (uint256) { return 1; }
    }
    """
    assert not verify_solidity_compilation(no_pragma), f"Code without pragma should not pass validation: {no_pragma}"
    
def test_verify_solidity_compilation_with_forge():
    ############################################################################
    # These tests require Forge, see miner_and_validator_setup.md to install it
    ############################################################################

    valid_code = """
    // SPDX-License-Identifier: MIT
    pragma solidity ^0.8.0;
    contract Test {
        function test() public pure returns (uint256) { return 1; }
    }
    """
    assert verify_solidity_compilation(valid_code), f"Valid code should compile: {valid_code}"
    print(f"Valid code did compile")
    
    invalid_code = """
    // SPDX-License-Identifier: MIT
    pragma solidity ^0.8.0;
    contract Test 
        function test public pure returns (uint256) { return 1; }
    """
    assert not verify_solidity_compilation(invalid_code), f"Invalid code should not compile: {invalid_code}"
    print(f"Invalid code correctly rejected")