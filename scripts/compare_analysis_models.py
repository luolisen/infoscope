"""Compare configured models against one immutable sanitized Window Analysis batch."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Literal
from uuid import UUID

import httpx
from infoscope.analysis.client import AnalysisError, DeepSeekAnalysisClient
from infoscope.analysis.schemas import AnalysisSignal, WindowAnalysisBatchArtifact
from infoscope.config import get_settings
from infoscope.db import close_database, session_factory
from infoscope.models import EvidenceVisibility, PipelineArtifact, PipelineRun, Signal
from infoscope.pipeline import LogicalWindow
from infoscope.schemas.model_settings import ModelSelection
from infoscope.services.model_settings import analysis_config_for_selection
from sqlalchemy import select

Target = Literal["dragon", "kimi", "qwen"]
TARGET_SELECTIONS: dict[Target, ModelSelection] = {
    "dragon": ModelSelection(source_id="gpt_5_5", model_id="gpt-5.5"),
    "kimi": ModelSelection(source_id="ai_ping", model_id="Kimi-K3"),
    "qwen": ModelSelection(source_id="ai_ping", model_id="Qwen3.8-Max"),
}


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    target: str
    provider: str
    configured_model: str
    returned_model: str | None
    status: str
    error_code: str | None
    elapsed_seconds: float
    signal_count: int
    cluster_count: int | None
    cluster_titles: list[str] | None
    cluster_sizes: list[int] | None
    unassigned_count: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None


async def _fixed_input(
    artifact_id: UUID | None,
    signal_count: int,
) -> tuple[UUID, LogicalWindow, list[AnalysisSignal]]:
    async with session_factory() as database:
        statement = (
            select(PipelineArtifact, PipelineRun)
            .join(PipelineRun, PipelineRun.id == PipelineArtifact.pipeline_run_id)
            .where(PipelineArtifact.artifact_type == "window_analysis_batch")
        )
        if artifact_id is not None:
            statement = statement.where(PipelineArtifact.id == artifact_id)
        rows = list(
            (
                await database.execute(
                    statement.order_by(PipelineArtifact.created_at, PipelineArtifact.id)
                )
            ).all()
        )
        selected: tuple[PipelineArtifact, PipelineRun] | None = None
        selected_ids: list[UUID] = []
        for artifact, run in rows:
            payload = WindowAnalysisBatchArtifact.model_validate(artifact.payload)
            signal_ids = [
                item.signal_id for item in payload.model_output.signal_analyses
            ]
            if artifact_id is not None or len(signal_ids) == signal_count:
                selected = (artifact, run)
                selected_ids = signal_ids
                break
        if selected is None:
            raise RuntimeError("no eligible Window Analysis batch was found")
        artifact, run = selected
        signals = list(
            (
                await database.execute(
                    select(Signal).where(Signal.id.in_(selected_ids))
                )
            ).scalars()
        )
        by_id = {signal.id: signal for signal in signals}
        if set(by_id) != set(selected_ids):
            raise RuntimeError("fixed batch Signals are incomplete")
        values: list[AnalysisSignal] = []
        for signal_id in selected_ids:
            signal = by_id[signal_id]
            if (
                signal.evidence_visibility == EvidenceVisibility.PRIVATE_SANITIZED.value
                and signal.public_provenance is not None
            ):
                raise RuntimeError("private Signal contains provenance")
            values.append(
                AnalysisSignal(
                    signal_id=signal.id,
                    title=signal.title,
                    text=signal.normalized_text,
                    published_at=signal.published_at,
                    source_type=signal.source_type,
                    evidence_visibility=signal.evidence_visibility,
                    public_provenance=signal.public_provenance,
                )
            )
        return (
            artifact.id,
            LogicalWindow(start=run.window_start, end=run.window_end),
            values,
        )


async def _compare(
    target: Target,
    window: LogicalWindow,
    signals: list[AnalysisSignal],
    semaphore: asyncio.Semaphore,
) -> ComparisonResult:
    config = analysis_config_for_selection(get_settings(), TARGET_SELECTIONS[target])
    started = perf_counter()
    async with semaphore:
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                response = await DeepSeekAnalysisClient(
                    client=client, config=config
                ).analyze(
                    window=window,
                    signals=signals,
                )
        except AnalysisError as error:
            return ComparisonResult(
                target=target,
                provider=config.provider,
                configured_model=config.model,
                returned_model=None,
                status="failed",
                error_code=error.error_code,
                elapsed_seconds=round(perf_counter() - started, 3),
                signal_count=len(signals),
                cluster_count=None,
                cluster_titles=None,
                cluster_sizes=None,
                unassigned_count=None,
                prompt_tokens=None,
                completion_tokens=None,
                total_tokens=None,
            )
    return ComparisonResult(
        target=target,
        provider=response.provider,
        configured_model=config.model,
        returned_model=response.model,
        status="succeeded",
        error_code=None,
        elapsed_seconds=round(perf_counter() - started, 3),
        signal_count=len(signals),
        cluster_count=len(response.payload.clusters),
        cluster_titles=[cluster.proposed_title for cluster in response.payload.clusters],
        cluster_sizes=[len(cluster.signal_ids) for cluster in response.payload.clusters],
        unassigned_count=len(response.payload.unassigned_signal_ids),
        prompt_tokens=response.token_usage.prompt_tokens,
        completion_tokens=response.token_usage.completion_tokens,
        total_tokens=response.token_usage.total_tokens,
    )


async def run(args: argparse.Namespace) -> None:
    try:
        artifact_id, window, signals = await _fixed_input(args.artifact_id, args.signal_count)
        semaphore = asyncio.Semaphore(args.concurrency)
        results = await asyncio.gather(
            *(_compare(target, window, signals, semaphore) for target in args.targets)
        )
        print(
            json.dumps(
                {
                    "fixed_batch_artifact_id": str(artifact_id),
                    "signal_count": len(signals),
                    "results": [asdict(result) for result in results],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        await close_database()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-id", type=UUID)
    parser.add_argument("--signal-count", type=int, choices=range(1, 51), default=50)
    parser.add_argument(
        "--targets",
        nargs="+",
        choices=tuple(TARGET_SELECTIONS),
        default=list(TARGET_SELECTIONS),
    )
    parser.add_argument("--concurrency", type=int, choices=(1, 2), default=2)
    return parser.parse_args()


def main() -> None:
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
