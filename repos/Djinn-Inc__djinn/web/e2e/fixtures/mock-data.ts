/**
 * Mock data for E2E tests.
 * Used with page.route() to intercept API calls.
 */

// Anvil account #0 — matches the mock connector in providers.tsx
export const TEST_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266";

export const MOCK_ODDS_EVENTS = [
  {
    id: "e2e-event-nba-1",
    sport_key: "basketball_nba",
    sport_title: "NBA",
    commence_time: new Date(Date.now() + 86400000).toISOString(),
    home_team: "Los Angeles Lakers",
    away_team: "Boston Celtics",
    bookmakers: [
      {
        key: "fanduel",
        title: "FanDuel",
        markets: [
          {
            key: "h2h",
            outcomes: [
              { name: "Los Angeles Lakers", price: 1.85 },
              { name: "Boston Celtics", price: 2.0 },
            ],
          },
          {
            key: "spreads",
            outcomes: [
              { name: "Los Angeles Lakers", price: 1.91, point: -3.5 },
              { name: "Boston Celtics", price: 1.91, point: 3.5 },
            ],
          },
          {
            key: "totals",
            outcomes: [
              { name: "Over", price: 1.91, point: 225.5 },
              { name: "Under", price: 1.91, point: 225.5 },
            ],
          },
        ],
      },
      {
        key: "draftkings",
        title: "DraftKings",
        markets: [
          {
            key: "h2h",
            outcomes: [
              { name: "Los Angeles Lakers", price: 1.83 },
              { name: "Boston Celtics", price: 2.05 },
            ],
          },
          {
            key: "spreads",
            outcomes: [
              { name: "Los Angeles Lakers", price: 1.87, point: -3.5 },
              { name: "Boston Celtics", price: 1.95, point: 3.5 },
            ],
          },
        ],
      },
      {
        key: "betmgm",
        title: "BetMGM",
        markets: [
          {
            key: "h2h",
            outcomes: [
              { name: "Los Angeles Lakers", price: 1.87 },
              { name: "Boston Celtics", price: 1.95 },
            ],
          },
          {
            key: "spreads",
            outcomes: [
              { name: "Los Angeles Lakers", price: 1.91, point: -3.0 },
              { name: "Boston Celtics", price: 1.91, point: 3.0 },
            ],
          },
        ],
      },
    ],
  },
  {
    id: "e2e-event-nba-2",
    sport_key: "basketball_nba",
    sport_title: "NBA",
    commence_time: new Date(Date.now() + 172800000).toISOString(),
    home_team: "Golden State Warriors",
    away_team: "Miami Heat",
    bookmakers: [
      {
        key: "fanduel",
        title: "FanDuel",
        markets: [
          {
            key: "h2h",
            outcomes: [
              { name: "Golden State Warriors", price: 1.5 },
              { name: "Miami Heat", price: 2.6 },
            ],
          },
          {
            key: "spreads",
            outcomes: [
              { name: "Golden State Warriors", price: 1.91, point: -7.5 },
              { name: "Miami Heat", price: 1.91, point: 7.5 },
            ],
          },
        ],
      },
    ],
  },
];

export const MOCK_NFL_EVENTS = [
  {
    id: "e2e-event-nfl-1",
    sport_key: "americanfootball_nfl",
    sport_title: "NFL",
    commence_time: new Date(Date.now() + 86400000).toISOString(),
    home_team: "Kansas City Chiefs",
    away_team: "Buffalo Bills",
    bookmakers: [
      {
        key: "fanduel",
        title: "FanDuel",
        markets: [
          {
            key: "h2h",
            outcomes: [
              { name: "Kansas City Chiefs", price: 1.67 },
              { name: "Buffalo Bills", price: 2.2 },
            ],
          },
          {
            key: "spreads",
            outcomes: [
              { name: "Kansas City Chiefs", price: 1.91, point: -3.5 },
              { name: "Buffalo Bills", price: 1.91, point: 3.5 },
            ],
          },
        ],
      },
    ],
  },
];

/** ABI-encoded uint256(0) — used as default mock for eth_call */
export const ZERO_ENCODED = "0x" + "0".repeat(64);

/** ABI-encoded uint256(1000000000) — 1000 USDC (6 decimals) */
export const USDC_1000_ENCODED =
  "0x" + (1000_000000n).toString(16).padStart(64, "0");

/** Mock transaction hash */
export const MOCK_TX_HASH =
  "0xabababababababababababababababababababababababababababababababababab";
