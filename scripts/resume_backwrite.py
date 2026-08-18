"""Resume one durable Backwrite cycle through its original idempotency key."""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from infoscope.analysis.backwrite_schemas import BackwriteSnapshotSpec
from infoscope.db import close_database, session_factory
from infoscope.models import User
from infoscope.services.personalization import (
    PersonalizationVisibleEventSnapshotProvider,
)
from infoscope.worker.main import run_backwrite_spec_once
from sqlalchemy import select


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True)
    parser.add_argument("--idempotency-key", required=True, type=UUID)
    args = parser.parse_args()
    try:
        async with session_factory() as database:
            user = (
                await database.execute(
                    select(User).where(
                        User.username_normalized == args.username.strip().lower(),
                        User.onboarding_completed.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if user is None:
                raise RuntimeError("BACKWRITE_USER_NOT_READY")
            provider = PersonalizationVisibleEventSnapshotProvider(database)
            await run_backwrite_spec_once(
                BackwriteSnapshotSpec(
                    user_id=user.id,
                    idempotency_key=args.idempotency_key,
                ),
                provider=provider,
            )
        return 0
    finally:
        await close_database()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
