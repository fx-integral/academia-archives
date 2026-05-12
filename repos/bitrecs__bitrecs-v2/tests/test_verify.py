import os
import time
from dotenv import load_dotenv
load_dotenv()
from utils.verify import (
    validate_signed_timestamp,
    verify_submission_signature,
    create_transport_signature,
    verify_transport_signature,
    verify_timestamp
)
from models.miner_submission import MinerSubmission
from bittensor_wallet import Wallet
from version import __version__

MINER_WALLET_NAME = os.getenv("MINER_WALLET_NAME", None)
MINER_WALLET_HOTKEY_NAME = os.getenv("MINER_WALLET_HOTKEY_NAME", None)
MINER_WALLET_HOTKEY = os.getenv("MINER_WALLET_HOTKEY", None)
if not any([MINER_WALLET_NAME, MINER_WALLET_HOTKEY]):
    raise ValueError(f"MINER_WALLET_NAME, MINER_WALLET_HOTKEY_NAME, and MINER_WALLET_HOTKEY not found in environment")

wallet = Wallet(
    name=MINER_WALLET_NAME,
    hotkey=MINER_WALLET_HOTKEY_NAME
)

def test_validate_signed_timestamp():
    result_invalid = validate_signed_timestamp(1234567890, "dummy_signed", MINER_WALLET_HOTKEY)
    assert isinstance(result_invalid, bool)
    assert result_invalid == False
    
    timestamp = 1234567890
    signed_timestamp = wallet.hotkey.sign(str(timestamp).encode('utf-8')).hex()
    result_valid = validate_signed_timestamp(timestamp, signed_timestamp, wallet.hotkey.ss58_address)
    assert result_valid == True

def test_verify_submission_signature():
    preamble = f"2023-01-01T00:00:00Z:testuser:12345:{wallet.hotkey.ss58_address}"
    signature = wallet.hotkey.sign(preamble.encode('utf-8')).hex()
    submission = MinerSubmission(
        created_at="2023-01-01T00:00:00Z",
        github_account="testuser",
        gist_id="12345",
        hotkey=MINER_WALLET_HOTKEY,
        signature=signature
    )    
    result = verify_submission_signature(submission)
    assert result == True

def test_create_transport_signature():
    submission = MinerSubmission(
        created_at="2023-01-01T00:00:00Z",
        github_account="testuser",
        gist_id="12345",
        hotkey=MINER_WALLET_HOTKEY,
        signature="dummy_signature"
    )
    sig, t_nonce = create_transport_signature(wallet, submission, "nonce", 1234567890)
    assert isinstance(sig, str)
    assert isinstance(t_nonce, str)

def test_verify_transport_signature():
    submission = MinerSubmission(
        created_at="2023-01-01T00:00:00Z",
        github_account="testuser",
        gist_id="12345",
        hotkey=MINER_WALLET_HOTKEY,
        signature="dummy_signature"
    )
    nonce = "nonce"
    t_nonce = "t_nonce"
    ts = 1234567890
    version = __version__
    preamble = f"{submission.created_at}:{submission.github_account}:{submission.gist_id}:{submission.hotkey}:{nonce}:{t_nonce}:{version}:{ts}"
    preamble_bytes = preamble.encode('utf-8')
    transport_signature = wallet.hotkey.sign(preamble_bytes).hex()
    result = verify_transport_signature(submission, transport_signature, nonce, t_nonce, ts)
    assert result == True

def test_verify_transport__broken_signature():
    submission = MinerSubmission(
        created_at="2023-01-01T00:00:00Z",
        github_account="testuser",
        gist_id="12345",
        hotkey=MINER_WALLET_HOTKEY,
        signature="dummy_signature"
    )
    nonce = "nonce"
    t_nonce = "t_nonce"
    ts = 1234567890
    version = __version__
    preamble = f"{submission.created_at}:{submission.github_account}:{submission.gist_id}:{submission.hotkey}:{nonce}:{t_nonce}:{version}:1234567891"
    preamble_bytes = preamble.encode('utf-8')
    transport_signature = wallet.hotkey.sign(preamble_bytes).hex()
    result = verify_transport_signature(submission, transport_signature, nonce, t_nonce, ts)
    assert result == False

def test_verify_timestamp():
    current = int(time.time())
    assert verify_timestamp(str(current)) == True
    assert verify_timestamp("invalid") == False
    assert verify_timestamp(str(current - 400)) == False