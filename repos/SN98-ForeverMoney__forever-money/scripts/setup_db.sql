-- SN98 ForeverMoney Database Schema
-- This script sets up the pool_events table structure

-- Pool events table
CREATE TABLE IF NOT EXISTS pool_events (
    id BIGSERIAL PRIMARY KEY,
    block_number BIGINT NOT NULL,
    transaction_hash VARCHAR(66) NOT NULL,
    log_index INTEGER NOT NULL,
    pool_address VARCHAR(42) NOT NULL,
    event_type VARCHAR(32) NOT NULL,
    event_data JSONB NOT NULL,
    timestamp BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(transaction_hash, log_index)
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_pool_events_pool_address
    ON pool_events(pool_address);

CREATE INDEX IF NOT EXISTS idx_pool_events_block_number
    ON pool_events(block_number);

CREATE INDEX IF NOT EXISTS idx_pool_events_event_type
    ON pool_events(event_type);

CREATE INDEX IF NOT EXISTS idx_pool_events_pool_block
    ON pool_events(pool_address, block_number);

CREATE INDEX IF NOT EXISTS idx_pool_events_timestamp
    ON pool_events(timestamp);

-- JSONB indexes for common queries
CREATE INDEX IF NOT EXISTS idx_pool_events_event_data
    ON pool_events USING GIN(event_data);

-- Optional: owner_address column for tracking vault fees
ALTER TABLE pool_events
    ADD COLUMN IF NOT EXISTS owner_address VARCHAR(42);

CREATE INDEX IF NOT EXISTS idx_pool_events_owner
    ON pool_events(owner_address)
    WHERE owner_address IS NOT NULL;

-- Create read-only user for miners/validators
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_user WHERE usename = 'readonly_user') THEN
        CREATE USER readonly_user WITH PASSWORD 'change_me_in_production';
    END IF;
END
$$;

-- Grant read-only permissions
GRANT CONNECT ON DATABASE sn98_pool_data TO readonly_user;
GRANT USAGE ON SCHEMA public TO readonly_user;
GRANT SELECT ON pool_events TO readonly_user;

-- Example: Insert sample swap event
-- INSERT INTO pool_events (
--     block_number,
--     transaction_hash,
--     log_index,
--     pool_address,
--     event_type,
--     event_data,
--     timestamp
-- ) VALUES (
--     12345678,
--     '0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef',
--     0,
--     '0x0000000000000000000000000000000000000000',
--     'swap',
--     '{"amount0": "-1000000000000000000", "amount1": "2500000000", "sqrtPriceX96": "1234567890123456789012345", "liquidity": "1000000000000000000", "tick": -9200}'::jsonb,
--     1706745600
-- );

COMMENT ON TABLE pool_events IS 'All Aerodrome pool events for SN98 strategy backtesting';
COMMENT ON COLUMN pool_events.event_type IS 'Event type: swap, mint, burn, collect, etc.';
COMMENT ON COLUMN pool_events.event_data IS 'JSONB data containing event-specific fields';
COMMENT ON COLUMN pool_events.owner_address IS 'Address of position owner (for tracking miner vaults)';
