from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from infoscope.models import (
    PipelineArtifact,
    PipelineCheckpoint,
    PipelineRun,
    PipelineRunStatus,
    WindowAnalysisBatchCache,
)
from infoscope.pipeline import AcquisitionCursor, LogicalWindow


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ArtifactWrite:
    id: UUID
    artifact_type: str
    artifact_key: str
    schema_version: str
    input_hash: str
    payload: dict[str, Any]
    provider: str
    model: str
    token_usage: dict[str, Any]


@dataclass(frozen=True, slots=True)
class BatchCacheWrite:
    input_hash: str
    schema_version: str
    payload: dict[str, Any]
    provider: str
    model: str
    token_usage: dict[str, Any]


class PipelineRepository:
    def __init__(self, database: AsyncSession) -> None:
        self.database = database

    async def rollback(self) -> None:
        await self.database.rollback()

    async def latest_successful_window_end(self, pipeline_name: str) -> datetime | None:
        result = await self.database.execute(
            select(func.max(PipelineRun.window_end)).where(
                PipelineRun.pipeline_name == pipeline_name,
                PipelineRun.status == PipelineRunStatus.SUCCEEDED.value,
            )
        )
        return result.scalar_one()

    async def checkpoint_cursor(self, pipeline_name: str) -> AcquisitionCursor | None:
        checkpoint = await self.database.get(PipelineCheckpoint, pipeline_name)
        if checkpoint is None or checkpoint.last_acquired_at is None:
            return None
        if checkpoint.last_raw_id is None:
            raise ValueError("pipeline checkpoint has an incomplete cursor")
        return AcquisitionCursor(checkpoint.last_acquired_at, checkpoint.last_raw_id)

    async def get_run(self, run_id: UUID) -> PipelineRun | None:
        return await self.database.get(PipelineRun, run_id)

    async def recover_stale_running(
        self,
        *,
        stale_before: datetime,
        finished_at: datetime,
        error_code: str = "PIPELINE_WORKER_LOST",
    ) -> list[UUID]:
        """Fail closed runs that cannot still belong to a live pipeline worker.

        Pipeline artifacts are committed only on a successful path, so an
        abandoned ``running`` row has no result to reuse.  Maintenance calls
        this recovery before rebuilding missing derived artifacts; the age
        threshold protects an active model request in the current worker.
        """

        _require_aware(stale_before, "stale_before")
        _require_aware(finished_at, "finished_at")
        if not error_code:
            raise ValueError("a stable error_code is required")
        recovered = list(
            (
                await self.database.execute(
                    update(PipelineRun)
                    .where(
                        PipelineRun.status == PipelineRunStatus.RUNNING.value,
                        PipelineRun.started_at.is_not(None),
                        PipelineRun.started_at < stale_before,
                    )
                    .values(
                        status=PipelineRunStatus.FAILED.value,
                        finished_at=finished_at,
                        next_retry_at=None,
                        error_code=error_code[:128],
                    )
                    .returning(PipelineRun.id)
                )
            ).scalars()
        )
        if recovered:
            await self.database.commit()
        return recovered

    async def latest_window_run(
        self,
        *,
        pipeline_name: str,
        window: LogicalWindow,
    ) -> PipelineRun | None:
        result = await self.database.execute(
            select(PipelineRun)
            .where(
                PipelineRun.pipeline_name == pipeline_name,
                PipelineRun.window_start == window.start,
                PipelineRun.window_end == window.end,
            )
            .order_by(PipelineRun.attempt.desc(), PipelineRun.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def start_run(
        self,
        *,
        pipeline_name: str,
        window: LogicalWindow,
        started_at: datetime,
        lower_cursor: AcquisitionCursor | None,
        attempt: int = 1,
    ) -> PipelineRun:
        if not pipeline_name:
            raise ValueError("pipeline_name is required")
        if attempt <= 0:
            raise ValueError("attempt must be positive")
        _require_aware(started_at, "started_at")
        run = PipelineRun(
            pipeline_name=pipeline_name,
            status=PipelineRunStatus.RUNNING.value,
            window_start=window.start,
            window_end=window.end,
            lower_cursor_acquired_at=lower_cursor.acquired_at if lower_cursor else None,
            lower_cursor_raw_id=lower_cursor.raw_id if lower_cursor else None,
            attempt=attempt,
            started_at=started_at,
        )
        self.database.add(run)
        await self.database.commit()
        return run

    async def retry_run(self, failed_run: PipelineRun, *, started_at: datetime) -> PipelineRun:
        if failed_run.status != PipelineRunStatus.FAILED.value:
            raise ValueError("only failed runs can be retried")
        return await self._repeat_run(failed_run, started_at=started_at)

    async def replay_run(self, terminal_run: PipelineRun, *, started_at: datetime) -> PipelineRun:
        if terminal_run.status not in {
            PipelineRunStatus.SUCCEEDED.value,
            PipelineRunStatus.FAILED.value,
        }:
            raise ValueError("only terminal runs can be replayed")
        return await self._repeat_run(terminal_run, started_at=started_at)

    async def _repeat_run(self, previous_run: PipelineRun, *, started_at: datetime) -> PipelineRun:
        lower_cursor = None
        if previous_run.lower_cursor_acquired_at is not None:
            if previous_run.lower_cursor_raw_id is None:
                raise ValueError("previous run has an incomplete lower cursor")
            lower_cursor = AcquisitionCursor(
                acquired_at=previous_run.lower_cursor_acquired_at,
                raw_id=previous_run.lower_cursor_raw_id,
            )
        return await self.start_run(
            pipeline_name=previous_run.pipeline_name,
            window=LogicalWindow(start=previous_run.window_start, end=previous_run.window_end),
            started_at=started_at,
            lower_cursor=lower_cursor,
            attempt=previous_run.attempt + 1,
        )

    async def fail_run(
        self,
        run: PipelineRun,
        *,
        finished_at: datetime,
        next_retry_at: datetime,
        error_code: str,
    ) -> None:
        if run.status != PipelineRunStatus.RUNNING.value:
            raise ValueError("only running pipeline runs can fail")
        if not error_code:
            raise ValueError("a stable error_code is required")
        _require_aware(finished_at, "finished_at")
        _require_aware(next_retry_at, "next_retry_at")
        run.status = PipelineRunStatus.FAILED.value
        run.finished_at = finished_at
        run.next_retry_at = next_retry_at
        run.error_code = error_code
        await self.database.commit()

    async def complete_run(
        self,
        run: PipelineRun,
        *,
        finished_at: datetime,
        upper_cursor: AcquisitionCursor | None,
    ) -> None:
        if run.status != PipelineRunStatus.RUNNING.value:
            raise ValueError("only running pipeline runs can complete")
        _require_aware(finished_at, "finished_at")
        run.status = PipelineRunStatus.SUCCEEDED.value
        run.finished_at = finished_at
        run.next_retry_at = None
        run.error_code = None
        if upper_cursor is not None:
            run.upper_cursor_acquired_at = upper_cursor.acquired_at
            run.upper_cursor_raw_id = upper_cursor.raw_id
            excluded = insert(PipelineCheckpoint).excluded
            checkpoint = insert(PipelineCheckpoint).values(
                pipeline_name=run.pipeline_name,
                last_acquired_at=upper_cursor.acquired_at,
                last_raw_id=upper_cursor.raw_id,
            )
            await self.database.execute(
                checkpoint.on_conflict_do_update(
                    index_elements=[PipelineCheckpoint.pipeline_name],
                    set_={
                        "last_acquired_at": excluded.last_acquired_at,
                        "last_raw_id": excluded.last_raw_id,
                        "updated_at": func.now(),
                    },
                    where=tuple_(
                        PipelineCheckpoint.last_acquired_at,
                        PipelineCheckpoint.last_raw_id,
                    )
                    < tuple_(excluded.last_acquired_at, excluded.last_raw_id),
                )
            )
        await self.database.commit()

    async def persist_artifact(
        self,
        *,
        run: PipelineRun,
        artifact_type: str,
        schema_version: str,
        input_hash: str,
        payload: dict[str, Any],
        provider: str,
        model: str,
        token_usage: dict[str, Any],
        artifact_key: str = "default",
    ) -> PipelineArtifact:
        if run.status != PipelineRunStatus.RUNNING.value:
            raise ValueError("only running pipeline runs can persist artifacts")
        if len(input_hash) != 64 or any(value not in "0123456789abcdef" for value in input_hash):
            raise ValueError("input_hash must be a lowercase SHA-256 hex digest")
        statement = (
            insert(PipelineArtifact)
            .values(
                id=uuid4(),
                pipeline_run_id=run.id,
                artifact_type=artifact_type,
                artifact_key=artifact_key,
                schema_version=schema_version,
                input_hash=input_hash,
                payload=payload,
                provider=provider,
                model=model,
                token_usage=token_usage,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    PipelineArtifact.pipeline_run_id,
                    PipelineArtifact.artifact_type,
                    PipelineArtifact.artifact_key,
                ]
            )
            .returning(PipelineArtifact)
        )
        artifact = (await self.database.execute(statement)).scalar_one_or_none()
        if artifact is None:
            artifact = (
                await self.database.execute(
                    select(PipelineArtifact).where(
                        PipelineArtifact.pipeline_run_id == run.id,
                        PipelineArtifact.artifact_type == artifact_type,
                        PipelineArtifact.artifact_key == artifact_key,
                    )
                )
            ).scalar_one()
            if artifact.input_hash != input_hash or artifact.schema_version != schema_version:
                raise ValueError("existing artifact does not match replay input")
        await self.database.commit()
        return artifact

    async def persist_window_bundle(
        self,
        *,
        run: PipelineRun,
        batches: list[ArtifactWrite],
        manifest: ArtifactWrite,
        finished_at: datetime,
        upper_cursor: AcquisitionCursor | None,
    ) -> tuple[list[PipelineArtifact], PipelineArtifact]:
        if run.status != PipelineRunStatus.RUNNING.value:
            raise ValueError("only running pipeline runs can persist a window bundle")
        if not batches:
            raise ValueError("at least one batch artifact is required")
        writes = [*batches, manifest]
        keys = [(item.artifact_type, item.artifact_key) for item in writes]
        if len(keys) != len(set(keys)):
            raise ValueError("artifact type/key pairs must be unique within a run")
        for item in writes:
            if len(item.input_hash) != 64 or any(
                value not in "0123456789abcdef" for value in item.input_hash
            ):
                raise ValueError("input_hash must be a lowercase SHA-256 hex digest")

        artifacts = [
            PipelineArtifact(
                id=item.id,
                pipeline_run_id=run.id,
                artifact_type=item.artifact_type,
                artifact_key=item.artifact_key,
                schema_version=item.schema_version,
                input_hash=item.input_hash,
                payload=item.payload,
                provider=item.provider,
                model=item.model,
                token_usage=item.token_usage,
            )
            for item in writes
        ]
        self.database.add_all(artifacts)
        _require_aware(finished_at, "finished_at")
        run.status = PipelineRunStatus.SUCCEEDED.value
        run.finished_at = finished_at
        run.next_retry_at = None
        run.error_code = None
        if upper_cursor is not None:
            run.upper_cursor_acquired_at = upper_cursor.acquired_at
            run.upper_cursor_raw_id = upper_cursor.raw_id
            excluded = insert(PipelineCheckpoint).excluded
            checkpoint = insert(PipelineCheckpoint).values(
                pipeline_name=run.pipeline_name,
                last_acquired_at=upper_cursor.acquired_at,
                last_raw_id=upper_cursor.raw_id,
            )
            await self.database.execute(
                checkpoint.on_conflict_do_update(
                    index_elements=[PipelineCheckpoint.pipeline_name],
                    set_={
                        "last_acquired_at": excluded.last_acquired_at,
                        "last_raw_id": excluded.last_raw_id,
                        "updated_at": func.now(),
                    },
                    where=tuple_(
                        PipelineCheckpoint.last_acquired_at,
                        PipelineCheckpoint.last_raw_id,
                    )
                    < tuple_(excluded.last_acquired_at, excluded.last_raw_id),
                )
            )
        await self.database.commit()
        return artifacts[:-1], artifacts[-1]

    async def cached_window_batches(
        self, input_hashes: list[str]
    ) -> dict[str, WindowAnalysisBatchCache]:
        if not input_hashes:
            return {}
        result = await self.database.execute(
            select(WindowAnalysisBatchCache).where(
                WindowAnalysisBatchCache.input_hash.in_(input_hashes)
            )
        )
        return {item.input_hash: item for item in result.scalars()}

    async def persist_window_batch_cache(
        self, writes: list[BatchCacheWrite]
    ) -> None:
        if not writes:
            return
        for item in writes:
            if len(item.input_hash) != 64 or any(
                value not in "0123456789abcdef" for value in item.input_hash
            ):
                raise ValueError("input_hash must be a lowercase SHA-256 hex digest")
        statement = insert(WindowAnalysisBatchCache).values(
            [
                {
                    "id": uuid4(),
                    "input_hash": item.input_hash,
                    "schema_version": item.schema_version,
                    "payload": item.payload,
                    "provider": item.provider,
                    "model": item.model,
                    "token_usage": item.token_usage,
                }
                for item in writes
            ]
        )
        await self.database.execute(
            statement.on_conflict_do_nothing(
                index_elements=[WindowAnalysisBatchCache.input_hash]
            )
        )
        await self.database.commit()
