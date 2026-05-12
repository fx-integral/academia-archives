import { describe, expect, it } from "vitest";

import {
  AdapterRegistry,
  americanToDecimal,
  canonicalBookmaker,
  canonicalToOddsApiMarket,
  canonicalToOddsApiSport,
  decimalToAmerican,
  oddsApiMarketToCanonical,
  oddsApiSportToCanonical,
  TheOddsApiAdapter,
  theOddsApiToCanonical,
  type CanonicalOdds,
  type CanonicalOddsQuery,
  type OddsAdapter,
  type OddsApiResponseEvent,
} from "../canonicalOdds";

// ----------------------------------------------------------------------
// Sport translation
// ----------------------------------------------------------------------

describe("sport translation", () => {
  it("maps every Odds API sport to a canonical key", () => {
    expect(oddsApiSportToCanonical("basketball_nba")).toBe("nba");
    expect(oddsApiSportToCanonical("americanfootball_nfl")).toBe("nfl");
    expect(oddsApiSportToCanonical("baseball_mlb")).toBe("mlb");
    expect(oddsApiSportToCanonical("icehockey_nhl")).toBe("nhl");
    expect(oddsApiSportToCanonical("americanfootball_ncaaf")).toBe("ncaaf");
    expect(oddsApiSportToCanonical("basketball_ncaab")).toBe("ncaab");
    expect(oddsApiSportToCanonical("soccer_epl")).toBe("epl");
    expect(oddsApiSportToCanonical("soccer_usa_mls")).toBe("mls");
  });

  it("falls back to 'other' for unknown sports", () => {
    expect(oddsApiSportToCanonical("cricket_nope")).toBe("other");
    expect(oddsApiSportToCanonical("")).toBe("other");
  });

  it("round-trips canonical sports back to Odds API keys", () => {
    expect(canonicalToOddsApiSport("nba")).toBe("basketball_nba");
    expect(canonicalToOddsApiSport("nfl")).toBe("americanfootball_nfl");
    expect(canonicalToOddsApiSport("epl")).toBe("soccer_epl");
  });
});

// ----------------------------------------------------------------------
// Market translation
// ----------------------------------------------------------------------

describe("market translation", () => {
  it("maps known markets", () => {
    expect(oddsApiMarketToCanonical("h2h")).toBe("moneyline");
    expect(oddsApiMarketToCanonical("spreads")).toBe("spread");
    expect(oddsApiMarketToCanonical("totals")).toBe("total");
  });

  it("unknown markets fall back to 'other'", () => {
    expect(oddsApiMarketToCanonical("playerprops")).toBe("other");
  });

  it("round-trips canonical markets", () => {
    expect(canonicalToOddsApiMarket("moneyline")).toBe("h2h");
    expect(canonicalToOddsApiMarket("spread")).toBe("spreads");
    expect(canonicalToOddsApiMarket("total")).toBe("totals");
  });
});

// ----------------------------------------------------------------------
// American/decimal conversion
// ----------------------------------------------------------------------

describe("americanToDecimal", () => {
  it("converts even money", () => {
    expect(americanToDecimal(100)).toBeCloseTo(2.0, 2);
    expect(americanToDecimal(-100)).toBeCloseTo(2.0, 2);
  });

  it("converts favorites", () => {
    expect(americanToDecimal(-110)).toBeCloseTo(1.909, 2);
    expect(americanToDecimal(-200)).toBeCloseTo(1.5, 2);
  });

  it("converts underdogs", () => {
    expect(americanToDecimal(150)).toBeCloseTo(2.5, 2);
    expect(americanToDecimal(250)).toBeCloseTo(3.5, 2);
  });

  it("returns 0 for 0", () => {
    expect(americanToDecimal(0)).toBe(0);
  });
});

describe("decimalToAmerican", () => {
  it("converts even money", () => {
    expect(decimalToAmerican(2.0)).toBe(100);
  });

  it("converts favorites", () => {
    expect(decimalToAmerican(1.91)).toBeCloseTo(-110, 0);
  });

  it("converts underdogs", () => {
    expect(decimalToAmerican(2.5)).toBe(150);
  });
});

// ----------------------------------------------------------------------
// Bookmaker normalization
// ----------------------------------------------------------------------

describe("canonicalBookmaker", () => {
  it("normalizes known aliases", () => {
    expect(canonicalBookmaker("draftkings")).toBe("DRAFTKINGS");
    expect(canonicalBookmaker("DraftKings")).toBe("DRAFTKINGS");
    expect(canonicalBookmaker("pointsbetus")).toBe("POINTSBET");
    expect(canonicalBookmaker("pointsbet")).toBe("POINTSBET");
  });

  it("uppercases unknown books", () => {
    expect(canonicalBookmaker("newbook")).toBe("NEWBOOK");
  });

  it("returns UNKNOWN for empty input", () => {
    expect(canonicalBookmaker("")).toBe("UNKNOWN");
  });
});

// ----------------------------------------------------------------------
// theOddsApiToCanonical
// ----------------------------------------------------------------------

const SAMPLE_EVENT: OddsApiResponseEvent = {
  id: "evt_001",
  sport_key: "basketball_nba",
  commence_time: "2026-04-12T02:30:00Z",
  home_team: "Los Angeles Lakers",
  away_team: "Boston Celtics",
  bookmakers: [
    {
      key: "draftkings",
      title: "DraftKings",
      last_update: "2026-04-11T20:00:00Z",
      markets: [
        {
          key: "h2h",
          outcomes: [
            { name: "Los Angeles Lakers", price: 1.95 },
            { name: "Boston Celtics", price: 1.85 },
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
            { name: "Over", price: 1.91, point: 220.5 },
            { name: "Under", price: 1.91, point: 220.5 },
          ],
        },
      ],
    },
    {
      key: "fanduel",
      markets: [
        {
          key: "h2h",
          outcomes: [
            { name: "Los Angeles Lakers", price: 2.0 },
            { name: "Boston Celtics", price: 1.83 },
          ],
        },
      ],
    },
  ],
};

describe("theOddsApiToCanonical", () => {
  it("flattens an event into per-bookmaker observations", () => {
    const observations = theOddsApiToCanonical(SAMPLE_EVENT);
    expect(observations.length).toBeGreaterThan(0);
    for (const o of observations) {
      expect(o.event.sport).toBe("nba");
      expect(o.event.homeTeam).toBe("Los Angeles Lakers");
      expect(o.event.awayTeam).toBe("Boston Celtics");
      expect(o.source).toBe("the-odds-api");
      expect(o.fetchedAt).toBeGreaterThan(0);
    }
  });

  it("infers home/away sides for moneyline", () => {
    const obs = theOddsApiToCanonical(SAMPLE_EVENT).filter(
      (o) => o.market === "moneyline",
    );
    const sides = obs.map((o) => o.side).sort();
    expect(sides).toContain("home");
    expect(sides).toContain("away");
  });

  it("preserves spread points as the line field", () => {
    const obs = theOddsApiToCanonical(SAMPLE_EVENT).filter(
      (o) => o.market === "spread",
    );
    expect(obs.find((o) => o.side === "home")?.line).toBe(-3.5);
    expect(obs.find((o) => o.side === "away")?.line).toBe(3.5);
  });

  it("handles totals with over/under sides", () => {
    const obs = theOddsApiToCanonical(SAMPLE_EVENT).filter(
      (o) => o.market === "total",
    );
    expect(obs.length).toBe(2);
    expect(obs.find((o) => o.side === "over")?.line).toBe(220.5);
    expect(obs.find((o) => o.side === "under")?.line).toBe(220.5);
  });

  it("normalizes bookmaker names", () => {
    const obs = theOddsApiToCanonical(SAMPLE_EVENT);
    const books = new Set(obs.map((o) => o.bookmaker));
    expect(books.has("DRAFTKINGS")).toBe(true);
    expect(books.has("FANDUEL")).toBe(true);
  });

  it("uses bookmaker last_update when present", () => {
    const obs = theOddsApiToCanonical(SAMPLE_EVENT);
    const dk = obs.find((o) => o.bookmaker === "DRAFTKINGS");
    expect(dk?.fetchedAt).toBe(Date.parse("2026-04-11T20:00:00Z"));
  });

  it("falls back to fetchedAt when bookmaker has no last_update", () => {
    const obs = theOddsApiToCanonical(SAMPLE_EVENT, { fetchedAt: 99999 });
    const fd = obs.find((o) => o.bookmaker === "FANDUEL");
    expect(fd?.fetchedAt).toBe(99999);
  });

  it("skips unknown markets gracefully", () => {
    const event: OddsApiResponseEvent = {
      ...SAMPLE_EVENT,
      bookmakers: [
        {
          key: "draftkings",
          markets: [
            { key: "playerprops", outcomes: [{ name: "Lebron O 25.5", price: 1.91 }] },
          ],
        },
      ],
    };
    const obs = theOddsApiToCanonical(event);
    expect(obs).toHaveLength(0);
  });

  it("returns empty array for an event with no bookmakers", () => {
    const event: OddsApiResponseEvent = {
      ...SAMPLE_EVENT,
      bookmakers: [],
    };
    expect(theOddsApiToCanonical(event)).toEqual([]);
  });
});

// ----------------------------------------------------------------------
// TheOddsApiAdapter
// ----------------------------------------------------------------------

describe("TheOddsApiAdapter", () => {
  it("supports all known sports", () => {
    const adapter = new TheOddsApiAdapter(async () => []);
    expect(adapter.supportsSport("nba")).toBe(true);
    expect(adapter.supportsSport("epl")).toBe(true);
    expect(adapter.supportsSport("other")).toBe(false);
  });

  it("fetches and translates", async () => {
    const adapter = new TheOddsApiAdapter(async (q: CanonicalOddsQuery) => {
      expect(q.sport).toBe("nba");
      return [SAMPLE_EVENT];
    });
    const obs = await adapter.fetchOdds({ sport: "nba", market: "moneyline" });
    expect(obs.length).toBeGreaterThan(0);
    obs.forEach((o) => {
      expect(o.market).toBe("moneyline");
      expect(o.event.sport).toBe("nba");
    });
  });

  it("filters by bookmaker", async () => {
    const adapter = new TheOddsApiAdapter(async () => [SAMPLE_EVENT]);
    const obs = await adapter.fetchOdds({
      sport: "nba",
      market: "moneyline",
      bookmakers: ["DRAFTKINGS"],
    });
    obs.forEach((o) => {
      expect(o.bookmaker).toBe("DRAFTKINGS");
    });
  });

  it("filters by event id", async () => {
    const adapter = new TheOddsApiAdapter(async () => [
      SAMPLE_EVENT,
      { ...SAMPLE_EVENT, id: "evt_002" },
    ]);
    const obs = await adapter.fetchOdds({
      sport: "nba",
      market: "moneyline",
      eventId: "evt_001",
    });
    obs.forEach((o) => {
      expect(o.event.id).toBe("evt_001");
    });
  });

  it("propagates fetcher errors", async () => {
    const adapter = new TheOddsApiAdapter(async () => {
      throw new Error("upstream down");
    });
    await expect(
      adapter.fetchOdds({ sport: "nba", market: "moneyline" }),
    ).rejects.toThrow(/upstream down/);
  });
});

// ----------------------------------------------------------------------
// AdapterRegistry
// ----------------------------------------------------------------------

class StubAdapter implements OddsAdapter {
  constructor(public source: string, private supportedSports: string[]) {}
  supportsSport(sport: string): boolean {
    return this.supportedSports.includes(sport);
  }
  async fetchOdds(): Promise<CanonicalOdds[]> {
    return [];
  }
}

describe("AdapterRegistry", () => {
  it("registers and retrieves adapters", () => {
    const reg = new AdapterRegistry();
    const a = new StubAdapter("a", ["nba"]);
    reg.register(a);
    expect(reg.get("a")).toBe(a);
    expect(reg.all()).toHaveLength(1);
  });

  it("rejects duplicate registration", () => {
    const reg = new AdapterRegistry();
    reg.register(new StubAdapter("a", ["nba"]));
    expect(() => reg.register(new StubAdapter("a", ["nfl"]))).toThrow(
      /already registered/,
    );
  });

  it("filters supporting adapters by sport", () => {
    const reg = new AdapterRegistry();
    reg.register(new StubAdapter("nba-only", ["nba"]));
    reg.register(new StubAdapter("nfl-only", ["nfl"]));
    reg.register(new StubAdapter("multi", ["nba", "nfl"]));

    const nba = reg.supportingSport("nba" as never).map((a) => a.source);
    expect(nba).toEqual(expect.arrayContaining(["nba-only", "multi"]));
    expect(nba).not.toContain("nfl-only");
  });
});
