/**
 * ContextAgent OpenClaw Memory Plugin
 *
 * kind: "memory" — lightweight alternative to the context-engine plugin.
 *
 * Registers 3 tools the LLM can call explicitly:
 *   - memory_recall   : retrieve relevant memories for a query
 *   - memory_store    : write a new memory item
 *   - memory_forget   : delete a memory item by ID
 *
 * Registers 2 hooks for automatic operation:
 *   - before_agent_start : auto-inject recalled memories as prependContext
 *   - agent_end          : auto-capture the turn's assistant reply as a memory
 *
 * This plugin works alongside ANY context engine (including the context-agent
 * context-engine plugin).  Use it when you want memory tools available to the
 * LLM without taking full ownership of the context lifecycle.
 */

import type { OpenClawPluginApi } from "openclaw/plugin-sdk";
import { ContextAgentMemoryClient } from "./src/memory-client.js";
import { parseMemoryConfig } from "./src/memory-config.js";

const plugin = {
  id: "context-agent-memory",
  name: "ContextAgent Memory",
  description: "Tool-based memory recall and storage via ContextAgent",
  kind: "memory" as const,
  configSchema: { parse: parseMemoryConfig },

  register(api: OpenClawPluginApi) {
    const config = parseMemoryConfig(api.pluginConfig);
    const client = new ContextAgentMemoryClient(config);

    // ── Tool: memory_recall ──────────────────────────────────────────────────
    api.registerTool({
      name: "memory_recall",
      description:
        "Retrieve relevant memories from ContextAgent's knowledge base. " +
        "Use this when you need information about past interactions, user preferences, " +
        "project context, or any stored knowledge.",
      parameters: {
        type: "object",
        properties: {
          query: {
            type: "string",
            description: "Natural language query to search memories",
          },
          top_k: {
            type: "number",
            description: "Maximum number of memories to return (default: 5)",
          },
        },
        required: ["query"],
      },
      async execute({ query, top_k = 5 }: { query: string; top_k?: number }) {
        try {
          const sessionId = api.session?.id ?? "default";
          const results = await client.recall(config.scopeId, sessionId, query, top_k);
          if (results.items.length === 0) {
            return "No relevant memories found.";
          }
          return results.items
            .map((item, i) => `[${i + 1}] ${item.content}`)
            .join("\n\n");
        } catch (err) {
          api.logger.warn("[context-agent-memory] memory_recall failed:", String(err));
          return "Memory recall temporarily unavailable.";
        }
      },
    });

    // ── Tool: memory_store ───────────────────────────────────────────────────
    api.registerTool({
      name: "memory_store",
      description:
        "Store a new memory in ContextAgent's knowledge base. " +
        "Use this to remember important facts, decisions, user preferences, or context for future sessions.",
      parameters: {
        type: "object",
        properties: {
          content: {
            type: "string",
            description: "The content to remember",
          },
          memory_type: {
            type: "string",
            enum: ["variable", "invariant", "reference"],
            description:
              "Memory type: 'variable' (can change), 'invariant' (permanent facts), 'reference' (external links)",
          },
        },
        required: ["content"],
      },
      async execute({
        content,
        memory_type = "variable",
      }: {
        content: string;
        memory_type?: string;
      }) {
        try {
          const sessionId = api.session?.id ?? "default";
          const result = await client.store(config.scopeId, sessionId, content, memory_type);
          return `Memory stored with ID: ${result.item_id}`;
        } catch (err) {
          api.logger.warn("[context-agent-memory] memory_store failed:", String(err));
          return "Memory storage temporarily unavailable.";
        }
      },
    });

    // ── Tool: memory_forget ──────────────────────────────────────────────────
    api.registerTool({
      name: "memory_forget",
      description:
        "Delete a specific memory from ContextAgent's knowledge base by its ID. " +
        "Use this when a memory is outdated or incorrect.",
      parameters: {
        type: "object",
        properties: {
          item_id: {
            type: "string",
            description: "The ID of the memory to delete",
          },
        },
        required: ["item_id"],
      },
      async execute({ item_id }: { item_id: string }) {
        try {
          await client.forget(config.scopeId, item_id);
          return `Memory ${item_id} deleted.`;
        } catch (err) {
          api.logger.warn("[context-agent-memory] memory_forget failed:", String(err));
          return "Memory deletion temporarily unavailable.";
        }
      },
    });

    // ── Hook: before_agent_start — auto-inject recalled context ─────────────
    api.on("before_agent_start", async ({ messages, session }) => {
      if (!config.autoRecall) return {};
      try {
        const sessionId = session?.id ?? "default";
        const lastUserMsg = [...messages].reverse().find((m) => m.role === "user");
        if (!lastUserMsg?.content) return {};

        const results = await client.recall(
          config.scopeId,
          sessionId,
          lastUserMsg.content,
          config.autoRecallTopK,
          config.autoRecallMinScore,
        );
        if (results.items.length === 0) return {};

        const contextText = results.items
          .map((item) => `- ${item.content}`)
          .join("\n");
        return {
          prependContext: `# Recalled Memories\n${contextText}`,
        };
      } catch (err) {
        api.logger.warn("[context-agent-memory] before_agent_start recall failed:", String(err));
        return {};
      }
    });

    // ── Hook: agent_end — auto-capture assistant reply ───────────────────────
    api.on("agent_end", async ({ messages, session }) => {
      if (!config.autoCapture) return;
      try {
        const sessionId = session?.id ?? "default";
        const assistantMsg = [...messages].reverse().find((m) => m.role === "assistant");
        if (!assistantMsg?.content) return;

        await client.store(
          config.scopeId,
          sessionId,
          assistantMsg.content,
          "variable",
        );
      } catch (err) {
        api.logger.warn("[context-agent-memory] agent_end capture failed:", String(err));
      }
    });

    api.logger.info(
      `[context-agent-memory] Plugin loaded, baseUrl=${config.baseUrl}, autoRecall=${config.autoRecall}`,
    );
  },
};

export default plugin;
