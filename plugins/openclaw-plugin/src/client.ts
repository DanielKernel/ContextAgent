/**
 * HTTP client for the ContextAgent bridge API.
 *
 * Uses the Node.js native `fetch` (available in Node ≥ 18) with bearer-token
 * auth and configurable timeout.  All methods throw on non-2xx responses.
 */

import type { ContextAgentConfig } from "./config.js";

/** A single turn message in the OpenClaw conversation history. */
export interface AgentMessage {
  role: "user" | "assistant" | "system";
  content: string;
  metadata?: Record<string, unknown>;
}

// ── Request / Response shapes (mirrors openclaw_schemas.py) ──────────────────

interface BootstrapResponse {
  status: string;
  items_loaded: number;
}

interface IngestResponse {
  status: string;
  ingested_count: number;
}

export interface AssembleResponse {
  messages: AgentMessage[];
  system_prompt_addition: string;
  context_item_ids: string[];
  estimated_tokens: number;
}

export interface CompactResponse {
  messages: AgentMessage[];
  tokens_before: number;
  tokens_after: number;
  status: string;
  summary?: string;
}

interface AfterTurnResponse {
  status: string;
  updated_count: number;
}

// ── Client ────────────────────────────────────────────────────────────────────

export class ContextAgentClient {
  private readonly baseUrl: string;
  private readonly headers: Record<string, string>;
  private readonly timeoutMs: number;

  constructor(config: ContextAgentConfig) {
    this.baseUrl = config.baseUrl;
    this.timeoutMs = config.timeoutMs;
    this.headers = {
      "Content-Type": "application/json",
      ...(config.apiKey ? { Authorization: `Bearer ${config.apiKey}` } : {}),
    };
  }

  async bootstrap(
    scopeId: string,
    sessionId: string,
    messages: AgentMessage[]
  ): Promise<BootstrapResponse> {
    return this._post<BootstrapResponse>("/v1/openclaw/bootstrap", {
      scope_id: scopeId,
      session_id: sessionId,
      messages,
    });
  }

  async ingest(
    scopeId: string,
    sessionId: string,
    messages: AgentMessage[]
  ): Promise<IngestResponse> {
    return this._post<IngestResponse>("/v1/openclaw/ingest", {
      scope_id: scopeId,
      session_id: sessionId,
      messages,
    });
  }

  async assemble(
    scopeId: string,
    sessionId: string,
    messages: AgentMessage[],
    opts: {
      tokenBudget: number;
      topK: number;
      mode: "fast" | "quality";
      minScore?: number;
    }
  ): Promise<AssembleResponse> {
    return this._post<AssembleResponse>("/v1/openclaw/assemble", {
      scope_id: scopeId,
      session_id: sessionId,
      messages,
      token_budget: opts.tokenBudget,
      top_k: opts.topK,
      mode: opts.mode,
      min_score: opts.minScore,
    });
  }

  async compact(
    scopeId: string,
    sessionId: string,
    messages: AgentMessage[],
    tokenLimit: number,
    opts?: {
      force?: boolean;
      compactionTarget?: "budget" | "threshold";
      customInstructions?: string;
    }
  ): Promise<CompactResponse> {
    return this._post<CompactResponse>("/v1/openclaw/compact", {
      scope_id: scopeId,
      session_id: sessionId,
      messages,
      token_limit: tokenLimit,
      force: opts?.force,
      compaction_target: opts?.compactionTarget,
      custom_instructions: opts?.customInstructions,
    });
  }

  async afterTurn(
    scopeId: string,
    sessionId: string,
    assistantMessage: AgentMessage,
    usedContextItemIds: string[]
  ): Promise<AfterTurnResponse> {
    return this._post<AfterTurnResponse>("/v1/openclaw/after-turn", {
      scope_id: scopeId,
      session_id: sessionId,
      assistant_message: assistantMessage,
      used_context_item_ids: usedContextItemIds,
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
