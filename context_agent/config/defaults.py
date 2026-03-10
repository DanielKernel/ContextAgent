"""Default threshold constants.

All tuneable values that affect runtime behaviour but are not env-config
are declared here so they can be imported without triggering Settings I/O.
"""

# ── Tier TTLs (seconds) ──────────────────────────────────────────────────────
HOT_TIER_TTL_S: int = 300        # 5 min – current session state
WARM_TIER_TTL_S: int = 3_600     # 1 h – recent episodic / summary
COLD_TIER_TTL_S: int = 86_400    # 24 h – stable semantic knowledge

# ── JIT resolver result cache ────────────────────────────────────────────────
JIT_RESULT_CACHE_TTL_S: int = 60

# ── Token budgets ─────────────────────────────────────────────────────────────
DEFAULT_TOKEN_BUDGET: int = 4_096
SYSTEM_PROMPT_TOKEN_RESERVE: int = 512
TOOL_RESULT_TOKEN_LIMIT: int = 1_024

# ── Compression triggers ──────────────────────────────────────────────────────
COMPACTION_TRIGGER_RATIO: float = 0.85  # trigger when usage > 85% of budget

# ── Retrieval ─────────────────────────────────────────────────────────────────
DEFAULT_TOP_K: int = 10
RERANK_TOP_K: int = 5
HYBRID_VECTOR_WEIGHT: float = 0.6
HYBRID_SPARSE_WEIGHT: float = 0.4

# ── Monitoring ────────────────────────────────────────────────────────────────
METRIC_FLUSH_INTERVAL_S: float = 10.0
ALERT_COOLDOWN_S: float = 300.0  # 5 min between repeated alerts

# ── Health check risk score thresholds ───────────────────────────────────────
HEALTH_POISONING_THRESHOLD: float = 0.7
HEALTH_DISTRACTION_THRESHOLD: float = 0.5
HEALTH_CONFUSION_THRESHOLD: float = 0.4
HEALTH_CLASH_THRESHOLD: float = 0.6

# ── Working memory ────────────────────────────────────────────────────────────
MAX_NOTES_PER_SESSION: int = 100

# ── Sub-agent ────────────────────────────────────────────────────────────────
MAX_HANDOFF_SUMMARY_TOKENS: int = 512

# ── Aggregation ───────────────────────────────────────────────────────────────
AGGREGATION_TIMEOUT_MS: float = 200.0   # UC001: 200ms deadline

# ── Tool governor ─────────────────────────────────────────────────────────────
TOOL_RAG_THRESHOLD: int = 20   # use RAG selection when toolset exceeds this
TOOL_TOP_K: int = 10
