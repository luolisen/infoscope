from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from infoscope.integrations.research.prompt import build_research_prompt
from infoscope.integrations.research.schemas import (
    ResearchDiscovery,
    ResearchDiscoveryResponse,
    ResearchRequestPayload,
    RuntimeUsage,
)

OPENCLAW_VERSION = "2026.7.1-2"
OPENCLAW_AGENT_ID = "infoscope-research"
OPENCLAW_BASE_ENV_ALLOWLIST = ("PATH",)
OPENCLAW_CREDENTIAL_ENV_ALLOWLIST = ("DEEPSEEK_API_KEY",)


class ResearchRuntimeError(RuntimeError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class OpenClawConfig:
    executable: str
    config_path: Path
    state_dir: Path
    model: str
    timeout_seconds: int
    max_stdout_bytes: int = 65_536


class OpenClawResearchClient:
    def __init__(self, config: OpenClawConfig) -> None:
        self.config = config

    async def discover(
        self,
        payload: ResearchRequestPayload,
        *,
        workdir: Path,
    ) -> ResearchDiscoveryResponse:
        self._prepare_runtime_paths(workdir)
        environment = self._subprocess_env()
        await self._verify_version(workdir, environment)
        prompt_path = workdir / "research-prompt.json"
        await asyncio.to_thread(self._write_private_prompt, prompt_path, payload)
        argv = (
            self.config.executable,
            "agent",
            "--local",
            "--agent",
            OPENCLAW_AGENT_ID,
            "--session-key",
            f"research-{payload.request_id}",
            "--message-file",
            str(prompt_path.resolve()),
            "--model",
            self.config.model,
            "--timeout",
            str(self.config.timeout_seconds),
            "--json",
        )
        try:
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
                    process.communicate(),
                    timeout=self.config.timeout_seconds + 5,
                )
            except TimeoutError as error:
                process.kill()
                await process.wait()
                raise ResearchRuntimeError("RESEARCH_RUNTIME_TIMEOUT") from error
            if len(stdout) > self.config.max_stdout_bytes:
                raise ResearchRuntimeError("RESEARCH_RUNTIME_PROTOCOL_INVALID")
            try:
                envelope = json.loads(stdout)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ResearchRuntimeError("RESEARCH_RUNTIME_PROTOCOL_INVALID") from error
            return self._parse_envelope(envelope, process.returncode, payload)
        finally:
            prompt_path.unlink(missing_ok=True)

    async def _verify_version(
        self, workdir: Path, environment: dict[str, str]
    ) -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                self.config.executable,
                "--version",
                cwd=workdir,
                env=environment,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as error:
            raise ResearchRuntimeError("RESEARCH_RUNTIME_UNAVAILABLE") from error
        try:
            stdout, _stderr = await asyncio.wait_for(process.communicate(), timeout=10)
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise ResearchRuntimeError("RESEARCH_RUNTIME_TIMEOUT") from error
        try:
            version = stdout.decode("utf-8").strip()
        except UnicodeDecodeError as error:
            raise ResearchRuntimeError("RESEARCH_RUNTIME_UNAVAILABLE") from error
        match = re.fullmatch(r"(?:OpenClaw )?([^\s]+)(?: \([0-9a-f]+\))?", version)
        if (
            process.returncode != 0
            or match is None
            or match.group(1) != OPENCLAW_VERSION
        ):
            raise ResearchRuntimeError("RESEARCH_RUNTIME_UNAVAILABLE")

    def _prepare_runtime_paths(self, workdir: Path) -> None:
        if not self.config.config_path.is_file() or self.config.config_path.is_symlink():
            raise ResearchRuntimeError("RESEARCH_RUNTIME_UNAVAILABLE")
        workdir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.config.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        workdir.chmod(0o700)
        self.config.state_dir.chmod(0o700)

    @staticmethod
    def _write_private_prompt(path: Path, payload: ResearchRequestPayload) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(build_research_prompt(payload))
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    def _subprocess_env(self) -> dict[str, str]:
        environment: dict[str, str] = {}
        for name in OPENCLAW_BASE_ENV_ALLOWLIST + OPENCLAW_CREDENTIAL_ENV_ALLOWLIST:
            value = os.environ.get(name)
            if value:
                environment[name] = value
        environment.setdefault("PATH", os.defpath)
        isolated_home = self.config.state_dir / "home"
        isolated_home.mkdir(mode=0o700, parents=True, exist_ok=True)
        isolated_home.chmod(0o700)
        environment["HOME"] = str(isolated_home)
        environment["TMPDIR"] = str(self.config.state_dir / "tmp")
        Path(environment["TMPDIR"]).mkdir(mode=0o700, parents=True, exist_ok=True)
        environment["OPENCLAW_CONFIG_PATH"] = str(self.config.config_path.resolve())
        environment["OPENCLAW_STATE_DIR"] = str(self.config.state_dir.resolve())
        return environment

    @staticmethod
    def _parse_envelope(
        envelope: Any,
        returncode: int | None,
        request: ResearchRequestPayload,
    ) -> ResearchDiscoveryResponse:
        if returncode not in {0, None}:
            raise ResearchRuntimeError("RESEARCH_RUNTIME_FAILED")
        if not isinstance(envelope, dict):
            raise ResearchRuntimeError("RESEARCH_RUNTIME_PROTOCOL_INVALID")
        meta = envelope.get("meta")
        payloads = envelope.get("payloads")
        if not isinstance(meta, dict) or not isinstance(payloads, list):
            raise ResearchRuntimeError("RESEARCH_RUNTIME_PROTOCOL_INVALID")
        if meta.get("aborted") is True:
            raise ResearchRuntimeError("RESEARCH_RUNTIME_FAILED")
        if meta.get("error") is not None or meta.get("failureSignal") is not None:
            raise ResearchRuntimeError("RESEARCH_RUNTIME_FAILED")

        visible: list[str] = []
        for item in payloads:
            if not isinstance(item, dict):
                raise ResearchRuntimeError("RESEARCH_RUNTIME_PROTOCOL_INVALID")
            if item.get("isError") is True:
                raise ResearchRuntimeError("RESEARCH_RUNTIME_FAILED")
            if item.get("isReasoning") is True or item.get("isCommentary") is True:
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                visible.append(text)
        if len(visible) != 1:
            raise ResearchRuntimeError("RESEARCH_RUNTIME_PROTOCOL_INVALID")
        try:
            document = json.loads(visible[0])
        except json.JSONDecodeError as error:
            raise ResearchRuntimeError("RESEARCH_DISCOVERY_INVALID_JSON") from error

        agent_meta = meta.get("agentMeta")
        if not isinstance(agent_meta, dict):
            raise ResearchRuntimeError("RESEARCH_RUNTIME_PROTOCOL_INVALID")
        provider = agent_meta.get("provider")
        model = agent_meta.get("model")
        if not isinstance(provider, str) or not provider:
            raise ResearchRuntimeError("RESEARCH_RUNTIME_PROTOCOL_INVALID")
        if not isinstance(model, str) or not model:
            raise ResearchRuntimeError("RESEARCH_RUNTIME_PROTOCOL_INVALID")
        usage_document = agent_meta.get("usage") or {}
        if not isinstance(usage_document, dict):
            raise ResearchRuntimeError("RESEARCH_RUNTIME_PROTOCOL_INVALID")
        usage_document = {
            name: usage_document.get(name, 0) for name in ("input", "output", "total")
        }
        try:
            discovery = ResearchDiscovery.model_validate(document)
            usage = RuntimeUsage.model_validate(usage_document)
        except ValidationError as error:
            raise ResearchRuntimeError("RESEARCH_DISCOVERY_SCHEMA_INVALID") from error
        if discovery.request_id != request.request_id:
            raise ResearchRuntimeError("RESEARCH_DISCOVERY_REQUEST_MISMATCH")
        allowed = set(request.allowed_source_kinds)
        if any(item.source_kind not in allowed for item in discovery.candidates):
            raise ResearchRuntimeError("RESEARCH_DISCOVERY_SOURCE_KIND_INVALID")
        return ResearchDiscoveryResponse(
            payload=discovery,
            provider=provider,
            model=model,
            usage=usage,
        )
