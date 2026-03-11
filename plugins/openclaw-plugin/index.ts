/**
 * ContextAgent OpenClaw plugin entry point.
 *
 * Integrates ContextAgent into OpenClaw via the hooks API:
 *   - before_prompt_build : fetch relevant context → prependContext
 *   - agent_end           : persist conversation turn to ContextAgent
 *
 * Plugin loading:
 *   OpenClaw discovers this file via package.json:
 *     "openclaw": { "extensions": ["./index.ts"] }
 *
 * Activation (openclaw config):
 *   plugins:
 *     entries:
 *       context-agent:
 *         enabled: true
 *         config:
 *           baseUrl: "http://localhost:8000"
 *           scopeId: "my-channel"
 */

import type {
  OpenClawPluginApi,
  PluginHookBeforePromptBuildEvent,
  PluginHookAgentContext,
  PluginHookAgentEndEvent,
} from "openclaw/plugin-sdk";
import { parseConfig } from "./src/config.js";
import { ContextAgentClient } from "./src/client.js";

const plugin = {
  id: "context-agent",
  name: "ContextAgent",
  description:
    "Enriches each agent turn with relevant context retrieved from ContextAgent. " +
    "Provides tiered memory, hybrid retrieval, and hotness-scored injection.",

  register(api: OpenClawPluginApi) {
    const config = parseConfig(api.pluginConfig);
    const client = new ContextAgentClient(config);

    // ── Inject context before each LLM call ──────────────────────────────────
    api.on(
      "before_prompt_build",
      async (event: PluginHookBeforePromptBuildEvent, ctx: PluginHookAgentContext) => {
        try {
          const sessionId = ctx.sessionId ?? ctx.sessionKey ?? "default";
          const result = await client.retrieveContext({
            scope_id: config.scopeId,
            session_id: sessionId,
            query: event.prompt,
            token_budget: config.contextTokenBudget,
            top_k: config.topK,
            mode: config.retrievalMode,
          });

          if (result?.output?.content) {
            api.logger.info(
              `[context-agent] injected context (${result.output.content.length} chars, session=${sessionId})`
            );
            return { prependContext: result.output.content };
          }
        } catch (err) {
          // Non-fatal: log and continue without context injection
          api.logger.warn(`[context-agent] context retrieval failed: ${String(err)}`);
        }
      }
    );

    // ── Persist conversation turn after agent finishes ────────────────────────
    api.on(
      "agent_end",
      async (event: PluginHookAgentEndEvent, ctx: PluginHookAgentContext) => {
        if (!event.success) return;
        try {
          const sessionId = ctx.sessionId ?? ctx.sessionKey ?? "default";
          // Extract the last user+assistant exchange from messages
          const messages = event.messages as Array<{ role?: string; content?: string }>;
          const lastUser = [...messages].reverse().find((m) => m.role === "user");
          const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");
          if (lastUser?.content || lastAssistant?.content) {
            await client.writeContext({
              scope_id: config.scopeId,
              session_id: sessionId,
              content: [lastUser?.content, lastAssistant?.content]
                .filter(Boolean)
                .join("\n\n"),
              source_type: "conversation",
            });
          }
        } catch (err) {
          api.logger.warn(`[context-agent] context write failed: ${String(err)}`);
        }
      }
    );

    api.logger.info(
      `[context-agent] Plugin registered — baseUrl=${config.baseUrl} scope=${config.scopeId} mode=${config.retrievalMode}`
    );
  },
};

export default plugin;
