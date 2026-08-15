from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "window_analysis.v1"


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
    relationship_type: str
    signal_ids: list[UUID] = Field(min_length=2)
    explanation: str


class MissingContext(StrictModel):
    question: str
    reason: str


class ClusterProposal(StrictModel):
    cluster_key: str
    signal_ids: list[UUID] = Field(min_length=1)
    proposed_title: str
    summary: str
    relationships: list[SignalRelationship]
    missing_context: list[MissingContext]

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


class TokenUsage(StrictModel):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class AnalysisResponse(StrictModel):
    payload: WindowAnalysisPayload
    provider: str
    model: str
    token_usage: TokenUsage
