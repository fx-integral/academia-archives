/**
 * HS58-E2B Provider Types
 */

import type { Hash, Hex } from 'viem';

export interface ModelPricing {
  inputPer1k: bigint;
  outputPer1k: bigint;
}

export interface ProviderConfig {
  e2bApiKey: string;
  sandboxTimeoutMs: number;
  markupMultiplier: number;
  port: number;
  host: string;
  chainId: 137 | 80002;
  providerPrivateKey: Hex;
  polygonRpcUrl?: string;
  pricing: Map<string, ModelPricing>;
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

// --- E2B-specific types ---

/** Supported code execution languages */
export type E2BLanguage = 'python' | 'javascript' | 'typescript' | 'bash' | 'r' | 'java';

/** Maps model ID (e.g. "e2b/python") to E2B language parameter */
export const MODEL_TO_LANGUAGE: Record<string, E2BLanguage> = {
  'e2b/python':     'python',
  'e2b/javascript': 'javascript',
  'e2b/typescript': 'typescript',
  'e2b/bash':       'bash',
  'e2b/r':          'r',
  'e2b/java':       'java',
};

export interface ExecutionResult {
  language: E2BLanguage;
  stdout: string;
  stderr: string;
  results: unknown[];
  error: {
    name: string;
    value: string;
    traceback: string;
  } | null;
  executionTimeMs: number;
}
