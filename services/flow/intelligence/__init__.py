"""Local intelligence boundary.

Model-specific code belongs in this package. The rest of FLOW consumes the
semantic observation contract and never depends on a vendor SDK.
"""

from .base import IntelligenceEngine
from .qwen_vl import QwenVLIntelligenceEngine
from .schema import IntelligenceObservation

__all__ = ["IntelligenceEngine", "IntelligenceObservation", "QwenVLIntelligenceEngine"]
