/**
 * HS58-Replicate Provider Types
 */

import type { Hash, Hex } from 'viem';

// --- DRAIN shared types ---

export interface ModelPricing {
  inputPer1k: bigint;
  outputPer1k: bigint;
}

export interface ProviderConfig {
  replicateApiToken: string;
  markupPercent: number;
  syncIntervalHours: number;
  maxPredictionTimeoutMs: number;
  predictionPollIntervalMs: number;
  syncCollections: string[];
  port: number;
  host: string;
  chainId: 137 | 80002;
  providerPrivateKey: Hex;
  polygonRpcUrl?: string;
  claimThreshold: bigint;
  storagePath: string;
  registryPath: string;
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

// --- Replicate-specific types ---

export type PricingTier =
  | 'image-gen'
  | 'video-gen'
  | 'llm'
  | 'audio'
  | 'image-edit'
  | 'video-edit'
  | '3d'
  | 'utility';

export interface PricingTierConfig {
  priceUsdc: number;
  description: string;
}

export interface RegisteredModel {
  id: string;
  owner: string;
  name: string;
  description: string;
  pricingTier: PricingTier;
  collections: string[];
  runCount: number;
  isOfficial: boolean;
  coverImageUrl: string | null;
  inputSchema: Record<string, unknown> | null;
  outputSchema: Record<string, unknown> | null;
  lastSynced: number;
}

export interface RegistryData {
  models: Record<string, RegisteredModel>;
  lastFullSync: number;
  version: number;
}

export interface ReplicateCollectionResponse {
  name: string;
  slug: string;
  description: string;
  models: ReplicateModelResponse[];
}

export interface ReplicateModelResponse {
  url: string;
  owner: string;
  name: string;
  description: string | null;
  visibility: string;
  run_count: number;
  cover_image_url: string | null;
  is_official?: boolean;
  default_example?: ReplicatePrediction | null;
  latest_version?: ReplicateModelVersion | null;
}

export interface ReplicateModelVersion {
  id: string;
  created_at: string;
  cog_version: string;
  openapi_schema?: {
    components?: {
      schemas?: {
        Input?: Record<string, unknown>;
        Output?: Record<string, unknown>;
      };
    };
  };
}

export interface ReplicatePrediction {
  id: string;
  model: string;
  version?: string;
  status: 'starting' | 'processing' | 'succeeded' | 'failed' | 'canceled';
  input: Record<string, unknown>;
  output: unknown;
  error: string | null;
  logs: string | null;
  metrics?: {
    predict_time?: number;
    total_time?: number;
    input_token_count?: number;
    output_token_count?: number;
    tokens_per_second?: number;
    image_count?: number;
  };
  urls?: {
    get?: string;
    cancel?: string;
    stream?: string;
  };
  created_at: string;
  started_at?: string;
  completed_at?: string;
}
