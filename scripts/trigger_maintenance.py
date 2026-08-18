"""Create one Maintenance run through the production repository contract."""

from __future__ import annotations

import argparse
import asyncio

from infoscope.db import close_database, session_factory
from infoscope.models import User
from infoscope.services.maintenance import MaintenanceRepository
from sqlalchemy import select


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True)
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
                raise RuntimeError("DEMO_USER_NOT_READY")
            run = await MaintenanceRepository(database).create(user.id)
            print(run.id)
        return 0
    finally:
        await close_database()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
