/**
 * ContextAgentEngine — implements the OpenClaw ContextEngine interface.
 *
 * All lifecycle methods delegate to the ContextAgent HTTP service via
 * ContextAgentClient.  The session ID is mapped from OpenClaw's `sessionId`;
 * the scope ID comes from plugin config.
 *
 * OpenClaw calling sequence (from attempt.ts):
 *
 *   bootstrap()  — when hadSessionFile=true (existing session)
 *   ingest()     — single-message ingestion (Required; fallback from afterTurn)
 *   assemble()   — after sanitize/validate/limit pipeline, before LLM call
 *   afterTurn()  — after each completed turn
 *   compact()    — on token overflow (always fires regardless of ownsCompaction)
 *   dispose()    — in finally block when run ends
 *
 * ContextAgent uses Mode B for assemble():
 *   - messages are returned unchanged
 *   - retrieved context is returned as systemPromptAddition (prepended to system prompt)
 */

import { readFile } from "node:fs/promises";
import type { ContextAgentConfig } from "./config.js";
import { ContextAgentClient, type AgentMessage } from "./client.js";

// ── OpenClaw type stubs (resolved from openclaw peer dep at runtime) ──────────
// Aligned with src/context-engine/types.ts from openclaw/openclaw

interface ContextEngineInfo {
  /** When true, OpenClaw skips its built-in Pi auto-compaction. */
  ownsCompaction: boolean;
}

interface AssembleResult {
  messages: AgentMessage[];
  estimatedTokens: number;
  systemPromptAddition?: string;
}

interface CompactResult {
  ok: boolean;
  compacted: boolean;
  reason?: string;
  result?: {
    summary?: string;
    firstKeptEntryId?: string;
    tokensBefore: number;
    tokensAfter?: number;
    details?: unknown;
  };
}

interface IngestResult {
  ingested: boolean;
}

interface IngestBatchResult {
  ingestedCount: number;
}

interface BootstrapResult {
  bootstrapped: boolean;
  importedMessages?: number;
  reason?: string;
}

interface ContextEngineRuntimeContext {
  [key: string]: unknown;
}

export interface ContextEngine {
  /** Static info about this engine (property, NOT a method). */
  readonly info: ContextEngineInfo;

  bootstrap?(params: { sessionId: string; sessionFile: string }): Promise<BootstrapResult>;

  /** Required: ingest a single message. */
  ingest(params: { sessionId: string; message: AgentMessage; isHeartbeat?: boolean }): Promise<IngestResult>;

  /** Optional: ingest a batch of messages atomically (preferred over repeated ingest). */
  ingestBatch?(params: { sessionId: string; messages: AgentMessage[]; isHeartbeat?: boolean }): Promise<IngestBatchResult>;

  afterTurn?(params: {
    sessionId: string;
    sessionFile: string;
    messages: AgentMessage[];
    prePromptMessageCount: number;
    autoCompactionSummary?: string;
    isHeartbeat?: boolean;
    tokenBudget?: number;
    runtimeContext?: ContextEngineRuntimeContext;
  }): Promise<void>;

  assemble(params: { sessionId: string; messages: AgentMessage[]; tokenBudget?: number }): Promise<AssembleResult>;

  compact(params: {
    sessionId: string;
    sessionFile: string;
    tokenBudget?: number;
    force?: boolean;
    currentTokenCount?: number;
    compactionTarget?: "budget" | "threshold";
    customInstructions?: string;
    runtimeContext?: ContextEngineRuntimeContext;
  }): Promise<CompactResult>;

  dispose?(): Promise<void>;
}

// ── Session file helpers ───────────────────────────────────────────────────────

/** Read a session JSON file and extract its messages array. */
async function readSessionMessages(sessionFile: string): Promise<AgentMessage[]> {
  try {
    const raw = await readFile(sessionFile, "utf-8");
    const parsed = JSON.parse(raw) as { messages?: AgentMessage[] };
    return Array.isArray(parsed.messages) ? parsed.messages : [];
  } catch {
    return [];
  }
}

// ── Engine ────────────────────────────────────────────────────────────────────

export class ContextAgentEngine implements ContextEngine {
  // Property (not method) — OpenClaw reads engine.info.ownsCompaction
  readonly info: ContextEngineInfo = {
    // ContextAgent owns compaction — suppresses OpenClaw's built-in Pi auto-compaction.
    ownsCompaction: true,
  };

  private readonly client: ContextAgentClient;
  private readonly config: ContextAgentConfig;
  // Carries context item IDs from assemble() to afterTurn() within a single turn
  private _pendingItemIds: string[] = [];

  constructor(config: ContextAgentConfig) {
    this.config = config;
    this.client = new ContextAgentClient(config);
  }

  async bootstrap(params: { sessionId: string; sessionFile: string }): Promise<BootstrapResult> {
    try {
      const messages = await readSessionMessages(params.sessionFile);
      const result = await this.client.bootstrap(
        this.config.scopeId,
        params.sessionId,
        messages,
      );
      return {
        bootstrapped: true,
        importedMessages: result.items_loaded,
      };
    } catch (err) {
      // Non-fatal: log and continue. OpenClaw must not fail on bootstrap errors.
      console.warn("[context-agent] bootstrap failed:", err);
      return { bootstrapped: false, reason: String(err) };
    }
  }

  /** Required: single-message ingestion. Called as fallback when afterTurn is absent. */
  async ingest(params: { sessionId: string; message: AgentMessage; isHeartbeat?: boolean }): Promise<IngestResult> {
    try {
      await this.client.ingest(
        this.config.scopeId,
        params.sessionId,
        [params.message],
      );
      return { ingested: true };
    } catch (err) {
      console.warn("[context-agent] ingest failed:", err);
      return { ingested: false };
    }
  }

  async assemble(params: {
    sessionId: string;
    messages: AgentMessage[];
    tokenBudget?: number;
  }): Promise<AssembleResult> {
    try {
      const result = await this.client.assemble(
        this.config.scopeId,
        params.sessionId,
        params.messages,
        {
          tokenBudget: params.tokenBudget ?? this.config.contextTokenBudget,
          topK: this.config.topK,
          mode: this.config.retrievalMode,
          minScore: this.config.minScore,
        },
      );
      // Store item IDs for afterTurn() Hotness Score feedback
      this._pendingItemIds = result.context_item_ids;

      return {
        messages: params.messages, // Mode B: pass messages through unchanged
        estimatedTokens: result.estimated_tokens,
        systemPromptAddition: result.system_prompt_addition || undefined,
      };
    } catch (err) {
      console.warn("[context-agent] assemble failed:", err);
      return {
        messages: params.messages,
        estimatedTokens: params.messages.reduce((s, m) => s + Math.ceil(m.content.length / 4), 0),
      };
    }
  }

  async afterTurn(params: {
    sessionId: string;
    sessionFile: string;
    messages: AgentMessage[];
    prePromptMessageCount: number;
    autoCompactionSummary?: string;
    isHeartbeat?: boolean;
    tokenBudget?: number;
    runtimeContext?: ContextEngineRuntimeContext;
  }): Promise<void> {
    try {
      // New messages are the ones added after prePromptMessageCount
      const newMessages = params.messages.slice(params.prePromptMessageCount);
      const assistantMsg = [...newMessages].reverse().find((m) => m.role === "assistant");
      if (!assistantMsg) return;

      await this.client.afterTurn(
        this.config.scopeId,
        params.sessionId,
        assistantMsg,
        this._pendingItemIds,
      );
      this._pendingItemIds = [];
    } catch (err) {
      console.warn("[context-agent] afterTurn failed:", err);
    }
  }

  async compact(params: {
    sessionId: string;
    sessionFile: string;
    tokenBudget?: number;
    force?: boolean;
    currentTokenCount?: number;
    compactionTarget?: "budget" | "threshold";
    customInstructions?: string;
    runtimeContext?: ContextEngineRuntimeContext;
  }): Promise<CompactResult> {
    try {
      const messages = await readSessionMessages(params.sessionFile);
      const tokenLimit = params.tokenBudget ?? params.currentTokenCount ?? 8192;

      const result = await this.client.compact(
        this.config.scopeId,
        params.sessionId,
        messages,
        tokenLimit,
        {
          force: params.force,
          compactionTarget: params.compactionTarget,
          customInstructions: params.customInstructions,
        },
      );

      return {
        ok: result.status === "ok",
        compacted: result.tokens_after < result.tokens_before,
        result: {
          tokensBefore: result.tokens_before,
          tokensAfter: result.tokens_after,
          summary: result.summary,
        },
      };
    } catch (err) {
      console.warn("[context-agent] compact failed:", err);
      return {
        ok: false,
        compacted: false,
        reason: String(err),
      };
    }
  }

  async dispose(): Promise<void> {
    this._pendingItemIds = [];
  }
}
