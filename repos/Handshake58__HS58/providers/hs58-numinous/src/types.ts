/**
 * HS58-Numinous Provider Types
 */

import type { Hash, Hex } from 'viem';

// --- DRAIN shared types ---

export interface ModelPricing {
  inputPer1k: bigint;
  outputPer1k: bigint;
}

export interface ProviderConfig {
  numinousApiUrl: string;
  numinousApiKey: string;
  numinousPollIntervalMs: number;
  numinousPollTimeoutMs: number;
  pricePerRequestUsdc: number;
  port: number;
  host: string;
  chainId: 137 | 80002;
  providerPrivateKey: Hex;
  polygonRpcUrl?: string;
  claimThreshold: bigint;
  storagePath: string;
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

// --- Numinous-specific types ---

export interface NuminousStructuredRequest {
  title: string;
  description: string;
  cutoff: string;
  topics?: string[];
}

export interface NuminousQueryRequest {
  query: string;
}

export type NuminousCreateJobRequest = NuminousStructuredRequest | NuminousQueryRequest;

export interface NuminousCreateJobResponse {
  prediction_id: string;
  status: 'PENDING';
}

export type NuminousJobStatus = 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED';

export interface NuminousForecastMetadata {
  miner_uid?: number;
  miner_hotkey?: string;
  pool?: string;
  version_id?: string;
  agent_name?: string;
  version_number?: number;
  raw_prediction?: number;
  event_title?: string;
  event_cutoff?: string;
  reasoning?: string;
}

export interface NuminousForecastResult {
  prediction: number;
  forecaster_name: string;
  forecasted_at: string;
  metadata: NuminousForecastMetadata | null;
  parsed_fields: Record<string, unknown> | null;
}

export interface NuminousPredictionResponse {
  prediction_id: string;
  status: NuminousJobStatus;
  created_at?: string;
  result: NuminousForecastResult | null;
  error: string | null;
}
