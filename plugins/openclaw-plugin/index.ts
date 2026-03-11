/**
 * ContextAgent OpenClaw plugin entry point.
 *
 * Registers ContextAgentEngine as the "context-agent" context engine.
 *
 * Plugin loading:
 *   OpenClaw discovers this file via package.json:
 *     "openclaw": { "extensions": ["./index.ts"] }
 *
 * User activation (openclaw config.yaml):
 *   plugins:
 *     slots:
 *       contextEngine: "context-agent"
 *     entries:
 *       context-agent:
 *         enabled: true
 *         config:
 *           baseUrl: "http://localhost:8000"
 *           scopeId: "my-channel"
 */

import type { OpenClawPluginApi } from "openclaw/plugin-sdk";
import { ContextAgentEngine } from "./src/engine.js";
import { parseConfig } from "./src/config.js";

const plugin = {
  id: "context-agent",
  name: "ContextAgent",
  description:
    "Delegates all context management to a remote ContextAgent HTTP service. " +
    "Provides tiered memory, hybrid retrieval, hotness scoring, and compression.",

  configSchema: {
    parse: parseConfig,
  },

  register(api: OpenClawPluginApi) {
    const config = parseConfig(api.pluginConfig);
    const engine = new ContextAgentEngine(config);

    api.registerContextEngine("context-agent", () => engine);

    api.logger.info(
      `[context-agent] Plugin registered — baseUrl=${config.baseUrl} scope=${config.scopeId} mode=${config.retrievalMode}`
    );
  },
};

export default plugin;
