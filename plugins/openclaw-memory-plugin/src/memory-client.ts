/**
 * Lightweight HTTP client for the ContextAgent memory tool endpoints.
 * Uses the /context (recall) and /context/write (store) bridge endpoints.
 */

import type { ContextAgentMemoryConfig } from "./memory-config.js";

export interface MemoryItem {
  id: string;
  content: string;
  score?: number;
}

interface RecallResponse {
  items: MemoryItem[];
  token_count: number;
}

interface WriteResponse {
  item_id: string;
  status: string;
}

export class ContextAgentMemoryClient {
  private readonly baseUrl: string;
  private readonly headers: Record<string, string>;
  private readonly timeoutMs: number;

  constructor(config: ContextAgentMemoryConfig) {
    this.baseUrl = config.baseUrl;
    this.timeoutMs = config.timeoutMs;
    this.headers = {
      "Content-Type": "application/json",
      ...(config.apiKey ? { Authorization: `Bearer ${config.apiKey}` } : {}),
    };
  }

  async recall(
    scopeId: string,
    sessionId: string,
    query: string,
    topK: number,
    minScore?: number,
  ): Promise<RecallResponse> {
    return this._post<RecallResponse>("/context", {
      scope_id: scopeId,
      session_id: sessionId,
      query,
      top_k: topK,
      min_score: minScore,
    });
  }

  async store(
    scopeId: string,
    sessionId: string,
    content: string,
    memoryType: string,
  ): Promise<WriteResponse> {
    return this._post<WriteResponse>("/context/write", {
      scope_id: scopeId,
      session_id: sessionId,
      content,
      memory_type: memoryType,
      source: "openclaw-memory-plugin",
    });
  }

  async forget(scopeId: string, itemId: string): Promise<void> {
    await this._post<{ status: string }>("/context/delete", {
      scope_id: scopeId,
      item_id: itemId,
    });
  }

  private async _post<T>(path: string, body: unknown): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const res = await fetch(`${this.baseUrl}${path}`, {
        method: "POST",
        headers: this.headers,
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(`ContextAgent ${path} → HTTP ${res.status}: ${text}`);
      }
      return (await res.json()) as T;
    } finally {
      clearTimeout(timer);
    }
  }
}
