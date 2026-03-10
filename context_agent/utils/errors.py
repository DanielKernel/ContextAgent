"""Error codes and exception hierarchy for ContextAgent.

Error code format: CA-XXX
  CA-0xx  General / internal errors
  CA-1xx  Input validation errors
  CA-2xx  Adapter / external system errors
  CA-3xx  Retrieval errors
  CA-4xx  Compression / memory errors
  CA-5xx  Authorization / policy errors
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    # General
    INTERNAL_ERROR = "CA-001"
    TIMEOUT = "CA-002"
    NOT_IMPLEMENTED = "CA-003"
    CONFIGURATION_ERROR = "CA-004"

    # Validation
    INVALID_SCOPE_ID = "CA-101"
    INVALID_OUTPUT_TYPE = "CA-102"
    INVALID_REF_TYPE = "CA-103"
    MISSING_REQUIRED_FIELD = "CA-104"
    INVALID_POLICY = "CA-105"

    # Adapter / external
    OPENJIUWEN_UNAVAILABLE = "CA-201"
    REDIS_UNAVAILABLE = "CA-202"
    VECTOR_DB_UNAVAILABLE = "CA-203"
    OBJECT_STORE_UNAVAILABLE = "CA-204"
    LLM_SERVICE_ERROR = "CA-205"
    GRAPH_DB_UNAVAILABLE = "CA-206"
    ADAPTER_MAPPING_ERROR = "CA-207"

    # Retrieval
    RETRIEVAL_FAILED = "CA-301"
    NO_RESULTS_FOUND = "CA-302"
    RERANK_FAILED = "CA-303"
    BUDGET_EXCEEDED = "CA-304"

    # Compression / memory
    COMPRESSION_FAILED = "CA-401"
    STRATEGY_NOT_FOUND = "CA-402"
    MEMORY_WRITE_FAILED = "CA-403"
    MEMORY_READ_FAILED = "CA-404"
    VERSION_NOT_FOUND = "CA-405"
    NOTE_NOT_FOUND = "CA-406"

    # Auth / policy
    UNAUTHORIZED = "CA-501"
    POLICY_VIOLATION = "CA-502"
    SCOPE_MISMATCH = "CA-503"


class ContextAgentError(Exception):
    """Base exception for all ContextAgent errors."""

    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}

    def __str__(self) -> str:
        return f"[{self.code}] {super().__str__()}"


class TimeoutError(ContextAgentError):
    def __init__(self, operation: str, timeout_ms: float) -> None:
        super().__init__(
            f"Operation '{operation}' timed out after {timeout_ms:.0f}ms",
            code=ErrorCode.TIMEOUT,
            details={"operation": operation, "timeout_ms": timeout_ms},
        )


class AdapterError(ContextAgentError):
    """Raised when an external adapter call fails."""

    def __init__(self, adapter: str, cause: str, code: ErrorCode = ErrorCode.ADAPTER_MAPPING_ERROR) -> None:
        super().__init__(
            f"Adapter '{adapter}' error: {cause}",
            code=code,
            details={"adapter": adapter, "cause": cause},
        )


class RetrievalError(ContextAgentError):
    def __init__(self, message: str, code: ErrorCode = ErrorCode.RETRIEVAL_FAILED) -> None:
        super().__init__(message, code=code)


class CompressionError(ContextAgentError):
    def __init__(self, message: str, strategy_id: str = "") -> None:
        super().__init__(message, code=ErrorCode.COMPRESSION_FAILED, details={"strategy_id": strategy_id})


class StrategyNotFoundError(ContextAgentError):
    def __init__(self, strategy_id: str) -> None:
        super().__init__(
            f"Compression strategy '{strategy_id}' not registered",
            code=ErrorCode.STRATEGY_NOT_FOUND,
            details={"strategy_id": strategy_id},
        )


class PolicyViolationError(ContextAgentError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason, code=ErrorCode.POLICY_VIOLATION)


class UnauthorizedError(ContextAgentError):
    def __init__(self, scope_id: str = "") -> None:
        super().__init__(
            f"Unauthorized access for scope '{scope_id}'",
            code=ErrorCode.UNAUTHORIZED,
            details={"scope_id": scope_id},
        )
