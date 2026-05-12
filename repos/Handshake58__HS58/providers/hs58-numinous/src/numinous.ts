/**
 * Numinous Forecasting API Client
 *
 * Wraps the Numinous prediction-jobs API at
 * https://api.numinouslabs.io/api/v1/forecasters/prediction-jobs
 *
 * Supports both structured mode (title/description/cutoff) and
 * query mode (natural language question). Jobs are asynchronous —
 * submit then poll until COMPLETED or FAILED.
 */

import type {
  NuminousCreateJobRequest,
  NuminousCreateJobResponse,
  NuminousPredictionResponse,
} from './types.js';

export class NuminousService {
  private baseUrl: string;
  private apiKey: string;
  private pollIntervalMs: number;
  private pollTimeoutMs: number;

  private get jobsUrl(): string {
    return `${this.baseUrl}/api/v1/forecasters/prediction-jobs`;
  }

  constructor(
    baseUrl: string,
    apiKey: string,
    pollIntervalMs: number = 5_000,
    pollTimeoutMs: number = 240_000,
  ) {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
    this.apiKey = apiKey;
    this.pollIntervalMs = pollIntervalMs;
    this.pollTimeoutMs = pollTimeoutMs;
  }

  async createPredictionJob(
    payload: NuminousCreateJobRequest,
  ): Promise<NuminousCreateJobResponse> {
    const res = await fetch(this.jobsUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': this.apiKey,
      },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(30_000),
    });

    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(`Numinous API ${res.status}: ${text.slice(0, 300)}`);
    }

    return (await res.json()) as NuminousCreateJobResponse;
  }

  async getPrediction(predictionId: string): Promise<NuminousPredictionResponse> {
    const res = await fetch(`${this.jobsUrl}/${predictionId}`, {
      method: 'GET',
      signal: AbortSignal.timeout(15_000),
    });

    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(`Numinous poll ${res.status}: ${text.slice(0, 300)}`);
    }

    return (await res.json()) as NuminousPredictionResponse;
  }

  /**
   * Submit a prediction job and poll until terminal state.
   * Returns the completed prediction or throws on failure/timeout.
   */
  async forecast(payload: NuminousCreateJobRequest): Promise<NuminousPredictionResponse> {
    const job = await this.createPredictionJob(payload);
    const predictionId = job.prediction_id;

    console.log(`[numinous] Job created: ${predictionId}`);

    const deadline = Date.now() + this.pollTimeoutMs;

    while (Date.now() < deadline) {
      await sleep(this.pollIntervalMs);

      const result = await this.getPrediction(predictionId);
      console.log(`[numinous] ${predictionId} status=${result.status}`);

      if (result.status === 'COMPLETED') {
        return result;
      }

      if (result.status === 'FAILED') {
        throw new Error(
          `Prediction failed: ${result.error ?? 'unknown error'}`,
        );
      }
    }

    throw new TimeoutError(
      `Prediction ${predictionId} did not complete within ${this.pollTimeoutMs / 1000}s`,
    );
  }

  /**
   * Parse user input into a Numinous request payload.
   * If the text is valid JSON with a "title" field → structured mode.
   * Otherwise → query mode with the raw text.
   */
  static parseUserInput(text: string): NuminousCreateJobRequest {
    try {
      const parsed = JSON.parse(text);
      if (parsed && typeof parsed === 'object' && typeof parsed.title === 'string') {
        return {
          title: parsed.title,
          description: parsed.description ?? '',
          cutoff: parsed.cutoff ?? '',
          ...(parsed.topics && { topics: parsed.topics }),
        };
      }
    } catch {
      // Not JSON — fall through to query mode
    }

    return { query: text };
  }
}

class TimeoutError extends Error {
  override name = 'TimeoutError';
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
