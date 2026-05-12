/**
 * HS58-Replicate Provider Configuration
 */

import { config } from 'dotenv';
import type { Hex } from 'viem';
import type { ProviderConfig } from './types.js';
import { DEFAULT_SYNC_COLLECTIONS } from './constants.js';

config();

const requireEnv = (name: string): string => {
  const value = process.env[name];
  if (!value) throw new Error(`Missing required env: ${name}`);
  return value;
};

const optionalEnv = (name: string, defaultValue: string): string =>
  process.env[name] ?? defaultValue;

export function loadConfig(): ProviderConfig {
  const chainIdRaw = parseInt(optionalEnv('CHAIN_ID', '137'));
  const chainId = chainIdRaw === 80002 ? 80002 : 137;

  const customCollections = process.env.SYNC_COLLECTIONS;
  const syncCollections = customCollections
    ? customCollections.split(',').map(s => s.trim())
    : DEFAULT_SYNC_COLLECTIONS;

  return {
    replicateApiToken: requireEnv('REPLICATE_API_TOKEN'),
    markupPercent: parseFloat(optionalEnv('MARKUP_PERCENT', '50')),
    syncIntervalHours: parseFloat(optionalEnv('SYNC_INTERVAL_HOURS', '24')),
    maxPredictionTimeoutMs: parseInt(optionalEnv('MAX_PREDICTION_TIMEOUT_MS', '600000')),
    predictionPollIntervalMs: parseInt(optionalEnv('PREDICTION_POLL_INTERVAL_MS', '3000')),
    syncCollections,
    port: parseInt(optionalEnv('PORT', '3000')),
    host: optionalEnv('HOST', '0.0.0.0'),
    chainId,
    providerPrivateKey: requireEnv('PROVIDER_PRIVATE_KEY') as Hex,
    polygonRpcUrl: process.env.POLYGON_RPC_URL || undefined,
    claimThreshold: BigInt(optionalEnv('CLAIM_THRESHOLD', '50000')),
    storagePath: optionalEnv('STORAGE_PATH', './data/vouchers.json'),
    registryPath: optionalEnv('REGISTRY_PATH', './data/registry.json'),
    providerName: optionalEnv('PROVIDER_NAME', 'HS58-Replicate'),
    autoClaimIntervalMinutes: parseInt(optionalEnv('AUTO_CLAIM_INTERVAL_MINUTES', '10')),
    autoClaimBufferSeconds: parseInt(optionalEnv('AUTO_CLAIM_BUFFER_SECONDS', '3600')),
  };
}
