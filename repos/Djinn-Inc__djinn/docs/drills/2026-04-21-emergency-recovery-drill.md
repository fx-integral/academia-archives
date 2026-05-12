# Emergency Recovery Drill — 2026-04-21

**Runbook:** `docs/runbook-emergency-recovery.md`
**Test file:** `contracts/test/recovery/EmergencyRecovery.t.sol`
**Command:** `forge test --match-contract EmergencyRecovery -vv`

## Result

```
Ran 12 tests for test/recovery/EmergencyRecovery.t.sol:EmergencyRecoveryTest
[PASS] test_emergency_pause_blocks_audit_settlement
[PASS] test_emergency_pause_blocks_purchases_and_withdrawals
[PASS] test_forceSettle_full_batch_damages_exceed_fees_overflow_to_credits
[PASS] test_forceSettle_full_batch_negative_score_slashes_usdc_to_idiot
[PASS] test_forceSettle_genius_claims_fees_after_delay
[PASS] test_forceSettle_positive_score_fees_claimable_by_genius
[PASS] test_forceSettle_small_batch_negative_score_credits_only_no_usdc_slash
[PASS] test_parallel_unpause_within_single_timelock_window
[PASS] test_pauser_cannot_unpause_only_owner_can
[PASS] test_timelocked_forceSettle_cannot_be_replayed
[PASS] test_timelocked_forceSettle_full_governance_path
[PASS] test_timelocked_unpause_restores_all_operations
Suite result: ok. 12 passed; 0 failed; 0 skipped
```

## Scenarios covered

| Scenario | Test |
|---|---|
| Positive score: all fees claimable by genius | `test_forceSettle_positive_score_fees_claimable_by_genius` |
| Small batch (<10): negative score mints credits only, no USDC slash | `test_forceSettle_small_batch_negative_score_credits_only_no_usdc_slash` |
| Full batch (10+): trancheA USDC slash → idiot, trancheB → credits | `test_forceSettle_full_batch_negative_score_slashes_usdc_to_idiot` |
| Full batch: damages exceed fees → overflow as credits | `test_forceSettle_full_batch_damages_exceed_fees_overflow_to_credits` |
| Genius claims fees after FEE_CLAIM_DELAY (96h) | `test_forceSettle_genius_claims_fees_after_delay` |
| Governance path: timelock schedule → warp → execute | `test_timelocked_forceSettle_full_governance_path` |
| Operation replay protection | `test_timelocked_forceSettle_cannot_be_replayed` |
| Pause blocks purchases + withdrawals | `test_emergency_pause_blocks_purchases_and_withdrawals` |
| Pause blocks audit settlement | `test_emergency_pause_blocks_audit_settlement` |
| Timelocked unpause restores operations | `test_timelocked_unpause_restores_all_operations` |
| Pauser cannot unpause (fire-only authority) | `test_pauser_cannot_unpause_only_owner_can` |
| Parallel unpause stays within one timelock window | `test_parallel_unpause_within_single_timelock_window` |

## Key economic invariants verified

- `trancheA = min(damages, totalUsdcFeesPaid)` — USDC flows from genius collateral to idiot
- `trancheB = max(0, damages - totalUsdcFeesPaid)` — overflow as Djinn Credits to idiot
- `netClaimable = totalUsdcFeesPaid - trancheA` — genius can claim remainder after delay
- Early-exit path (batch < 10): only credits, no collateral slash
- Protocol fee always slashed from collateral to treasury regardless of score sign
