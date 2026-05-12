-- Enable WAL mode for better write concurrency
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS miners (
    hotkey TEXT PRIMARY KEY,
    uid INTEGER,
    last_signature TEXT,
    last_message TEXT,
    first_seen_ts TEXT,
    last_seen_ts TEXT,
    axon_ip TEXT
);

CREATE TABLE IF NOT EXISTS performance_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hotkey TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    
    total_volume_usd REAL,
    weighted_volume REAL,
    profit REAL,
    trade_count INTEGER,
    realized_profit_usd REAL,
    unrealized_profit_usd REAL,
    win_rate REAL,
    total_fees_paid_usd REAL,
    open_positions_count INTEGER,
    referral_count INTEGER,
    referral_volume REAL,

    volume_delta REAL,
    profit_delta REAL,
    trade_delta INTEGER,
    activity_score REAL,

    FOREIGN KEY(hotkey) REFERENCES miners(hotkey)
);

CREATE INDEX IF NOT EXISTS idx_perf_hotkey_ts
    ON performance_snapshots(hotkey, timestamp);

CREATE TABLE IF NOT EXISTS scoring_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    hotkey TEXT NOT NULL,
    score REAL,
    reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_scoring_hotkey_ts
    ON scoring_runs(hotkey, ts DESC);

CREATE TABLE IF NOT EXISTS user_hotkey_bindings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,                     
    hotkey TEXT NOT NULL UNIQUE,
    first_seen_at TEXT NOT NULL, 
    last_updated_at TEXT NOT NULL,
    previous_user_id TEXT,
    
    FOREIGN KEY(hotkey) REFERENCES miners(hotkey)
);

CREATE INDEX IF NOT EXISTS idx_user_hotkey_bindings_user_id
    ON user_hotkey_bindings(user_id);

CREATE INDEX IF NOT EXISTS idx_user_hotkey_bindings_hotkey
    ON user_hotkey_bindings(hotkey);


