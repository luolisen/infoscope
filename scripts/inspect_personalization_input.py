"""Print safe size metrics for a user's canonical Personalization input."""

from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from infoscope.analysis.personalization_schemas import canonical_bytes
from infoscope.db import close_database, session_factory
from infoscope.services.personalization import PersonalizationRepository


async def run(user_ids: list[UUID]) -> None:
    try:
        async with session_factory() as database:
            repository = PersonalizationRepository(database)
            metrics = []
            for user_id in user_ids:
                value = await repository.input_snapshot(user_id)
                metrics.append(
                    {
                        "user_id": str(user_id),
                        "event_count": len(value.events),
                        "canonical_bytes": len(canonical_bytes(value)),
                    }
                )
        print(json.dumps(metrics, indent=2))
    finally:
        await close_database()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("user_ids", nargs="+", type=UUID)
    args = parser.parse_args()
    asyncio.run(run(args.user_ids))


if __name__ == "__main__":
    main()
