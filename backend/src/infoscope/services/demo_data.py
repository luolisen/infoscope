from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from infoscope.db import session_factory
from infoscope.models import (
    BaseAnalysis,
    BriefArtifact,
    BriefRun,
    Claim,
    Conflict,
    Event,
    PersonalizationArtifact,
    PersonalizationRun,
    TimelineEntry,
    User,
)


async def _count(database, model) -> int:
    return int((await database.execute(select(func.count()).select_from(model))).scalar_one())


async def build_demo_data_manifest(username: str | None) -> dict[str, Any]:
    async with session_factory() as database:
        manifest: dict[str, Any] = {
            "schema_version": "demo_data_manifest.v1",
            "fact_layer": {
                "events": await _count(database, Event),
                "claims": await _count(database, Claim),
                "timeline_entries": await _count(database, TimelineEntry),
                "conflicts": await _count(database, Conflict),
                "base_analysis": await _count(database, BaseAnalysis),
            },
            "completed_personalization_artifacts": await database.scalar(
                select(func.count())
                .select_from(PersonalizationArtifact)
                .join(
                    PersonalizationRun,
                    PersonalizationRun.id == PersonalizationArtifact.created_by_run_id,
                )
                .where(PersonalizationRun.status == "completed")
            ),
            "completed_brief_artifacts": await database.scalar(
                select(func.count())
                .select_from(BriefArtifact)
                .join(
                    BriefRun,
                    BriefRun.id == BriefArtifact.created_by_run_id,
                )
                .where(BriefRun.status == "completed")
            ),
        }
        if username is not None:
            user = (
                await database.execute(
                    select(User).where(User.username_normalized == username.strip().lower())
                )
            ).scalar_one_or_none()
            manifest["demo_user"] = {
                "username": username,
                "exists": user is not None,
                "onboarding_completed": bool(user and user.onboarding_completed),
            }
        return manifest


def validate_demo_data_manifest(
    manifest: dict[str, Any],
    *,
    require_complete: bool,
) -> None:
    facts = manifest["fact_layer"]
    if facts["events"] == 0 or facts["base_analysis"] < facts["events"]:
        raise RuntimeError("DEMO_FACT_LAYER_INCOMPLETE")
    if require_complete and (
        manifest["completed_personalization_artifacts"] == 0
        or manifest["completed_brief_artifacts"] == 0
    ):
        raise RuntimeError("DEMO_PERSONALIZATION_OR_BRIEF_INCOMPLETE")
