"""Verify the controlled fact layer used by the local Demo.

The Demo intentionally reuses a completed, user-independent fact layer rather
than seeding fake Events or copying credentials into the repository.  This
command produces a deterministic, non-sensitive readiness manifest and fails
closed when the required fact layer is incomplete.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from infoscope.db import close_database
from infoscope.services.demo_data import (
    build_demo_data_manifest,
    validate_demo_data_manifest,
)
from sqlalchemy.exc import SQLAlchemyError


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", help="Optional demo username to verify (no password is read).")
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Require at least one completed Personalization and Brief artifact.",
    )
    args = parser.parse_args()
    try:
        manifest = await build_demo_data_manifest(args.username)
        validate_demo_data_manifest(manifest, require_complete=args.require_complete)
        print(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (RuntimeError, SQLAlchemyError, OSError) as error:
        print(f"Demo data is not ready: {error}", file=sys.stderr)
        return 1
    finally:
        await close_database()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
