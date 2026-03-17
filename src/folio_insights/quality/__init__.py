"""Quality output layer: confidence gating and JSON formatting."""

from folio_insights.quality.confidence_gate import ConfidenceGate
from folio_insights.quality.output_formatter import OutputFormatter

__all__ = ["ConfidenceGate", "OutputFormatter"]
