/**
 * HS58-Vericore Provider Types
 */

import type { Hash, Hex } from 'viem';

// --- DRAIN shared types ---

export interface ModelPricing {
  inputPer1k: bigint;
  outputPer1k: bigint;
}

export interface ProviderConfig {
  vericoreApiUrl: string;
  vericoreApiKey: string;
  vericoreTimeoutMs: number;
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

// --- Vericore-specific types ---

export interface VericoreEvidenceStatement {
  statement: string;
  url: string;
  contradiction: number;
  neutral: number;
  entailment: number;
  sentiment: number;
  conviction: number;
  source_credibility: number;
  narrative_momentum: number;
  risk_reward_sentiment: number;
  political_leaning: number;
  catalyst_detection: number;
}

export interface VericoreEvidenceSummary {
  total_count: number;
  entailment: number;
  neutral: number;
  contradiction: number;
  sentiment: number;
  conviction: number;
  source_credibility: number;
  narrative_momentum: number;
  risk_reward_sentiment: number;
  political_leaning: number;
  catalyst_detection: number;
  statements: VericoreEvidenceStatement[];
}

export interface VericoreResponse {
  batch_id: string;
  request_id: string;
  preview_url: string;
  evidence_summary: VericoreEvidenceSummary;
}
