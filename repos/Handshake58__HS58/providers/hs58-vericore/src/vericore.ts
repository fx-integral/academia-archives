/**
 * Vericore API Client
 *
 * Wraps the Vericore Claim Analyzer API at
 * https://api.integration.vericore.dfusion.ai/calculate-rating/v2
 */

import type { VericoreResponse } from './types.js';

export class VericoreService {
  private apiUrl: string;
  private apiKey: string;
  private timeoutMs: number;

  constructor(apiUrl: string, apiKey: string, timeoutMs: number = 90_000) {
    this.apiUrl = apiUrl;
    this.apiKey = apiKey;
    this.timeoutMs = timeoutMs;
  }

  async analyzeStatement(statement: string): Promise<VericoreResponse> {
    const res = await fetch(this.apiUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `api-key ${this.apiKey}`,
      },
      body: JSON.stringify({ statement }),
      signal: AbortSignal.timeout(this.timeoutMs),
    });

    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(`Vericore API ${res.status}: ${text.slice(0, 300)}`);
    }

    return await res.json() as VericoreResponse;
  }

  async healthCheck(): Promise<boolean> {
    try {
      const res = await fetch(this.apiUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `api-key ${this.apiKey}`,
        },
        body: JSON.stringify({ statement: 'health check' }),
        signal: AbortSignal.timeout(30_000),
      });
      return res.ok;
    } catch {
      return false;
    }
  }
}
