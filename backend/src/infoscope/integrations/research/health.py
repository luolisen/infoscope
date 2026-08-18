from __future__ import annotations

import asyncio
import os
from pathlib import Path

from infoscope.integrations.research.client import OpenClawResearchClient, ResearchRuntimeError


class AgentReachHealthChecker:
    def __init__(
        self,
        executable: str = "agent-reach",
        *,
        state_dir: Path,
        timeout_seconds: int = 30,
    ) -> None:
        self.executable = executable
        self.state_dir = state_dir
        self.timeout_seconds = timeout_seconds

    async def check(self) -> None:
        environment = await asyncio.to_thread(self._subprocess_env)
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

    def _subprocess_env(self) -> dict[str, str]:
        isolated_home = self.state_dir / "home"
        isolated_tmp = self.state_dir / "tmp"
        isolated_home.mkdir(mode=0o700, parents=True, exist_ok=True)
        isolated_tmp.mkdir(mode=0o700, parents=True, exist_ok=True)
        isolated_home.chmod(0o700)
        isolated_tmp.chmod(0o700)
        environment = {name: value for name in ("PATH",) if (value := os.environ.get(name))}
        environment.setdefault("PATH", os.defpath)
        environment["HOME"] = str(isolated_home)
        environment["TMPDIR"] = str(isolated_tmp)
        return environment


class ResearchCapabilityChecker:
    def __init__(
        self,
        openclaw: OpenClawResearchClient,
        agent_reach: AgentReachHealthChecker,
    ) -> None:
        self.openclaw = openclaw
        self.agent_reach = agent_reach

    async def check(self) -> None:
        await self.openclaw.check_runtime()
        await self.agent_reach.check()
