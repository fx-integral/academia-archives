# BitKoop

<img src="./docs/assets/logo.png" alt="BitKoop Logo" width="50%">

## Guides
- **Mining:** [docs/mining.md](https://github.com/BitKoopLabs/BitKoop/blob/main/docs/mining.md)  
- **Validating:** [docs/validating.md](https://github.com/BitKoopLabs/BitKoop/blob/main/docs/validating.md)

## Overview – What is BitKoop?
BitKoop is a decentralized, community-powered coupon platform that turns **working discount codes** into a reliable, verifiable commodity.

Shoppers can discover **verified coupons** for a wide variety of products across multiple online stores — without wasting time on expired or fake offers.

Unlike traditional coupon sites, BitKoop’s discount codes are sourced directly from its network of incentivized **miners** — community members who actively hunt for and submit valid discounts. Every coupon is **tested, verified, and scored** by independent validators before appearing on the platform.

These miners earn rewards for every working code they contribute, creating a self-sustaining ecosystem where the more people participate, the more valuable the commodity — verified discount codes — becomes. By decentralizing the sourcing and standardizing the quality, BitKoop guarantees a constant flow of fresh, trustworthy offers while giving contributors a direct stake in the platform’s success.

---

## The Problem
Finding a working coupon is often:
- **Frustrating:** Most codes are expired, fake, or misleading.
- **Time-consuming:** Shoppers waste time testing multiple codes at checkout.
- **Non-transparent:** Traditional coupon sites don’t tell you if a code works until you try it.
- **Exploitative:** Many platforms profit from your clicks even when no real discount exists.

---

## The BitKoop Solution
We reimagine the coupon economy with **trust and transparency by default**:

- **Community-sourced**: All discount codes come from incentivized **miners** who actively find and submit working offers.
- **Real-time validation**: A network of independent validators tests and scores every code, ensuring only working discounts reach the platform.
- **Performance-based rewards**: Miners and validators earn based on the value and accuracy of their contributions, creating a self-policing ecosystem.

**With BitKoop, if you see it — it works.** No tricks, no wasted clicks.

---

## The Market Opportunity
The online coupon and deals industry is a multi-billion-dollar market. Traditional coupon platforms like RetailMeNot, Honey, and Groupon collectively generate hundreds of millions in annual revenue — primarily through affiliate commissions and advertising. For example, Honey was acquired by PayPal in 2020 for $4 billion, largely because of its ability to drive purchase decisions and capture affiliate revenue at scale.

Yet, despite the massive earnings, these platforms suffer from low trust and poor user experience — with high bounce rates due to non-working codes and opaque referral practices. This leaves a significant gap for a transparent, performance-driven alternative.

BitKoop is positioned to step directly into this market, leveraging the same proven revenue model (affiliate commissions from partner stores), but with a trust-first approach powered by decentralization and validation. Every verified code not only improves user satisfaction but also increases the likelihood of conversions — translating into higher revenue per user.

With the coupon industry projected to continue growing alongside global e-commerce, BitKoop is targeting a share of a market worth tens of billions annually, while differentiating itself through community incentives, transparency, and measurable value creation.

We aim to capture market share by delivering **verified value** in a space dominated by unreliable coupon sites.

---

## How BitKoop Works
- **Miners** – Find and submit working coupons.
- **Validators** – Verify coupons submitted by miners and score them accordingly.

---

## Mining Made Simple
- **VPS required** – Run the BitKoop miner server on a VPS for continuous operation.
- **Beginner friendly** – One of the easiest subnets to mine.

---

## Scoring Formula
- **Points**:
  - Each valid coupon: **100 points**
- **Combined score** = `coupon_weight * coupon_points`
- **Normalization**: `min(1.0, round(points / MAX, 4))`

---

## Coupon Validation Lifecycle
- **Initial state**: On submission (or inbound sync), coupons start as PENDING after base checks (submission window, site exists and is active, per-miner/site limits).
- **Periodic validation of PENDING**: A background task validates PENDING coupons per site using the active validator (Node/Playwright in production, Python fallback otherwise). Success sets status to VALID; failure sets to INVALID. `last_checked_at` is updated.
- **Periodic revalidation of VALIDs**: Another task rechecks VALID coupons whose `last_checked_at` is older than ~1 day, potentially flipping them to INVALID if they stop working.
- **Error/config handling**: If a site is missing configuration or is inactive, coupons are deferred and kept PENDING; unexpected validator errors/timeouts mark affected coupons INVALID.
- **Manual recheck**: Miners can request recheck of INVALID coupons after a cooldown (`recheck_interval`), which moves them back to PENDING for the next cycle.
- **Scheduler**: The worker loop in `subnet_validator/tasks/validate_coupons.py` runs periodically (default every minute), executing both the PENDING and stale VALID rechecks.

---

## Roadmap
**Phase 1**
- Launch BitKoop subnet
- [Release BitKoop CLI](https://github.com/BitKoopLabs/BitKoop-CLI)

**Phase 2**
- Public website launch
- Web-based miner registration (Subnet 16)
- Web-based coupon submission
- Partnerships with affiliate networks (Awin, Impact)

**Phase 3**
- New miner task: Build/maintain website configs
- Onboard hundreds of e-commerce stores across global markets

---

## Why Join as a Miner?
- Earn rewards for finding working coupons
- Help build the most trustworthy coupon database in the world
- Contribute to a transparent, decentralized system
- Mine from anywhere — no special hardware or coding skills needed
