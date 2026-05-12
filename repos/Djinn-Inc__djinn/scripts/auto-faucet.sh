#!/usr/bin/env bash
# Drain CDP faucet quota every hour. Direct drip to fleet addresses;
# no ephemeral wallets, no sweep gas loss, no strand risk.
# Rate limit is ~10 drips/hr GLOBAL on the API key (measured 2026-04-20).
# Target: 0.001 ETH/hr banked => 0.024 ETH/day => 0.72 ETH in 30 days.
set -euo pipefail

cd /home/user/djinn

node -e "
import('@coinbase/cdp-sdk').then(async ({ CdpClient }) => {
  const fs = await import('node:fs');
  const env = {};
  fs.readFileSync(process.env.HOME + '/.cdp-faucet.env', 'utf8').split('\n').forEach(l => {
    if (l.includes('=') && !l.startsWith('#')) { const [k,v] = l.split('=',2); env[k.trim()] = v.trim(); }
  });
  const cdp = new CdpClient({ apiKeyId: env.CDP_API_KEY, apiKeySecret: env.CDP_API_SECRET });

  // Fleet: deployer needs ETH most (pays gas for test flows + deploys).
  // Weight biases toward deployer; 10 drips => 6 deployer / 2 genius / 1 each other.
  const fleet = [
    { addr: '0xD717b5fbA93F123f6ad530ae2Ab327B4DcDa1e37', weight: 6 },
    { addr: '0x68fc8eeC9E5551d4c93a89b6d861f0a05e0A2A1d', weight: 2 },
    { addr: '0x82253053129fD3C95A7b09f1611Fc6Fc385227b4', weight: 1 },
    { addr: '0xa01C91f04C37d049D5887fd4D7B08AeEFc8Ca434', weight: 1 },
  ];
  const targets = fleet.flatMap(f => Array(f.weight).fill(f.addr));

  let ok = 0, fail = 0;
  for (const addr of targets) {
    try {
      await cdp.evm.requestFaucet({ address: addr, network: 'base-sepolia', token: 'eth' });
      ok++;
      console.log('OK', addr.slice(0, 12));
    } catch (e) {
      fail++;
      const msg = (e.message || '').slice(0, 80);
      console.log('FAIL', addr.slice(0, 12), msg);
      if (msg.toLowerCase().match(/rate|limit|quota|throttle/)) {
        console.log('Rate limited at', ok, 'drips. Stopping.');
        break;
      }
    }
    await new Promise(r => setTimeout(r, 400));
  }
  console.log(new Date().toISOString(), 'ok=' + ok, 'fail=' + fail);
});
"

echo "Done. $(date -u +%Y-%m-%dT%H:%M:%SZ)"
