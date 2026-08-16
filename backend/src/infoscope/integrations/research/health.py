from __future__ import annotations

import asyncio
import os
from pathlib import Path

from infoscope.integrations.research.client import ResearchRuntimeError


class AgentReachHealthChecker:
    def __init__(self, executable: str = "agent-reach", timeout_seconds: int = 30) -> None:
        self.executable = executable
        self.timeout_seconds = timeout_seconds

    async def check(self) -> None:
        environment = {
            name: value
            for name in ("PATH", "HOME", "TMPDIR")
            if (value := os.environ.get(name))
        }
        environment.setdefault("PATH", os.defpath)
        environment.setdefault("HOME", str(Path.home()))
        try:
            process = await asyncio.create_subprocess_exec(
                self.executable,
                "doctor",
                env=environment,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError as error:
            raise ResearchRuntimeError("RESEARCH_CAPABILITY_UNAVAILABLE") from error
        try:
            returncode = await asyncio.wait_for(process.wait(), timeout=self.timeout_seconds)
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise ResearchRuntimeError("RESEARCH_CAPABILITY_UNAVAILABLE") from error
        if returncode != 0:
            raise ResearchRuntimeError("RESEARCH_CAPABILITY_UNAVAILABLE")
