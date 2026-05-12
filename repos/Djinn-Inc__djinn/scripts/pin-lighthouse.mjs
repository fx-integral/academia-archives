#!/usr/bin/env node
// Upload a directory to Lighthouse IPFS and print the resulting root CID.
//
// Usage: node scripts/pin-lighthouse.mjs <dir> <name>
//   <dir>   local directory to upload (recursive)
//   <name>  label prefix (e.g. "djinn-gg-v1375")
//
// Env:    LIGHTHOUSE_API_KEY (required)
//
// Output: stdout = single line JSON `{"cid":"Qm...","size":123456}`
//         stderr = progress log

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const [, , dir, name] = process.argv;
if (!dir || !name) {
  console.error("usage: pin-lighthouse.mjs <dir> <name>");
  process.exit(64);
}
const key = process.env.LIGHTHOUSE_API_KEY;
if (!key) {
  console.error("LIGHTHOUSE_API_KEY not set");
  process.exit(65);
}

function walk(d) {
  const out = [];
  for (const n of readdirSync(d)) {
    const full = join(d, n);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else out.push(full);
  }
  return out;
}

const files = walk(dir);
const totalSize = files.reduce((s, f) => s + statSync(f).size, 0);
console.error(
  `[lighthouse] uploading ${files.length} files (${(totalSize / 1024 / 1024).toFixed(1)} MB) as "${name}"`,
);

const form = new FormData();
for (const f of files) {
  const rel = relative(dir, f);
  form.append("file", new Blob([readFileSync(f)]), `${name}/${rel}`);
}

const startedAt = Date.now();
const res = await fetch(
  "https://upload.lighthouse.storage/api/v0/add?wrap-with-directory=true",
  {
    method: "POST",
    headers: { Authorization: `Bearer ${key}` },
    body: form,
  },
);
const elapsed = ((Date.now() - startedAt) / 1000).toFixed(1);
console.error(`[lighthouse] HTTP ${res.status} in ${elapsed}s`);
const body = await res.text();
if (!res.ok) {
  console.error(body);
  process.exit(66);
}

// Lighthouse returns NDJSON; the final entry is the wrapper directory.
const lines = body
  .trim()
  .split("\n")
  .map((l) => l.trim())
  .filter(Boolean);
let root = null;
for (const line of lines) {
  let entry;
  try {
    entry = JSON.parse(line);
  } catch {
    continue;
  }
  if (entry.Name === "" || entry.Name === name) root = entry;
}
if (!root) root = JSON.parse(lines[lines.length - 1]);
console.log(
  JSON.stringify({ cid: root.Hash, size: Number(root.Size ?? totalSize) }),
);
