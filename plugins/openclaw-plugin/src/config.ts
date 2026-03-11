/**
 * ContextAgent plugin configuration.
 */

export interface ContextAgentConfig {
  /** Base URL of the ContextAgent HTTP service (required). */
  baseUrl: string;
  /** Optional Bearer token for API authentication. */
  apiKey?: string;
  /** Logical scope ID that namespaces all memories for this OpenClaw instance. */
  scopeId: string;
  /** HTTP timeout in milliseconds. */
  timeoutMs: number;
  /** Maximum tokens to inject via systemPromptAddition. */
  contextTokenBudget: number;
  /** Retrieval mode: 'fast' (hybrid) or 'quality' (LLM-driven agentic). */
  retrievalMode: "fast" | "quality";
  /** Number of context items to retrieve per assemble() call. */
  topK: number;
  /** Minimum relevance score threshold for context items (0–1). Items below this are filtered out. */
  minScore: number;
}

const DEFAULTS: Omit<ContextAgentConfig, "baseUrl"> = {
  apiKey: "",
  scopeId: "openclaw",
  timeoutMs: 5000,
  contextTokenBudget: 2048,
  retrievalMode: "fast",
  topK: 8,
  minScore: 0.01,
};

export function parseConfig(value: unknown): ContextAgentConfig {
  if (typeof value !== "object" || value === null) {
    throw new Error("ContextAgent plugin config must be an object");
  }
  const raw = value as Record<string, unknown>;

  const baseUrl = (raw["baseUrl"] as string | undefined) ?? "";
  if (!baseUrl) {
    throw new Error("ContextAgent plugin config: 'baseUrl' is required");
  }

  return {
    baseUrl: baseUrl.replace(/\/$/, ""), // strip trailing slash
    apiKey: (raw["apiKey"] as string | undefined) ?? DEFAULTS.apiKey,
    scopeId: (raw["scopeId"] as string | undefined) ?? DEFAULTS.scopeId,
    timeoutMs: (raw["timeoutMs"] as number | undefined) ?? DEFAULTS.timeoutMs,
    contextTokenBudget:
      (raw["contextTokenBudget"] as number | undefined) ?? DEFAULTS.contextTokenBudget,
    retrievalMode:
      (raw["retrievalMode"] as "fast" | "quality" | undefined) ?? DEFAULTS.retrievalMode,
    topK: (raw["topK"] as number | undefined) ?? DEFAULTS.topK,
    minScore: (raw["minScore"] as number | undefined) ?? DEFAULTS.minScore,
  };
}
