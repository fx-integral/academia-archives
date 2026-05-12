/**
 * HS58-Apify Provider Types
 */

import type { Hash, Hex } from 'viem';

export interface ModelPricing {
  inputPer1k: bigint;
  outputPer1k: bigint;
}

export interface ProviderConfig {
  apifyApiToken: string;
  actorLimit: number;
  maxItems: number;
  maxWait: number;
  markupMultiplier: number;
  port: number;
  host: string;
  chainId: 137 | 80002;
  providerPrivateKey: Hex;
  polygonRpcUrl?: string;
  pricing: Map<string, ModelPricing>;
  claimThreshold: bigint;
  storagePath: string;
  markup: number;
  providerName: string;
  autoClaimIntervalMinutes: number;
  autoClaimBufferSeconds: number;
}

export interface VoucherHeader {
  channelId: Hash;
  amount: string;
  nonce: string;
  signature: Hex;
}

export interface StoredVoucher {
  channelId: Hash;
  amount: bigint;
  nonce: bigint;
  signature: Hex;
  consumer: string;
  receivedAt: number;
  claimed: boolean;
  claimedAt?: number;
  claimTxHash?: Hash;
}

export interface ChannelState {
  channelId: Hash;
  consumer: string;
  deposit: bigint;
  totalCharged: bigint;
  expiry: number;
  lastVoucher?: StoredVoucher;
  createdAt: number;
  lastActivityAt: number;
}

export interface CostResult {
  cost: bigint;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
}

export interface DrainResponseHeaders {
  'X-DRAIN-Cost': string;
  'X-DRAIN-Total': string;
  'X-DRAIN-Remaining': string;
  'X-DRAIN-Channel': string;
}

export interface DrainErrorHeaders {
  'X-DRAIN-Error': string;
  'X-DRAIN-Required'?: string;
  'X-DRAIN-Provided'?: string;
}

// --- Apify-specific types ---

export interface EventPricing {
  eventTitle: string;
  eventDescription: string;
  isOneTimeEvent?: boolean;
  eventPriceUsd?: number;
  eventTieredPricingUsd?: Record<string, { tieredEventPriceUsd: number }>;
}

export interface StoreActorPricing {
  pricingModel: 'FREE' | 'PAY_PER_EVENT' | 'FLAT_PRICE_PER_MONTH' | 'PRICE_PER_DATASET_ITEM';
  pricingPerEvent?: {
    actorChargeEvents: Record<string, EventPricing>;
  };
}

export interface StoreActor {
  id: string;
  name: string;
  username: string;
  title: string;
  description: string;
  currentPricingInfo: StoreActorPricing;
  /** Calculated DRAIN price in USDC wei (6 decimals) */
  drainPrice: bigint;
  /** What we set as maxTotalChargeUsd on Apify side */
  apifyBudget: number;
}

export interface RunResult {
  status: 'SUCCEEDED' | 'FAILED' | 'ABORTED' | 'TIMED-OUT' | 'RUNNING';
  defaultDatasetId?: string;
  output?: unknown;
  usageUsd?: number;
}
