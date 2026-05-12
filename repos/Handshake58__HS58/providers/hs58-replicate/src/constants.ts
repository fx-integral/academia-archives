/**
 * DRAIN Protocol Constants + Replicate Pricing Tiers
 */

import type { PricingTier, PricingTierConfig } from './types.js';

// --- DRAIN Contract ---

export const DRAIN_ADDRESSES: Record<number, string> = {
  137: '0x0C2B3aA1e80629D572b1f200e6DF3586B3946A8A',
  80002: '0x61f1C1E04d6Da1C92D0aF1a3d7Dc0fEFc8794d7C',
};

export const USDC_DECIMALS = 6;

export const EIP712_DOMAIN = {
  name: 'DrainChannel',
  version: '1',
} as const;

export const DRAIN_CHANNEL_ABI = [
  {
    inputs: [{ name: 'channelId', type: 'bytes32' }],
    name: 'getChannel',
    outputs: [{
      components: [
        { name: 'consumer', type: 'address' },
        { name: 'provider', type: 'address' },
        { name: 'deposit', type: 'uint256' },
        { name: 'claimed', type: 'uint256' },
        { name: 'expiry', type: 'uint256' },
      ],
      name: '', type: 'tuple',
    }],
    stateMutability: 'view', type: 'function',
  },
  {
    inputs: [{ name: 'channelId', type: 'bytes32' }],
    name: 'getBalance',
    outputs: [{ name: '', type: 'uint256' }],
    stateMutability: 'view', type: 'function',
  },
  {
    inputs: [
      { name: 'channelId', type: 'bytes32' },
      { name: 'amount', type: 'uint256' },
      { name: 'nonce', type: 'uint256' },
      { name: 'signature', type: 'bytes' },
    ],
    name: 'claim', outputs: [], stateMutability: 'nonpayable', type: 'function',
  },
  { inputs: [], name: 'NotOwner', type: 'error' },
  { inputs: [], name: 'NoOwner', type: 'error' },
  { inputs: [], name: 'ZeroAddress', type: 'error' },
  { inputs: [], name: 'ChannelExists', type: 'error' },
  { inputs: [], name: 'ChannelNotFound', type: 'error' },
  { inputs: [], name: 'NotProvider', type: 'error' },
  { inputs: [], name: 'NotConsumer', type: 'error' },
  { inputs: [], name: 'NotExpired', type: 'error' },
  { inputs: [], name: 'InvalidSignature', type: 'error' },
  { inputs: [], name: 'InvalidAmount', type: 'error' },
  { inputs: [], name: 'TransferFailed', type: 'error' },
  {
    anonymous: false,
    inputs: [
      { indexed: true, name: 'channelId', type: 'bytes32' },
      { indexed: true, name: 'provider', type: 'address' },
      { indexed: false, name: 'amount', type: 'uint256' },
    ],
    name: 'ChannelClaimed', type: 'event',
  },
  {
    inputs: [
      { name: 'channelId', type: 'bytes32' },
      { name: 'finalAmount', type: 'uint256' },
      { name: 'providerSignature', type: 'bytes' },
    ],
    name: 'cooperativeClose', outputs: [], stateMutability: 'nonpayable', type: 'function',
  },
  {
    anonymous: false,
    inputs: [
      { indexed: true, name: 'channelId', type: 'bytes32' },
      { indexed: true, name: 'consumer', type: 'address' },
      { indexed: false, name: 'refund', type: 'uint256' },
    ],
    name: 'ChannelClosed', type: 'event',
  },
  {
    anonymous: false,
    inputs: [
      { indexed: true, name: 'channelId', type: 'bytes32' },
      { indexed: true, name: 'recipient', type: 'address' },
      { indexed: false, name: 'amount', type: 'uint256' },
    ],
    name: 'FeePaid', type: 'event',
  },
] as const;

export const PERMANENT_CLAIM_ERRORS = [
  'InvalidAmount', 'ChannelNotFound', 'InvalidSignature', 'NotProvider', 'NotExpired',
] as const;

// --- Replicate Pricing Tiers ---

export const PRICING_TIERS: Record<PricingTier, PricingTierConfig> = {
  'image-gen':  { priceUsdc: 0.03, description: 'Image generation (text/image to image)' },
  'video-gen':  { priceUsdc: 0.30, description: 'Video generation (text/image to video)' },
  'llm':        { priceUsdc: 0.01, description: 'Language model inference' },
  'audio':      { priceUsdc: 0.05, description: 'Audio processing (STT, TTS, music)' },
  'image-edit': { priceUsdc: 0.03, description: 'Image editing, upscaling, restoration' },
  'video-edit': { priceUsdc: 0.15, description: 'Video editing, enhancement, lipsync' },
  '3d':         { priceUsdc: 0.15, description: '3D model generation' },
  'utility':    { priceUsdc: 0.03, description: 'Utilities (classification, OCR, embeddings, face swap)' },
};

/**
 * Maps Replicate collection slugs to pricing tiers.
 * A model inherits the tier of its first matched collection.
 */
export const COLLECTION_TIER_MAP: Record<string, PricingTier> = {
  'text-to-image': 'image-gen',
  'flux': 'image-gen',
  'flux-fine-tunes': 'image-gen',
  'flux-kontext-fine-tunes': 'image-gen',
  'generate-anime': 'image-gen',
  'sketch-to-image': 'image-gen',
  'generate-emoji': 'image-gen',
  'ai-face-generator': 'image-gen',
  'qwen-image-fine-tunes': 'image-gen',

  'text-to-video': 'video-gen',
  'image-to-video': 'video-gen',
  'wan-video': 'video-gen',

  'language-models': 'llm',
  'vision-models': 'llm',

  'speech-to-text': 'audio',
  'text-to-speech': 'audio',
  'ai-music-generation': 'audio',
  'speaker-diarization': 'audio',
  'sing-with-voices': 'audio',

  'image-editing': 'image-edit',
  'super-resolution': 'image-edit',
  'remove-backgrounds': 'image-edit',
  'ai-image-restoration': 'image-edit',
  'control-net': 'image-edit',

  'video-editing': 'video-edit',
  'ai-enhance-videos': 'video-edit',
  'lipsync': 'video-edit',
  'video-to-text': 'video-edit',

  '3d-models': '3d',

  'face-swap': 'utility',
  'detect-nsfw-content': 'utility',
  'text-classification': 'utility',
  'embedding-models': 'utility',
  'utilities': 'utility',
  'text-recognition-ocr': 'utility',
  'image-to-text': 'utility',
  'ai-detect-objects': 'utility',
};

/**
 * Default collections to sync on startup.
 */
export const DEFAULT_SYNC_COLLECTIONS = [
  'official',
  'text-to-image',
  'image-to-video',
  'text-to-video',
  'language-models',
  'speech-to-text',
  'text-to-speech',
  'super-resolution',
  'image-editing',
  'vision-models',
  '3d-models',
  'wan-video',
  'flux',
];

export const REPLICATE_API_BASE = 'https://api.replicate.com/v1';
