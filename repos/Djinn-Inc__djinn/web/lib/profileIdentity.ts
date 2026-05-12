import { truncateAddress } from "./types";

const ADJECTIVES = [
  "Steady",
  "Sharp",
  "Calm",
  "Bold",
  "Prime",
  "Swift",
  "Keen",
  "Solid",
  "Clean",
  "Sure",
] as const;

const NOUNS = [
  "Scout",
  "Oracle",
  "Trader",
  "Analyst",
  "Forecaster",
  "Captain",
  "Strategist",
  "Navigator",
  "Operator",
  "Signaler",
] as const;

const BIO_TEMPLATES = [
  "On-chain analyst publishing verified sports signals.",
  "Public track record secured by audit settlements.",
  "Signal publisher with transparent performance history.",
] as const;

function hashAddress(address: string): number {
  let h = 2166136261;
  for (const ch of address.toLowerCase()) {
    h ^= ch.charCodeAt(0);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export interface ProfileIdentity {
  handle: string;
  bio: string;
  initials: string;
  avatarStyle: { background: string; color: string };
}

export function profileIdentity(address: string): ProfileIdentity {
  const hash = hashAddress(address);
  const adjective = ADJECTIVES[hash % ADJECTIVES.length];
  const noun = NOUNS[(hash >>> 4) % NOUNS.length];
  const hue = (hash >>> 8) % 360;
  const saturation = 68 + ((hash >>> 14) % 16);
  const lightness = 46 + ((hash >>> 20) % 12);
  const handle = `${adjective}${noun}`;
  const bio = BIO_TEMPLATES[(hash >>> 24) % BIO_TEMPLATES.length];

  return {
    handle,
    bio,
    initials: `${adjective[0]}${noun[0]}`.toUpperCase(),
    avatarStyle: {
      background: `linear-gradient(135deg, hsl(${hue} ${saturation}% ${lightness + 8}%), hsl(${(hue + 32) % 360} ${saturation}% ${lightness - 6}%))`,
      color: "#ffffff",
    },
  };
}

export function profileLabel(address: string): string {
  const id = profileIdentity(address);
  return `@${id.handle} (${truncateAddress(address)})`;
}
