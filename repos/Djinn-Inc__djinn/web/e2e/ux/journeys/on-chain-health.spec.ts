import { test, expect } from "@playwright/test";
import { ethers } from "ethers";

// Default targets are the live Base Sepolia proxies so this spec stays green
// on the normal cron. Override via env vars when running against a staging
// fork (see scripts/staging-e2e.sh). All 9 addresses are individually
// overridable — Deploy.s.sol emits fresh ones each fork deploy.
// Default to publicnode — sepolia.base.org's public RPC has had recurring
// 502s during the e2e cron window (iter-97 false-positive on
// "proxy-owner drift" was a pure RPC outage, no actual drift). Override
// via env vars when running against a staging fork.
const RPC_URL =
  process.env.ON_CHAIN_HEALTH_RPC ??
  process.env.BASE_SEPOLIA_RPC ??
  "https://base-sepolia-rpc.publicnode.com";

const TIMELOCK =
  process.env.ON_CHAIN_HEALTH_TIMELOCK ??
  "0x37f41EFfa8492022afF48B9Ef725008963F14f79";

const PROXIES: Array<{ name: string; addr: string }> = [
  {
    name: "SignalCommitment",
    addr:
      process.env.ON_CHAIN_HEALTH_SIGNAL_COMMITMENT ??
      "0x4712479Ba57c9ED40405607b2B18967B359209C0",
  },
  {
    name: "Escrow",
    addr:
      process.env.ON_CHAIN_HEALTH_ESCROW ??
      "0xb43BA175a6784973eB3825acF801Cd7920ac692a",
  },
  {
    name: "Collateral",
    addr:
      process.env.ON_CHAIN_HEALTH_COLLATERAL ??
      "0x71F0a8c6BBFc4C83c5203807fAdd305B0C0F4C88",
  },
  {
    name: "Account",
    addr:
      process.env.ON_CHAIN_HEALTH_ACCOUNT ??
      "0x4546354Dd32a613B76Abf530F81c8359e7cE440B",
  },
  {
    name: "Audit",
    addr:
      process.env.ON_CHAIN_HEALTH_AUDIT ??
      "0xCa7e642FE31BA83a7a857644E8894c1B93a2a44E",
  },
  {
    name: "CreditLedger",
    addr:
      process.env.ON_CHAIN_HEALTH_CREDIT_LEDGER ??
      "0xA65296cd11B65629641499024AD905FAcAB64C3E",
  },
  {
    name: "OutcomeVoting",
    addr:
      process.env.ON_CHAIN_HEALTH_OUTCOME_VOTING ??
      "0xAD534f4CAB13707BD4d65e4EF086A455e6A643e5",
  },
];

const IFACE = new ethers.Interface([
  "function owner() view returns (address)",
]);

test.describe("On-Chain Health Journey", () => {
  test.describe.configure({ mode: "serial" });

  test("every proxy is owned by the canonical TimelockController", async () => {
    const provider = new ethers.JsonRpcProvider(RPC_URL);
    const mismatches: string[] = [];

    for (const proxy of PROXIES) {
      try {
        const data = IFACE.encodeFunctionData("owner");
        const raw = await provider.call({ to: proxy.addr, data });
        const [owner] = IFACE.decodeFunctionResult("owner", raw);
        if ((owner as string).toLowerCase() !== TIMELOCK.toLowerCase()) {
          mismatches.push(`${proxy.name}.owner()=${owner} (want ${TIMELOCK})`);
        }
      } catch (err) {
        mismatches.push(`${proxy.name}.owner() threw: ${String(err).slice(0, 120)}`);
      }
    }

    expect(mismatches, `proxy-owner drift: ${mismatches.join(" | ")}`).toHaveLength(0);
  });

  test("every proxy has non-empty bytecode (not uninitialized)", async () => {
    const provider = new ethers.JsonRpcProvider(RPC_URL);
    const empties: string[] = [];

    for (const proxy of PROXIES) {
      const code = await provider.getCode(proxy.addr);
      if (!code || code === "0x" || code.length < 4) {
        empties.push(`${proxy.name} (${proxy.addr}) has no deployed bytecode`);
      }
    }

    expect(empties, `empty-bytecode proxies: ${empties.join(" | ")}`).toHaveLength(0);
  });
});
