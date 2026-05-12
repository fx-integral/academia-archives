/**
 * HS58-Numinous Provider Configuration
 *
 * Flat-rate pricing: fixed cost per forecast request.
 */

import { config } from 'dotenv';
import type { Hex } from 'viem';
import type { ProviderConfig, ModelPricing } from './types.js';

config();

const requireEnv = (name: string): string => {
  const value = process.env[name];
  if (!value) throw new Error(`Missing required env: ${name}`);
  return value;
};

const optionalEnv = (name: string, defaultValue: string): string =>
  process.env[name] ?? defaultValue;

const MODEL_ID = 'numinous/forecaster';

let modelPricing: ModelPricing | null = null;

export function loadConfig(): ProviderConfig {
  const chainIdRaw = parseInt(optionalEnv('CHAIN_ID', '137'));
  const chainId = chainIdRaw === 80002 ? 80002 : 137;

  const cfg: ProviderConfig = {
    numinousApiUrl: optionalEnv('NUMINOUS_API_URL', 'https://api.numinouslabs.io'),
    numinousApiKey: requireEnv('NUMINOUS_API_KEY'),
    numinousPollIntervalMs: parseInt(optionalEnv('NUMINOUS_POLL_INTERVAL_MS', '5000')),
    numinousPollTimeoutMs: parseInt(optionalEnv('NUMINOUS_POLL_TIMEOUT_MS', '240000')),
    pricePerRequestUsdc: parseFloat(optionalEnv('PRICE_PER_REQUEST_USDC', '0.10')),
    port: parseInt(optionalEnv('PORT', '3000')),
    host: optionalEnv('HOST', '0.0.0.0'),
    chainId,
    providerPrivateKey: requireEnv('PROVIDER_PRIVATE_KEY') as Hex,
    polygonRpcUrl: process.env.POLYGON_RPC_URL || undefined,
    claimThreshold: BigInt(optionalEnv('CLAIM_THRESHOLD', '50000')),
    storagePath: optionalEnv('STORAGE_PATH', './data/vouchers.json'),
    providerName: optionalEnv('PROVIDER_NAME', 'HS58-Numinous'),
    autoClaimIntervalMinutes: parseInt(optionalEnv('AUTO_CLAIM_INTERVAL_MINUTES', '10')),
    autoClaimBufferSeconds: parseInt(optionalEnv('AUTO_CLAIM_BUFFER_SECONDS', '3600')),
  };

  const priceWei = BigInt(Math.ceil(cfg.pricePerRequestUsdc * 1_000_000));
  modelPricing = {
    inputPer1k: priceWei,
    outputPer1k: 0n,
  };

  return cfg;
}

export function getModelId(): string {
  return MODEL_ID;
}

export function getModelPricing(): ModelPricing {
  if (!modelPricing) throw new Error('Config not loaded. Call loadConfig() first.');
  return modelPricing;
}

export function getRequestCost(): bigint {
  return getModelPricing().inputPer1k;
}
