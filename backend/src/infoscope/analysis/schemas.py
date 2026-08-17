from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "window_analysis.v1"
MODEL_SCHEMA_VERSION = "window_analysis_model.v2"
BATCH_SCHEMA_VERSION = "window_analysis_batch.v2"
MANIFEST_SCHEMA_VERSION = "window_analysis.v2"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisSignal(StrictModel):
    signal_id: UUID
    title: str | None
    text: str
    published_at: datetime | None
    source_type: str
    evidence_visibility: str
    public_provenance: dict[str, Any] | None


class SignalAnalysis(StrictModel):
    signal_id: UUID
    categories: list[str] = Field(max_length=8)
    fact_claims: list[str] = Field(max_length=12)


class SignalRelationship(StrictModel):
    relationship_type: str = Field(max_length=100)
    signal_ids: list[UUID] = Field(min_length=2)
    explanation: str = Field(max_length=500)


class MissingContext(StrictModel):
    question: str = Field(max_length=300)
    reason: str = Field(max_length=500)


class ClusterProposal(StrictModel):
    cluster_key: str
    signal_ids: list[UUID] = Field(min_length=1)
    proposed_title: str = Field(max_length=200)
    summary: str = Field(max_length=800)
    relationships: list[SignalRelationship] = Field(max_length=12)
    missing_context: list[MissingContext] = Field(max_length=4)

    @model_validator(mode="after")
    def relationships_stay_within_cluster(self) -> ClusterProposal:
        members = set(self.signal_ids)
        if any(
            not set(relationship.signal_ids) <= members
            for relationship in self.relationships
        ):
            raise ValueError("relationship signals must belong to their cluster")
        return self


class WindowAnalysisPayload(StrictModel):
    schema_version: Literal["window_analysis.v1"] = SCHEMA_VERSION
    signal_analyses: list[SignalAnalysis]
    clusters: list[ClusterProposal]
    unassigned_signal_ids: list[UUID]

    @model_validator(mode="after")
    def unique_assignments(self) -> WindowAnalysisPayload:
        analyzed = [item.signal_id for item in self.signal_analyses]
        if len(analyzed) != len(set(analyzed)):
            raise ValueError("signal_analyses contains duplicate signal ids")
        cluster_keys = [cluster.cluster_key for cluster in self.clusters]
        if len(cluster_keys) != len(set(cluster_keys)):
            raise ValueError("clusters contains duplicate cluster keys")
        assigned = [signal_id for cluster in self.clusters for signal_id in cluster.signal_ids]
        if len(assigned) != len(set(assigned)):
            raise ValueError("a signal cannot be assigned to multiple clusters")
        if set(assigned) & set(self.unassigned_signal_ids):
            raise ValueError("assigned and unassigned signals must be disjoint")
        return self


class ModelSignalAnalysis(SignalAnalysis):
    cluster_key: str | None = Field(default=None, max_length=128)


class ModelSignalRelationship(StrictModel):
    relationship_type: str = Field(max_length=100)
    signal_ids: list[UUID] = Field(min_length=1)
    explanation: str = Field(max_length=500)


class ModelClusterProposal(StrictModel):
    cluster_key: str = Field(max_length=128)
    proposed_title: str = Field(max_length=200)
    summary: str = Field(max_length=800)
    relationships: list[ModelSignalRelationship] = Field(max_length=12)
    missing_context: list[MissingContext] = Field(max_length=4)


class WindowAnalysisModelPayload(StrictModel):
    schema_version: Literal["window_analysis_model.v2"] = MODEL_SCHEMA_VERSION
    signal_analyses: list[ModelSignalAnalysis]
    clusters: list[ModelClusterProposal]

    @model_validator(mode="after")
    def assignments_reference_exact_clusters(self) -> WindowAnalysisModelPayload:
        signal_ids = [item.signal_id for item in self.signal_analyses]
        if len(signal_ids) != len(set(signal_ids)):
            raise ValueError("signal_analyses contains duplicate signal ids")
        cluster_keys = [cluster.cluster_key for cluster in self.clusters]
        if len(cluster_keys) != len(set(cluster_keys)):
            raise ValueError("clusters contains duplicate cluster keys")
        assigned_keys = {
            item.cluster_key for item in self.signal_analyses if item.cluster_key is not None
        }
        if assigned_keys != set(cluster_keys):
            raise ValueError("cluster_key assignments must match cluster summaries exactly")
        return self

    def to_window_payload(self) -> WindowAnalysisPayload:
        return WindowAnalysisPayload(
            signal_analyses=[
                SignalAnalysis(
                    signal_id=item.signal_id,
                    categories=item.categories,
                    fact_claims=item.fact_claims,
                )
                for item in self.signal_analyses
            ],
            clusters=[
                ClusterProposal(
                    cluster_key=cluster.cluster_key,
                    signal_ids=[
                        item.signal_id
                        for item in self.signal_analyses
                        if item.cluster_key == cluster.cluster_key
                    ],
                    proposed_title=cluster.proposed_title,
                    summary=cluster.summary,
                    relationships=[
                        SignalRelationship(
                            relationship_type=relationship.relationship_type,
                            signal_ids=relationship.signal_ids,
                            explanation=relationship.explanation,
                        )
                        for relationship in cluster.relationships
                        if len(set(relationship.signal_ids)) >= 2
                        and set(relationship.signal_ids)
                        <= {
                            item.signal_id
                            for item in self.signal_analyses
                            if item.cluster_key == cluster.cluster_key
                        }
                    ],
                    missing_context=cluster.missing_context,
                )
                for cluster in self.clusters
            ],
            unassigned_signal_ids=[
                item.signal_id for item in self.signal_analyses if item.cluster_key is None
            ],
        )


class TokenUsage(StrictModel):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class AnalysisResponse(StrictModel):
    payload: WindowAnalysisPayload
    provider: str
    model: str
    token_usage: TokenUsage


class WindowAnalysisBatchArtifact(StrictModel):
    schema_version: Literal["window_analysis_batch.v2"] = BATCH_SCHEMA_VERSION
    batch_index: int = Field(ge=0)
    batch_count: int = Field(gt=0)
    window_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_output: WindowAnalysisPayload

    @model_validator(mode="after")
    def batch_index_is_in_range(self) -> WindowAnalysisBatchArtifact:
        if self.batch_index >= self.batch_count:
            raise ValueError("batch_index must be less than batch_count")
        return self


class WindowAnalysisManifest(StrictModel):
    schema_version: Literal["window_analysis.v2"] = MANIFEST_SCHEMA_VERSION
    batch_artifact_ids: list[UUID] = Field(min_length=1)
    signal_count: int = Field(ge=0)
    window_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def batch_artifacts_are_unique(self) -> WindowAnalysisManifest:
        if len(self.batch_artifact_ids) != len(set(self.batch_artifact_ids)):
            raise ValueError("batch_artifact_ids must be unique")
        return self
