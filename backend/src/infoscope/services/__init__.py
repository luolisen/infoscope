"""Application services."""

from infoscope.services.acquisition import AcquisitionRepository
from infoscope.services.deduplication import ExactDeduplicationRunner
from infoscope.services.normalization import DeterministicNormalizer, NormalizationRunner
from infoscope.services.pipeline import PipelineRepository

__all__ = [
    "AcquisitionRepository",
    "DeterministicNormalizer",
    "ExactDeduplicationRunner",
    "NormalizationRunner",
    "PipelineRepository",
]
