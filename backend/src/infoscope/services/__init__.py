"""Application services."""

from infoscope.services.acquisition import AcquisitionRepository
from infoscope.services.deduplication import ExactDeduplicationRunner
from infoscope.services.normalization import DeterministicNormalizer, NormalizationRunner
from infoscope.services.pipeline import PipelineRepository
from infoscope.services.window_analysis import WindowAnalysisRunner

__all__ = [
    "AcquisitionRepository",
    "DeterministicNormalizer",
    "ExactDeduplicationRunner",
    "NormalizationRunner",
    "PipelineRepository",
    "WindowAnalysisRunner",
]
