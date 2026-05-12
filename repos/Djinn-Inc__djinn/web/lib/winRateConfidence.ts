export const WIN_RATE_MIN_AUDITS_DEFAULT = 10;
export const WIN_RATE_SMALL_SAMPLE_THRESHOLD = 5;

export const MIN_AUDITS_FILTER_OPTIONS = [0, 5, 10, 25] as const;
export type MinAuditsFilter = (typeof MIN_AUDITS_FILTER_OPTIONS)[number];

export interface WinRateSample {
  favCount: number;
  unfavCount: number;
}

export type SampleClass = "none" | "small" | "modest" | "reliable";

export function winRateSampleSize(entry: WinRateSample): number {
  return entry.favCount + entry.unfavCount;
}

export function classifySample(entry: WinRateSample): SampleClass {
  const n = winRateSampleSize(entry);
  if (n === 0) return "none";
  if (n < WIN_RATE_SMALL_SAMPLE_THRESHOLD) return "small";
  if (n < WIN_RATE_MIN_AUDITS_DEFAULT) return "modest";
  return "reliable";
}

export function winRatePercent(entry: WinRateSample): number {
  const n = winRateSampleSize(entry);
  if (n === 0) return 0;
  return (entry.favCount / n) * 100;
}

const WILSON_Z_95 = 1.959963984540054;

export function winRateLowerBound(
  entry: WinRateSample,
  z: number = WILSON_Z_95,
): number {
  const n = winRateSampleSize(entry);
  if (n === 0) return 0;
  const p = entry.favCount / n;
  const z2 = z * z;
  const denom = 1 + z2 / n;
  const center = p + z2 / (2 * n);
  const margin = z * Math.sqrt((p * (1 - p) + z2 / (4 * n)) / n);
  const lower = (center - margin) / denom;
  return Math.max(0, lower);
}

export function meetsMinAudits(entry: WinRateSample, min: number): boolean {
  if (min <= 0) return true;
  return winRateSampleSize(entry) >= min;
}
