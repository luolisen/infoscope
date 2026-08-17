"""Probe one configured model with a safe slice of canonical Personalization input."""

from __future__ import annotations

import argparse
import asyncio
import json
from time import perf_counter
from uuid import UUID

import httpx
from infoscope.analysis.intelligence_client import DeepSeekIntelligenceClient
from infoscope.config import get_settings
from infoscope.db import close_database, session_factory
from infoscope.schemas.model_settings import ModelSelection
from infoscope.services.model_settings import analysis_config_for_selection
from infoscope.services.personalization import PersonalizationRepository


async def run(args: argparse.Namespace) -> None:
    try:
        async with session_factory() as database:
            value = await PersonalizationRepository(database).input_snapshot(
                args.user_id
            )
        end = args.start + args.count
        probe = value.model_copy(update={"events": value.events[args.start : end]})
        selection = ModelSelection(source_id=args.source_id, model_id=args.model_id)
        config = analysis_config_for_selection(get_settings(), selection)
        started = perf_counter()
        async with httpx.AsyncClient(trust_env=False) as client:
            response = await DeepSeekIntelligenceClient(
                client=client,
                config=config,
            ).personalize(probe)
        print(
            json.dumps(
                {
                    "source_id": args.source_id,
                    "configured_model": args.model_id,
                    "returned_model": response.model,
                    "start": args.start,
                    "event_count": len(probe.events),
                    "decision_count": len(response.payload.decisions),
                    "relevant_count": sum(
                        decision.relevant for decision in response.payload.decisions
                    ),
                    "elapsed_seconds": round(perf_counter() - started, 3),
                    "token_usage": response.token_usage.model_dump(mode="json"),
                },
                indent=2,
            )
        )
    finally:
        await close_database()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("user_id", type=UUID)
    parser.add_argument(
        "source_id", choices=("deepseek_official", "gpt_5_5", "ai_ping")
    )
    parser.add_argument("model_id")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, choices=range(1, 21), default=5)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
