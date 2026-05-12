/**
 * Model Registry with Auto-Sync from Replicate Collections
 *
 * Periodically fetches models from configured Replicate collections,
 * assigns pricing tiers, and maintains an in-memory + file-cached registry.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'fs';
import { dirname } from 'path';
import { ReplicateClient } from './replicate.js';
import { COLLECTION_TIER_MAP, PRICING_TIERS } from './constants.js';
import type {
  PricingTier,
  RegisteredModel,
  RegistryData,
  ReplicateModelResponse,
} from './types.js';

export class ModelRegistry {
  private client: ReplicateClient;
  private collections: string[];
  private registryPath: string;
  private markupPercent: number;
  private data: RegistryData;
  private syncInterval: ReturnType<typeof setInterval> | null = null;

  constructor(
    client: ReplicateClient,
    collections: string[],
    registryPath: string,
    markupPercent: number,
  ) {
    this.client = client;
    this.collections = collections;
    this.registryPath = registryPath;
    this.markupPercent = markupPercent;
    this.data = this.loadFromDisk();
  }

  private loadFromDisk(): RegistryData {
    if (!existsSync(this.registryPath)) {
      return { models: {}, lastFullSync: 0, version: 1 };
    }
    try {
      const content = readFileSync(this.registryPath, 'utf-8');
      return JSON.parse(content) as RegistryData;
    } catch {
      console.warn('[registry] Failed to load cache, starting fresh');
      return { models: {}, lastFullSync: 0, version: 1 };
    }
  }

  private saveToDisk(): void {
    const dir = dirname(this.registryPath);
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
    writeFileSync(this.registryPath, JSON.stringify(this.data, null, 2));
  }

  async syncAll(): Promise<number> {
    console.log(`[registry] Syncing ${this.collections.length} collections...`);
    let added = 0;

    for (const slug of this.collections) {
      try {
        const collection = await this.client.getCollection(slug);
        const tier = COLLECTION_TIER_MAP[slug] ?? 'utility';

        for (const model of collection.models) {
          const id = `${model.owner}/${model.name}`;
          const existing = this.data.models[id];

          if (existing) {
            existing.runCount = model.run_count;
            if (!existing.collections.includes(slug)) {
              existing.collections.push(slug);
            }
            existing.lastSynced = Date.now();
          } else {
            this.data.models[id] = this.toRegisteredModel(model, slug, tier);
            added++;
          }
        }

        console.log(`[registry] ${slug}: ${collection.models.length} models (tier: ${tier})`);
      } catch (error: any) {
        console.error(`[registry] Failed to sync collection ${slug}:`, error.message);
      }
    }

    this.data.lastFullSync = Date.now();
    this.saveToDisk();
    const total = Object.keys(this.data.models).length;
    console.log(`[registry] Sync complete: ${total} models total, ${added} new`);
    return total;
  }

  private toRegisteredModel(
    model: ReplicateModelResponse,
    collectionSlug: string,
    tier: PricingTier,
  ): RegisteredModel {
    return {
      id: `${model.owner}/${model.name}`,
      owner: model.owner,
      name: model.name,
      description: model.description ?? '',
      pricingTier: tier,
      collections: [collectionSlug],
      runCount: model.run_count,
      isOfficial: model.is_official ?? false,
      coverImageUrl: model.cover_image_url,
      inputSchema: null,
      outputSchema: null,
      lastSynced: Date.now(),
    };
  }

  // --- Query methods ---

  getModel(owner: string, name: string): RegisteredModel | null {
    return this.data.models[`${owner}/${name}`] ?? null;
  }

  listModels(options?: {
    collection?: string;
    limit?: number;
    offset?: number;
  }): { models: RegisteredModel[]; total: number } {
    let models = Object.values(this.data.models);

    if (options?.collection) {
      models = models.filter(m => m.collections.includes(options.collection!));
    }

    models.sort((a, b) => b.runCount - a.runCount);

    const total = models.length;
    const offset = options?.offset ?? 0;
    const limit = options?.limit ?? 50;
    models = models.slice(offset, offset + limit);

    return { models, total };
  }

  searchModels(query: string, limit = 20): RegisteredModel[] {
    const q = query.toLowerCase();
    return Object.values(this.data.models)
      .filter(m =>
        m.id.toLowerCase().includes(q) ||
        m.description.toLowerCase().includes(q) ||
        m.collections.some(c => c.includes(q))
      )
      .sort((a, b) => b.runCount - a.runCount)
      .slice(0, limit);
  }

  getCollections(): { slug: string; tier: PricingTier; modelCount: number }[] {
    const counts = new Map<string, number>();
    for (const model of Object.values(this.data.models)) {
      for (const slug of model.collections) {
        counts.set(slug, (counts.get(slug) ?? 0) + 1);
      }
    }

    return Array.from(counts.entries())
      .map(([slug, modelCount]) => ({
        slug,
        tier: COLLECTION_TIER_MAP[slug] ?? ('utility' as PricingTier),
        modelCount,
      }))
      .sort((a, b) => b.modelCount - a.modelCount);
  }

  getModelCount(): number {
    return Object.keys(this.data.models).length;
  }

  /**
   * Get the DRAIN cost in USDC wei for a model (with markup).
   */
  getModelCost(owner: string, name: string): bigint {
    const model = this.getModel(owner, name);
    const tier = model?.pricingTier ?? 'utility';
    const basePrice = PRICING_TIERS[tier].priceUsdc;
    const withMarkup = basePrice * (1 + this.markupPercent / 100);
    return BigInt(Math.ceil(withMarkup * 1_000_000));
  }

  /**
   * Get the pricing tier for a model (falls back to 'utility').
   */
  getModelTier(owner: string, name: string): PricingTier {
    return this.getModel(owner, name)?.pricingTier ?? 'utility';
  }

  // --- Lifecycle ---

  startPeriodicSync(intervalHours: number): void {
    if (this.syncInterval) return;

    const ms = intervalHours * 3600_000;
    console.log(`[registry] Periodic sync every ${intervalHours}h`);

    this.syncInterval = setInterval(() => {
      this.syncAll().catch(err => console.error('[registry] Periodic sync failed:', err));
    }, ms);
  }

  stopPeriodicSync(): void {
    if (this.syncInterval) {
      clearInterval(this.syncInterval);
      this.syncInterval = null;
    }
  }
}
