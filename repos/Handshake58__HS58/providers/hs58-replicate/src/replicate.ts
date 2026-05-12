/**
 * Replicate API Client
 *
 * Handles predictions (create, poll, sync mode), model schema lookups,
 * and collection fetching. Caches schemas in memory.
 */

import { REPLICATE_API_BASE } from './constants.js';
import type {
  ReplicateCollectionResponse,
  ReplicateModelResponse,
  ReplicateModelVersion,
  ReplicatePrediction,
} from './types.js';

export class ReplicateClient {
  private token: string;
  private pollIntervalMs: number;
  private maxTimeoutMs: number;
  private schemaCache = new Map<string, { input: Record<string, unknown> | null; output: Record<string, unknown> | null; cachedAt: number }>();
  private schemaCacheTtlMs = 3600_000;

  constructor(token: string, pollIntervalMs = 3000, maxTimeoutMs = 600_000) {
    this.token = token;
    this.pollIntervalMs = pollIntervalMs;
    this.maxTimeoutMs = maxTimeoutMs;
  }

  private get headers(): Record<string, string> {
    return {
      'Authorization': `Bearer ${this.token}`,
      'Content-Type': 'application/json',
    };
  }

  // --- Models & Schemas ---

  async getModel(owner: string, name: string): Promise<ReplicateModelResponse> {
    const res = await fetch(`${REPLICATE_API_BASE}/models/${owner}/${name}`, {
      headers: this.headers,
      signal: AbortSignal.timeout(15_000),
    });
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(`Replicate GET model ${owner}/${name}: ${res.status} ${text.slice(0, 200)}`);
    }
    return await res.json() as ReplicateModelResponse;
  }

  async getModelSchema(owner: string, name: string): Promise<{ input: Record<string, unknown> | null; output: Record<string, unknown> | null }> {
    const key = `${owner}/${name}`;
    const cached = this.schemaCache.get(key);
    if (cached && Date.now() - cached.cachedAt < this.schemaCacheTtlMs) {
      return { input: cached.input, output: cached.output };
    }

    const model = await this.getModel(owner, name);
    const schemas = model.latest_version?.openapi_schema?.components?.schemas;
    const result = {
      input: (schemas?.Input as Record<string, unknown>) ?? null,
      output: (schemas?.Output as Record<string, unknown>) ?? null,
    };

    this.schemaCache.set(key, { ...result, cachedAt: Date.now() });
    return result;
  }

  async getModelVersion(owner: string, name: string): Promise<ReplicateModelVersion | null> {
    const model = await this.getModel(owner, name);
    return model.latest_version ?? null;
  }

  // --- Collections ---

  async getCollection(slug: string): Promise<ReplicateCollectionResponse> {
    const res = await fetch(`${REPLICATE_API_BASE}/collections/${slug}`, {
      headers: this.headers,
      signal: AbortSignal.timeout(30_000),
    });
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(`Replicate GET collection ${slug}: ${res.status} ${text.slice(0, 200)}`);
    }
    return await res.json() as ReplicateCollectionResponse;
  }

  async listCollections(): Promise<{ name: string; slug: string; description: string }[]> {
    const res = await fetch(`${REPLICATE_API_BASE}/collections`, {
      headers: this.headers,
      signal: AbortSignal.timeout(15_000),
    });
    if (!res.ok) throw new Error(`Replicate GET collections: ${res.status}`);
    const data = await res.json() as { results: { name: string; slug: string; description: string }[] };
    return data.results;
  }

  // --- Predictions ---

  async createPrediction(
    owner: string,
    name: string,
    input: Record<string, unknown>,
    preferWait = true,
  ): Promise<ReplicatePrediction> {
    const url = `${REPLICATE_API_BASE}/models/${owner}/${name}/predictions`;
    const headers: Record<string, string> = { ...this.headers };
    if (preferWait) {
      headers['Prefer'] = 'wait=60';
    }

    const res = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify({ input }),
      signal: AbortSignal.timeout(preferWait ? 70_000 : 15_000),
    });

    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(`Replicate prediction ${owner}/${name}: ${res.status} ${text.slice(0, 300)}`);
    }

    return await res.json() as ReplicatePrediction;
  }

  async getPrediction(id: string): Promise<ReplicatePrediction> {
    const res = await fetch(`${REPLICATE_API_BASE}/predictions/${id}`, {
      headers: this.headers,
      signal: AbortSignal.timeout(15_000),
    });
    if (!res.ok) throw new Error(`Replicate GET prediction ${id}: ${res.status}`);
    return await res.json() as ReplicatePrediction;
  }

  /**
   * Create a prediction and poll until terminal state.
   * Uses sync mode first (Prefer: wait=60), then polls if needed.
   */
  async runPrediction(
    owner: string,
    name: string,
    input: Record<string, unknown>,
  ): Promise<ReplicatePrediction> {
    let prediction = await this.createPrediction(owner, name, input, true);

    if (prediction.status === 'succeeded' || prediction.status === 'failed' || prediction.status === 'canceled') {
      return prediction;
    }

    const deadline = Date.now() + this.maxTimeoutMs;

    while (Date.now() < deadline) {
      await sleep(this.pollIntervalMs);

      prediction = await this.getPrediction(prediction.id);
      console.log(`[replicate] ${prediction.id} status=${prediction.status}`);

      if (prediction.status === 'succeeded' || prediction.status === 'failed' || prediction.status === 'canceled') {
        return prediction;
      }
    }

    throw new TimeoutError(
      `Prediction ${prediction.id} did not complete within ${this.maxTimeoutMs / 1000}s`,
    );
  }
}

class TimeoutError extends Error {
  override name = 'TimeoutError';
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}
