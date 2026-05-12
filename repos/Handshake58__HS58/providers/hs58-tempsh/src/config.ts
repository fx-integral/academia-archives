/**
 * HS58-TempSh Provider Configuration
 *
 * Flat-rate or per-MB pricing for file uploads proxied to temp.sh.
 */

import { config } from 'dotenv';
import type { ProviderConfig, ModelPricing } from './types.js';
import type { Hex } from 'viem';

config();

const requireEnv = (name: string): string => {
  const value = process.env[name];
  if (!value) throw new Error(`Missing env: ${name}`);
  return value;
};

const optionalEnv = (name: string, defaultValue: string): string =>
  process.env[name] ?? defaultValue;

let activeModels: Map<string, ModelPricing> = new Map();

const DEFAULT_PRICE_PER_UPLOAD_USD = 0.005;
const DEFAULT_PRICE_PER_MB_USD = 0.002;

export function loadModels(markup: number, pricingMode: 'flat' | 'per-mb'): void {
  activeModels = new Map();

  if (pricingMode === 'flat') {
    const priceUsd = parseFloat(optionalEnv('PRICE_PER_UPLOAD', DEFAULT_PRICE_PER_UPLOAD_USD.toString()));
    const priceUsdc = BigInt(Math.ceil(priceUsd * markup * 1_000_000));
    activeModels.set('tempsh/upload', { inputPer1k: priceUsdc, outputPer1k: 0n });
    console.log(`  tempsh/upload (flat): $${(Number(priceUsdc) / 1_000_000).toFixed(4)}/upload`);
  } else {
    const priceUsd = parseFloat(optionalEnv('PRICE_PER_MB', DEFAULT_PRICE_PER_MB_USD.toString()));
    const priceUsdc = BigInt(Math.ceil(priceUsd * markup * 1_000_000));
    activeModels.set('tempsh/upload', { inputPer1k: priceUsdc, outputPer1k: 0n });
    console.log(`  tempsh/upload (per-mb): $${(Number(priceUsdc) / 1_000_000).toFixed(4)}/MB`);
  }

  console.log(`Loaded 1 model with ${(markup - 1) * 100}% markup`);
}

export const getModelPricing = (model: string): ModelPricing | null => activeModels.get(model) ?? null;
export const isModelSupported = (model: string): boolean => activeModels.has(model);
export const getSupportedModels = (): string[] => Array.from(activeModels.keys());

export function loadConfig(): ProviderConfig {
  const chainId = parseInt(optionalEnv('CHAIN_ID', '137')) as 137 | 80002;
  if (chainId !== 137 && chainId !== 80002) throw new Error(`Invalid CHAIN_ID: ${chainId}`);

  const markupPercent = parseInt(optionalEnv('MARKUP_PERCENT', '50'));
  const markup = 1 + (markupPercent / 100);

  const pricingMode = optionalEnv('PRICING_MODE', 'flat') as 'flat' | 'per-mb';

  const pricePerUploadUsd = parseFloat(optionalEnv('PRICE_PER_UPLOAD', DEFAULT_PRICE_PER_UPLOAD_USD.toString()));
  const pricePerMbUsd = parseFloat(optionalEnv('PRICE_PER_MB', DEFAULT_PRICE_PER_MB_USD.toString()));

  const pricePerUpload = BigInt(Math.ceil(pricePerUploadUsd * markup * 1_000_000));
  const pricePerMb = BigInt(Math.ceil(pricePerMbUsd * markup * 1_000_000));

  const maxFileMb = parseInt(optionalEnv('MAX_FILE_SIZE_MB', '100'));
  const maxFileSizeBytes = maxFileMb * 1024 * 1024;

  const allowedMimeTypesStr = optionalEnv('ALLOWED_MIME_TYPES', '');
  const allowedMimeTypes = allowedMimeTypesStr
    ? allowedMimeTypesStr.split(',').map(m => m.trim()).filter(Boolean)
    : [];

  return {
    pricePerUpload,
    pricePerMb,
    pricingMode,
    maxFileSizeBytes,
    allowedMimeTypes,
    rateLimitPerMinute: parseInt(optionalEnv('RATE_LIMIT_PER_MINUTE', '20')),
    adminPassword: process.env.ADMIN_PASSWORD || undefined,
    port: parseInt(optionalEnv('PORT', '3000')),
    host: optionalEnv('HOST', '0.0.0.0'),
    chainId,
    providerPrivateKey: requireEnv('PROVIDER_PRIVATE_KEY') as Hex,
    polygonRpcUrl: process.env.POLYGON_RPC_URL || undefined,
    pricing: activeModels,
    claimThreshold: BigInt(optionalEnv('CLAIM_THRESHOLD', '1000000')),
    storagePath: optionalEnv('STORAGE_PATH', './data/vouchers.json'),
    markup,
    providerName: optionalEnv('PROVIDER_NAME', 'HS58-TempSh'),
    autoClaimIntervalMinutes: parseInt(optionalEnv('AUTO_CLAIM_INTERVAL_MINUTES', '10')),
    autoClaimBufferSeconds: parseInt(optionalEnv('AUTO_CLAIM_BUFFER_SECONDS', '3600')),
  };
}
