from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from infoscope.integrations.research.client import ResearchRuntimeError
from infoscope.integrations.research.schemas import (
    ResearchDiscovery,
    ResearchDiscoveryResponse,
    ResearchRequestPayload,
    RuntimeUsage,
)


@dataclass(frozen=True, slots=True)
class GrokBuildConfig:
    executable: str
    model: str
    timeout_seconds: int = 180
    max_stdout_bytes: int = 256_000


class GrokBuildResearchClient:
    """ASK-only X discovery adapter for the installed Grok Build CLI.

    It deliberately receives only research questions and missing-fact text. The
    resulting URLs still enter the normal Research runner and never write facts.
    """

    def __init__(self, config: GrokBuildConfig) -> None:
        self.config = config

    async def discover(
        self,
        payload: ResearchRequestPayload,
        *,
        workdir: Path,
    ) -> ResearchDiscoveryResponse:
        await asyncio.to_thread(workdir.mkdir, mode=0o700, parents=True, exist_ok=True)
        prompt = self._prompt(payload)
        environment = {"PATH": os.environ.get("PATH", os.defpath)}
        argv = (
            self.config.executable,
            "--cwd",
            str(workdir),
            "--model",
            self.config.model,
            "--sandbox",
            "workspace",
            "--always-approve",
            "--no-subagents",
            "--max-turns",
            "6",
            "--output-format",
            "streaming-json",
            "-p",
            prompt,
        )
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=workdir,
                env=environment,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as error:
            raise ResearchRuntimeError("RESEARCH_RUNTIME_UNAVAILABLE") from error
        try:
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.config.timeout_seconds
            )
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise ResearchRuntimeError("RESEARCH_RUNTIME_TIMEOUT") from error
        if len(stdout) > self.config.max_stdout_bytes or process.returncode != 0:
            raise ResearchRuntimeError("RESEARCH_RUNTIME_FAILED")
        return self._parse_stream(stdout, payload)

    @staticmethod
    def _prompt(payload: ResearchRequestPayload) -> str:
        document = {
            "schema_version": "grok_x_discovery.v1",
            "request_id": str(payload.request_id),
            "research_questions": payload.research_questions,
            "missing_fact_descriptions": payload.missing_fact_descriptions,
        }
        return (
            "Use the built-in live X search tool, not model memory. Search recent public X posts "
            "that answer the supplied questions. Return exactly one JSON object matching "
            "research_discovery.v1 with at most 4 candidates. Every candidate must use "
            "source_kind web_page, a direct https://x.com/<account>/status/<id> URL, and a "
            "short relevance_summary. Copy request_id exactly. No prose or Markdown. INPUT_JSON:\n"
            + json.dumps(document, ensure_ascii=False, separators=(",", ":"))
        )

    def _parse_stream(
        self, stdout: bytes, payload: ResearchRequestPayload
    ) -> ResearchDiscoveryResponse:
        tool_used = False
        texts: list[str] = []
        usage_document: dict[str, int] = {}
        try:
            lines = stdout.decode("utf-8", errors="strict").splitlines()
        except UnicodeDecodeError as error:
            raise ResearchRuntimeError("RESEARCH_RUNTIME_PROTOCOL_INVALID") from error
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "tool_call_update":
                raw = event.get("rawOutput")
                name = raw.get("name", "") if isinstance(raw, dict) else ""
                tool_used = tool_used or "x_" in name.lower() or "x search" in str(
                    event.get("toolName", "")
                ).lower()
            if event.get("type") == "text" and isinstance(event.get("data"), str):
                texts.append(event["data"])
            if event.get("type") == "usage" and isinstance(event.get("usage"), dict):
                usage_document = event["usage"]
        if not tool_used:
            raise ResearchRuntimeError("GROK_SEARCH_TOOL_NOT_USED")
        raw_text = "".join(texts).strip()
        try:
            discovery = GrokBuildResearchClient._parse_discovery_text(raw_text)
            usage = RuntimeUsage.model_validate(usage_document or {})
        except ValueError as error:
            raise ResearchRuntimeError("RESEARCH_DISCOVERY_SCHEMA_INVALID") from error
        if discovery.request_id != payload.request_id:
            raise ResearchRuntimeError("RESEARCH_DISCOVERY_REQUEST_MISMATCH")
        if len(discovery.candidates) > 4:
            raise ResearchRuntimeError("GROK_OUTPUT_LIMIT_EXCEEDED")
        for candidate in discovery.candidates:
            if candidate.source_kind.value != "web_page" or re.fullmatch(
                r"https://x\.com/[A-Za-z0-9_]{1,15}/status/[0-9]+", candidate.source_url
            ) is None:
                raise ResearchRuntimeError("GROK_SOURCE_URL_INVALID")
        return ResearchDiscoveryResponse(
            payload=discovery,
            provider="grok-build",
            model=self.config.model,
            usage=usage,
        )

    @staticmethod
    def _parse_discovery_text(value: str) -> ResearchDiscovery:
        decoder = json.JSONDecoder()
        for index in range(len(value) - 1, -1, -1):
            if value[index] != "{":
                continue
            try:
                document, _end = decoder.raw_decode(value[index:])
                return ResearchDiscovery.model_validate(document)
            except (json.JSONDecodeError, ValueError):
                continue
        raise ValueError("no valid research discovery JSON")
