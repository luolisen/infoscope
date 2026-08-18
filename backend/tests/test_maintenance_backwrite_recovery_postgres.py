from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4, uuid5

import pytest
from sqlalchemy import delete

from infoscope.db import session_factory
from infoscope.models import (
    BackwriteCycle,
    BackwriteItem,
    BackwriteReconciliationRun,
    Event,
    MaintenanceRun,
    User,
)
from infoscope.services.maintenance import (
    MAINTENANCE_BACKWRITE_NAMESPACE,
    MaintenanceRepository,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("INFOSCOPE_POSTGRES_INTEGRATION") != "1",
    reason="requires the local PostgreSQL integration database",
)


@pytest.mark.asyncio
async def test_terminal_maintenance_fail_closes_its_abandoned_backwrite_cycle() -> None:
    now = datetime.now(UTC)
    user_id = uuid4()
    event_ids = [uuid4(), uuid4()]
    maintenance_id = uuid4()
    cycle_id = uuid4()
    completed_item_id = uuid4()
    abandoned_item_id = uuid4()
    run_id = uuid4()
    idempotency_key = uuid5(
        MAINTENANCE_BACKWRITE_NAMESPACE,
        f"{maintenance_id}:{user_id}:event_backwrite.v1",
    )
    try:
        async with session_factory() as database:
            database.add(
                User(
                    id=user_id,
                    username=f"maintenance-recovery-{user_id}",
                    username_normalized=f"maintenance-recovery-{user_id}",
                    password_hash="unused",
                    onboarding_completed=True,
                )
            )
            database.add_all(
                [
                    Event(
                        id=event_id,
                        title=f"Recovery Event {index}",
                        overview="Recovery test",
                        state="developing",
                        display_time=now,
                    )
                    for index, event_id in enumerate(event_ids)
                ]
            )
            maintenance = MaintenanceRun(
                id=maintenance_id,
                requested_by_user_id=user_id,
                status="pending",
                phase=None,
                active_slot=1,
            )
            database.add(maintenance)
            await database.flush()
            maintenance.status = "failed"
            maintenance.active_slot = None
            maintenance.error_code = "MAINTENANCE_WORKER_LOST"
            maintenance.started_at = now
            maintenance.finished_at = now
            await database.flush()
            database.add(
                BackwriteCycle(
                    id=cycle_id,
                    user_id=user_id,
                    idempotency_key=idempotency_key,
                    input_hash="a" * 64,
                    schema_version="backwrite_snapshot.v1",
                    status="running",
                    snapshot_payload={
                        "schema_version": "backwrite_snapshot.v1",
                        "user_id": str(user_id),
                        "ordered_event_ids": [str(value) for value in event_ids],
                    },
                    item_count=2,
                    started_at=now,
                )
            )
            await database.flush()
            database.add_all(
                [
                    BackwriteItem(
                        id=completed_item_id,
                        cycle_id=cycle_id,
                        event_id=event_ids[0],
                        snapshot_position=0,
                        queue_position=0,
                        status="completed",
                        outcome="no_change",
                        attempt_count=1,
                        max_attempts=3,
                        started_at=now,
                        finished_at=now,
                    ),
                    BackwriteItem(
                        id=abandoned_item_id,
                        cycle_id=cycle_id,
                        event_id=event_ids[1],
                        snapshot_position=1,
                        queue_position=1,
                        status="reconciling",
                        attempt_count=1,
                        max_attempts=3,
                        started_at=now,
                    ),
                ]
            )
            await database.flush()
            database.add(
                BackwriteReconciliationRun(
                    id=run_id,
                    item_id=abandoned_item_id,
                    attempt=1,
                    status="running",
                    started_at=now,
                )
            )
            await database.commit()

            stored_maintenance = await database.get(MaintenanceRun, maintenance_id)
            stored_cycle = await database.get(BackwriteCycle, cycle_id)
            assert stored_maintenance is not None and stored_maintenance.status == "failed"
            assert stored_cycle is not None and stored_cycle.status == "running"
            assert stored_cycle.idempotency_key == idempotency_key

            recovered = await MaintenanceRepository(
                database
            ).recover_terminal_maintenance_backwrites()
            assert cycle_id in {cycle.id for cycle in recovered}

            cycle = await database.get(BackwriteCycle, cycle_id)
            item = await database.get(BackwriteItem, abandoned_item_id)
            run = await database.get(BackwriteReconciliationRun, run_id)
            assert cycle is not None and cycle.status == "partial"
            assert cycle.error_code == "BACKWRITE_PARTIAL_FAILURE"
            assert item is not None and item.status == "failed"
            assert item.error_code == "BACKWRITE_MAINTENANCE_LOST"
            assert run is not None and run.status == "failed"
            assert run.error_code == "BACKWRITE_MAINTENANCE_LOST"
            await database.rollback()
    finally:
        async with session_factory() as database:
            await database.execute(
                delete(BackwriteCycle).where(BackwriteCycle.id == cycle_id)
            )
            await database.execute(
                delete(MaintenanceRun).where(MaintenanceRun.id == maintenance_id)
            )
            await database.execute(delete(Event).where(Event.id.in_(event_ids)))
            await database.execute(delete(User).where(User.id == user_id))
            await database.commit()
