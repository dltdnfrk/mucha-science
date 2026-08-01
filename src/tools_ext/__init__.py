"""External computational-tool adapter and invocation framework."""

from .adapter import ParsedResult, ToolAdapter
from .contract import InvocationRecord, StagedRunArtifact, ToolIdentity, ToolLimitation
from .invoker import InvocationConfig, InvocationResult, ToolInvoker
from .registry import AdapterRegistry, RegisteredAdapter
from .staging import StagingError, stage_run

__all__ = [
    "AdapterRegistry", "InvocationConfig", "InvocationRecord", "InvocationResult",
    "ParsedResult", "RegisteredAdapter", "StagedRunArtifact", "StagingError",
    "ToolAdapter", "ToolIdentity", "ToolInvoker", "ToolLimitation", "stage_run",
]
