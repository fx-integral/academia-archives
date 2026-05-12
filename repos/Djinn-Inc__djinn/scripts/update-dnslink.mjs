#!/usr/bin/env node
// Update the `_dnslink.<host>` TXT record at Namecheap so IPFS gateways
// resolve `<host>` to a specific CID.
//
// Usage: node scripts/update-dnslink.mjs <subdomain> <cid>
//   <subdomain>  e.g. "_dnslink" (the Namecheap Host field)
//   <cid>        Qm... or bafy...
//
// Env:  NAMECHEAP_API_USER   Namecheap API user (usually same as UserName)
//       NAMECHEAP_API_KEY    Namecheap API key
//       NAMECHEAP_USERNAME   (optional) Namecheap account username (defaults to API_USER)
//       NAMECHEAP_CLIENT_IP  IP whitelisted in Namecheap API; must match the caller
//       NAMECHEAP_SLD        second-level domain, default "djinn"
//       NAMECHEAP_TLD        top-level domain, default "gg"
//
// The Namecheap API is stateful: setHosts REPLACES every record on the
// zone. This script reads the current hosts via getHosts, swaps the
// targeted _dnslink TXT, and writes the full list back.

const [, , subdomain, cid] = process.argv;
if (!subdomain || !cid) {
  console.error("usage: update-dnslink.mjs <subdomain> <cid>");
  process.exit(64);
}

const apiUser = process.env.NAMECHEAP_API_USER;
const apiKey = process.env.NAMECHEAP_API_KEY;
const userName = process.env.NAMECHEAP_USERNAME ?? apiUser;
const clientIp = process.env.NAMECHEAP_CLIENT_IP;
const sld = process.env.NAMECHEAP_SLD ?? "djinn";
const tld = process.env.NAMECHEAP_TLD ?? "gg";

for (const [k, v] of Object.entries({ apiUser, apiKey, clientIp })) {
  if (!v) {
    console.error(`${k} not set`);
    process.exit(65);
  }
}

const BASE = "https://api.namecheap.com/xml.response";

// Decode the five XML entities Namecheap uses (&amp; &lt; &gt; &quot; &apos;).
function decode(s) {
  return s
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'");
}

function parseHosts(xml) {
  // <host ...Address="dnslink=/ipfs/Qm..." .../> — Address can contain "/",
  // so matching with `[^/>]` eats that record. Non-greedy match up to the
  // self-closing `/>` instead.
  const hosts = [];
  const re = /<host\s+(.*?)\/>/g;
  let m;
  while ((m = re.exec(xml)) !== null) {
    const attrs = {};
    const attrRe = /(\w+)="([^"]*)"/g;
    let a;
    while ((a = attrRe.exec(m[1])) !== null) attrs[a[1]] = decode(a[2]);
    hosts.push(attrs);
  }
  return hosts;
}

async function call(command, extra = {}) {
  const params = new URLSearchParams({
    ApiUser: apiUser,
    ApiKey: apiKey,
    UserName: userName,
    ClientIp: clientIp,
    Command: command,
    SLD: sld,
    TLD: tld,
    ...extra,
  });
  const res = await fetch(`${BASE}?${params}`);
  const text = await res.text();
  if (!res.ok) {
    console.error(text);
    throw new Error(`${command} HTTP ${res.status}`);
  }
  if (!/Status="OK"/.test(text.slice(0, 500))) {
    console.error(text);
    throw new Error(`${command} status != OK`);
  }
  return text;
}

console.error(`[dnslink] reading current hosts for ${sld}.${tld}…`);
const current = await call("namecheap.domains.dns.getHosts");
const hosts = parseHosts(current);
console.error(`[dnslink] ${hosts.length} existing record(s)`);

const targetValue = `dnslink=/ipfs/${cid}`;
let replaced = 0;
const rebuilt = hosts.map((h) => {
  if (h.Name === subdomain && h.Type === "TXT") {
    replaced += 1;
    return { ...h, Address: targetValue };
  }
  return h;
});
if (replaced === 0) {
  console.error(`[dnslink] no existing TXT for ${subdomain}; adding`);
  rebuilt.push({
    Name: subdomain,
    Type: "TXT",
    Address: targetValue,
    TTL: "60",
    MXPref: "10",
  });
}

const extra = {};
rebuilt.forEach((h, i) => {
  const n = i + 1;
  extra[`HostName${n}`] = h.Name;
  extra[`RecordType${n}`] = h.Type;
  extra[`Address${n}`] = h.Address;
  extra[`MXPref${n}`] = h.MXPref ?? "10";
  extra[`TTL${n}`] = h.TTL ?? "1800";
});

console.error(
  `[dnslink] writing ${rebuilt.length} records (replaced=${replaced}) target=${targetValue}`,
);
await call("namecheap.domains.dns.setHosts", extra);
console.log(
  JSON.stringify({ host: `${subdomain}.${sld}.${tld}`, value: targetValue }),
);
