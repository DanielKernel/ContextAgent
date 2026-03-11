/**
 * Configuration schema for the ContextAgent memory plugin.
 */

export interface ContextAgentMemoryConfig {
  /** Base URL of the ContextAgent HTTP service. */
  baseUrl: string;
  /** Optional bearer token for authentication. */
  apiKey?: string;
  /** Scope ID for memory isolation. */
  scopeId: string;
  /** HTTP request timeout in milliseconds. */
  timeoutMs: number;
  /** Minimum relevance score for recalled memories (0–1). */
  autoRecallMinScore: number;
  /** Whether to automatically recall memories before each turn. */
  autoRecall: boolean;
  /** Number of memories to auto-recall per turn. */
  autoRecallTopK: number;
  /** Whether to automatically capture the assistant reply as a memory after each turn. */
  autoCapture: boolean;
}

export function parseMemoryConfig(value: unknown): ContextAgentMemoryConfig {
  const v = (value ?? {}) as Record<string, unknown>;
  const baseUrl = typeof v["baseUrl"] === "string" ? v["baseUrl"] : "http://localhost:8000";
  const apiKey = typeof v["apiKey"] === "string" ? v["apiKey"] : undefined;
  const scopeId = typeof v["scopeId"] === "string" ? v["scopeId"] : "openclaw";
  const timeoutMs = typeof v["timeoutMs"] === "number" ? v["timeoutMs"] : 5000;
  const autoRecallMinScore =
    typeof v["autoRecallMinScore"] === "number" ? v["autoRecallMinScore"] : 0.01;
  const autoRecall = typeof v["autoRecall"] === "boolean" ? v["autoRecall"] : true;
  const autoRecallTopK = typeof v["autoRecallTopK"] === "number" ? v["autoRecallTopK"] : 5;
  const autoCapture = typeof v["autoCapture"] === "boolean" ? v["autoCapture"] : false;

  return { baseUrl, apiKey, scopeId, timeoutMs, autoRecallMinScore, autoRecall, autoRecallTopK, autoCapture };
}
