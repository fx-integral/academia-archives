#!/usr/bin/env node
/**
 * test-payment.mjs – End-to-end DRAIN payment test
 *
 * 1. Fetches approved providers from the marketplace API
 * 2. For each provider: opens a DRAIN channel, signs an EIP-712 voucher,
 *    sends one chat request and logs the result.
 *
 * Usage:
 *   node scripts/test-payment.mjs                    # test all providers
 *   node scripts/test-payment.mjs --provider <name>  # test one provider
 *   node scripts/test-payment.mjs --dry-run          # just list providers
 *
 * Required env (or defaults):
 *   POLYGON_RPC_URL   – Polygon JSON-RPC (default: https://polygon-rpc.com)
 *   AGENT_PRIVATE_KEY – private key of the agent wallet (falls back to wallets/polygon/agent.json)
 *   MARKETPLACE_URL   – marketplace base URL (default: https://drain-marketplace-production.up.railway.app)
 */

import { ethers } from 'ethers';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// ============================================================================
// CONFIG
// ============================================================================

const DRAIN_CONTRACT = '0x1C1918C99b6DcE977392E4131C91654d8aB71e64';
const USDC_ADDRESS   = '0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359';
const CHAIN_ID       = 137;

const RPC_URL        = process.env.POLYGON_RPC_URL || 'https://polygon-rpc.com';
const MARKETPLACE    = process.env.MARKETPLACE_URL  || 'https://handshake58.com';

// DRAIN channel parameters
const DEPOSIT_USDC   = '0.10';          // $0.10 per channel
const DURATION_SEC   = 86400;           // 24 hours
const VOUCHER_USDC   = '0.01';          // $0.01 per request

// ============================================================================
// ABI fragments (only what we need)
// ============================================================================

const SESSION_FEE   = 10000n;           // $0.01 USDC per channel

const USDC_ABI = [
  'function approve(address spender, uint256 amount) returns (bool)',
  'function allowance(address owner, address spender) view returns (uint256)',
  'function balanceOf(address account) view returns (uint256)',
  'function transfer(address to, uint256 amount) returns (bool)',
];

const DRAIN_ABI = [
  'function open(address provider, uint256 amount, uint256 duration) returns (bytes32)',
  'function close(bytes32 channelId)',
  'function getChannel(bytes32 channelId) view returns (tuple(address consumer, address provider, uint256 deposit, uint256 claimed, uint256 expiry))',
  'event ChannelOpened(bytes32 indexed channelId, address indexed consumer, address indexed provider, uint256 deposit, uint256 expiry)',
];

// EIP-712 Domain & Types
const EIP712_DOMAIN = {
  name: 'DrainChannel',
  version: '1',
  chainId: CHAIN_ID,
  verifyingContract: DRAIN_CONTRACT,
};

const VOUCHER_TYPES = {
  Voucher: [
    { name: 'channelId', type: 'bytes32' },
    { name: 'amount',    type: 'uint256' },
    { name: 'nonce',     type: 'uint256' },
  ],
};

// ============================================================================
// HELPERS
// ============================================================================

function parseUSDC(usdString) {
  const [whole, frac = ''] = usdString.split('.');
  return BigInt(whole) * 1_000_000n + BigInt(frac.padEnd(6, '0').slice(0, 6));
}

function formatUSDC(wei) {
  const s = wei.toString().padStart(7, '0');
  return '$' + s.slice(0, -6) + '.' + s.slice(-6);
}

function loadAgentKey() {
  if (process.env.AGENT_PRIVATE_KEY) return process.env.AGENT_PRIVATE_KEY;
  const agentFile = path.join(__dirname, '..', 'wallets', 'polygon', 'agent.json');
  if (fs.existsSync(agentFile)) {
    const data = JSON.parse(fs.readFileSync(agentFile, 'utf-8'));
    return data.privateKey;
  }
  throw new Error('No agent private key found. Set AGENT_PRIVATE_KEY or place wallets/polygon/agent.json');
}

async function waitForTx(tx, label = 'tx') {
  process.stdout.write(`  ⏳ Waiting for ${label}...`);
  const receipt = await tx.wait(1);
  console.log(` ✅ confirmed (block ${receipt.blockNumber})`);
  return receipt;
}

// ============================================================================
// MAIN
// ============================================================================

async function main() {
  const args = process.argv.slice(2);
  const dryRun = args.includes('--dry-run');
  const providerFilter = args.includes('--provider')
    ? args[args.indexOf('--provider') + 1]?.toLowerCase()
    : null;

  console.log('═══════════════════════════════════════════════════');
  console.log('  DRAIN Test Payment Script');
  console.log('═══════════════════════════════════════════════════\n');

  // 1. Setup wallet & contracts
  const provider = new ethers.JsonRpcProvider(RPC_URL);
  const wallet = new ethers.Wallet(loadAgentKey(), provider);
  console.log(`Agent wallet : ${wallet.address}`);

  const usdc  = new ethers.Contract(USDC_ADDRESS, USDC_ABI, wallet);
  const drain = new ethers.Contract(DRAIN_CONTRACT, DRAIN_ABI, wallet);

  // Check balances
  const maticBal = await provider.getBalance(wallet.address);
  const usdcBal  = await usdc.balanceOf(wallet.address);
  console.log(`MATIC balance: ${ethers.formatEther(maticBal)} POL`);
  console.log(`USDC balance : ${formatUSDC(usdcBal)}\n`);

  if (usdcBal === 0n) {
    console.error('❌ Agent wallet has no USDC. Fund it first.');
    process.exit(1);
  }

  // 2. Fetch marketplace config (fee wallet)
  let feeWallet = null;
  try {
    const cfgRes = await fetch(`${MARKETPLACE}/api/directory/config`);
    const cfg = await cfgRes.json();
    feeWallet = cfg.feeWallet || null;
    if (feeWallet) console.log(`Fee wallet:   ${feeWallet}`);
    else console.log(`Fee wallet:   not configured (skipping session fee)`);
  } catch { console.log('Fee wallet:   could not fetch config'); }
  console.log();

  // 3. Fetch providers from marketplace
  console.log(`Fetching providers from ${MARKETPLACE}...`);
  const res = await fetch(`${MARKETPLACE}/api/directory/providers?format=json`);
  if (!res.ok) throw new Error(`Marketplace returned ${res.status}`);
  const data = await res.json();
  let providers = data.providers || data;
  console.log(`Found ${providers.length} approved providers.\n`);

  if (providerFilter) {
    providers = providers.filter(p =>
      p.name.toLowerCase().includes(providerFilter) ||
      p.providerAddress?.toLowerCase() === providerFilter
    );
    if (providers.length === 0) {
      console.error(`❌ No provider matching "${providerFilter}"`);
      process.exit(1);
    }
  }

  if (dryRun) {
    console.log('Providers (dry-run):\n');
    for (const p of providers) {
      const models = (p.models || []).map(m => m.modelId || m.name).join(', ');
      console.log(`  • ${p.name}`);
      console.log(`    URL    : ${p.apiUrl}`);
      console.log(`    Wallet : ${p.providerAddress}`);
      console.log(`    Models : ${models || '(none)'}`);
      console.log(`    Online : ${p.isOnline ? '✅' : '❌'}`);
      console.log();
    }
    return;
  }

  // 4. Ensure USDC approval for DRAIN contract
  const depositWei = parseUSDC(DEPOSIT_USDC);
  const feePerProvider = feeWallet ? SESSION_FEE : 0n;
  const totalNeeded = (depositWei + feePerProvider) * BigInt(providers.length);

  if (usdcBal < totalNeeded) {
    console.error(`❌ Not enough USDC. Need ${formatUSDC(totalNeeded)} for ${providers.length} providers (incl. fees), have ${formatUSDC(usdcBal)}`);
    process.exit(1);
  }

  const allowance = await usdc.allowance(wallet.address, DRAIN_CONTRACT);
  if (allowance < totalNeeded) {
    console.log('Approving USDC spend on DRAIN contract...');
    const approveTx = await usdc.approve(DRAIN_CONTRACT, ethers.MaxUint256);
    await waitForTx(approveTx, 'USDC approve');
    console.log();
  }

  // 4. Test each provider
  const results = [];

  for (const prov of providers) {
    const provName    = prov.name;
    const provAddress = prov.providerAddress;
    const provUrl     = prov.apiUrl;
    const model       = prov.models?.[0];

    console.log('───────────────────────────────────────────────────');
    console.log(`Provider: ${provName}`);
    console.log(`URL     : ${provUrl}`);
    console.log(`Address : ${provAddress}`);
    console.log(`Model   : ${model?.modelId || model?.name || 'unknown'}`);
    console.log('───────────────────────────────────────────────────');

    const result = { name: provName, address: provAddress, url: provUrl };

    try {
      // a) Pay session fee
      if (feeWallet) {
        console.log(`  Paying session fee ($0.01 USDC to ${feeWallet.slice(0,10)}...)...`);
        const feeTx = await usdc.transfer(feeWallet, SESSION_FEE);
        await waitForTx(feeTx, 'session fee');
      }

      // b) Open channel
      console.log(`  Opening channel (${DEPOSIT_USDC} USDC, ${DURATION_SEC}s)...`);
      const openTx = await drain.open(provAddress, depositWei, DURATION_SEC);
      const receipt = await waitForTx(openTx, 'channel open');

      // Find ChannelOpened event
      const iface = new ethers.Interface(DRAIN_ABI);
      let channelId = null;
      for (const log of receipt.logs) {
        try {
          const parsed = iface.parseLog({ topics: log.topics, data: log.data });
          if (parsed?.name === 'ChannelOpened') {
            channelId = parsed.args[0]; // first indexed param = channelId
            break;
          }
        } catch { /* not our event */ }
      }

      if (!channelId) {
        // Fallback: look for topic
        const eventSig = '0x506f81b7a67b45bfbc6167fd087b3dd9b65b4531a2380ec406aab5b57ac62152';
        const openedLog = receipt.logs.find(l => l.topics[0] === eventSig);
        channelId = openedLog?.topics[1];
      }

      if (!channelId) throw new Error('ChannelOpened event not found in receipt');
      
      console.log(`  Channel ID: ${channelId}`);
      result.channelId = channelId;

      // b) Sign EIP-712 voucher
      const voucherAmount = parseUSDC(VOUCHER_USDC);
      const nonce = 0;

      const voucherMessage = {
        channelId: channelId,
        amount: voucherAmount,
        nonce: nonce,
      };

      console.log(`  Signing voucher (${VOUCHER_USDC} USDC, nonce=${nonce})...`);
      const signature = await wallet.signTypedData(EIP712_DOMAIN, VOUCHER_TYPES, voucherMessage);
      console.log(`  Signature: ${signature.slice(0, 20)}...`);

      // c) Build voucher header
      const voucherHeader = JSON.stringify({
        channelId: channelId,
        amount: voucherAmount.toString(),
        nonce: nonce.toString(),
        signature: signature,
      });

      // d) Send chat request
      const modelId = model?.modelId || model?.name || 'gpt-4o-mini';
      console.log(`  Sending chat request to ${provUrl}/v1/chat/completions ...`);

      const startTime = Date.now();
      const chatRes = await fetch(`${provUrl}/v1/chat/completions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-DRAIN-Voucher': voucherHeader,
        },
        body: JSON.stringify({
          model: modelId,
          messages: [
            { role: 'user', content: 'Say "Hello from Handshake58 test!" in exactly 5 words.' },
          ],
          max_tokens: 50,
        }),
      });

      const elapsed = Date.now() - startTime;
      result.statusCode = chatRes.status;
      result.responseTime = elapsed;

      // Read DRAIN cost headers
      result.drainCost      = chatRes.headers.get('X-DRAIN-Cost');
      result.drainTotal     = chatRes.headers.get('X-DRAIN-Total');
      result.drainRemaining = chatRes.headers.get('X-DRAIN-Remaining');

      if (!chatRes.ok) {
        const errBody = await chatRes.text();
        console.log(`  ❌ HTTP ${chatRes.status}: ${errBody.slice(0, 200)}`);
        result.success = false;
        result.error = `HTTP ${chatRes.status}`;
      } else {
        const body = await chatRes.json();
        const reply = body.choices?.[0]?.message?.content || '(no content)';
        console.log(`  ✅ Response (${elapsed}ms): "${reply}"`);
        console.log(`  💰 Cost: ${result.drainCost || 'n/a'} | Total: ${result.drainTotal || 'n/a'} | Remaining: ${result.drainRemaining || 'n/a'}`);
        result.success = true;
        result.reply = reply;
      }

    } catch (err) {
      console.log(`  ❌ Error: ${err.message}`);
      result.success = false;
      result.error = err.message;
    }

    results.push(result);
    console.log();
  }

  // 5. Summary
  console.log('═══════════════════════════════════════════════════');
  console.log('  SUMMARY');
  console.log('═══════════════════════════════════════════════════\n');

  const succeeded = results.filter(r => r.success);
  const failed    = results.filter(r => !r.success);

  console.log(`Total providers tested: ${results.length}`);
  console.log(`Succeeded: ${succeeded.length}`);
  console.log(`Failed:    ${failed.length}\n`);

  for (const r of results) {
    const icon = r.success ? '✅' : '❌';
    const time = r.responseTime ? `${r.responseTime}ms` : 'n/a';
    const cost = r.drainCost ? formatUSDC(BigInt(r.drainCost)) : 'n/a';
    console.log(`  ${icon} ${r.name.padEnd(30)} ${time.padStart(8)} | cost: ${cost} | ${r.error || r.reply?.slice(0, 40) || ''}`);
  }

  console.log('\n═══════════════════════════════════════════════════');

  // Final USDC balance
  const finalBal = await usdc.balanceOf(wallet.address);
  console.log(`USDC remaining: ${formatUSDC(finalBal)}`);
  console.log('═══════════════════════════════════════════════════\n');

  if (failed.length > 0) process.exit(1);
}

main().catch(err => {
  console.error('\n💀 Fatal error:', err.message);
  process.exit(1);
});
