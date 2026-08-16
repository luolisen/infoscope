from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from infoscope.integrations.research.client import (
    OPENCLAW_AGENT_ID,
    OPENCLAW_CREDENTIAL_ENV_ALLOWLIST,
    OpenClawConfig,
    OpenClawResearchClient,
    ResearchRuntimeError,
)
from infoscope.integrations.research.fetcher import (
    DirectHTTPSResearchFetcher,
    ResearchFetchError,
    _html_document,
    normalize_text,
)
from infoscope.integrations.research.schemas import (
    ResearchDiscovery,
    ResearchDiscoveryResponse,
    ResearchEvent,
    ResearchFactSnapshot,
    ResearchRequestPayload,
    RuntimeUsage,
    canonical_json_bytes,
)
from infoscope.integrations.research.url_policy import (
    ResearchURLRejected,
    ValidatedURL,
    canonicalize_url,
    validate_public_url,
)
from infoscope.models import ResearchSourceKind, ResearchStatus, Signal
from infoscope.services.normalization import DeterministicNormalizer
from infoscope.services.research import ResearchError, ResearchRepository, ResearchRunner


def _payload() -> ResearchRequestPayload:
    event_id = uuid4()
    return ResearchRequestPayload.model_validate(
        {
            "request_id": uuid4(),
            "trigger": "ask_missing_fact",
            "source_event_ids": [event_id],
            "research_questions": ["What changed?"],
            "missing_fact_descriptions": [],
            "current_fact_snapshot": {
                "events": [
                    {
                        "event_id": event_id,
                        "title": "Event",
                        "overview": "Known overview",
                        "state": "developing",
                        "display_time": "2026-08-16T00:00:00Z",
                        "claims": [],
                        "timeline": [],
                        "conflicts": [],
                        "evidence_signals": [],
                    }
                ]
            },
            "allowed_source_kinds": ["web_page"],
        }
    )


def test_openclaw_success_envelope_and_request_id_are_strict() -> None:
    payload = _payload()
    discovery = {
        "schema_version": "research_discovery.v1",
        "request_id": str(payload.request_id),
        "candidates": [
            {
                "source_kind": "web_page",
                "source_url": "https://example.com/report",
                "relevance_summary": "Primary report",
            }
        ],
    }
    response = OpenClawResearchClient._parse_envelope(
        {
            "payloads": [
                {"text": "thinking", "isReasoning": True},
                {"text": json.dumps(discovery)},
            ],
            "meta": {
                "durationMs": 10,
                "agentMeta": {
                    "provider": "deepseek",
                    "model": "test",
                    "usage": {
                        "input": 10,
                        "output": 5,
                        "total": 15,
                        "cacheRead": 2,
                    },
                },
            },
            "ignored": "additive",
        },
        0,
        payload,
    )
    assert response.payload.request_id == payload.request_id
    assert response.usage.total == 15

    discovery["request_id"] = str(uuid4())
    with pytest.raises(ResearchRuntimeError, match="RESEARCH_DISCOVERY_REQUEST_MISMATCH"):
        OpenClawResearchClient._parse_envelope(
            {
                "payloads": [{"text": json.dumps(discovery)}],
                "meta": {
                    "durationMs": 10,
                    "agentMeta": {"provider": "deepseek", "model": "test"},
                },
            },
            0,
            payload,
        )


def test_openclaw_error_envelopes_map_to_stable_codes() -> None:
    payload = _payload()
    with pytest.raises(ResearchRuntimeError, match="RESEARCH_RUNTIME_FAILED"):
        OpenClawResearchClient._parse_envelope(
            {
                "payloads": [],
                "meta": {"durationMs": 10, "aborted": True},
            },
            0,
            payload,
        )
    with pytest.raises(ResearchRuntimeError, match="RESEARCH_RUNTIME_FAILED"):
        OpenClawResearchClient._parse_envelope(
            {
                "payloads": [{"text": "failed", "isError": True}],
                "meta": {"durationMs": 10},
            },
            0,
            payload,
        )
    with pytest.raises(ResearchRuntimeError, match="RESEARCH_RUNTIME_PROTOCOL_INVALID"):
        OpenClawResearchClient._parse_envelope(
            {
                "payloads": [{"text": "one"}, {"text": "two"}],
                "meta": {
                    "durationMs": 10,
                    "agentMeta": {"provider": "deepseek", "model": "test"},
                },
            },
            0,
            payload,
        )


async def test_openclaw_invocation_is_isolated_and_cleans_prompt(
    monkeypatch, tmp_path: Path
) -> None:
    payload = _payload()
    config_path = tmp_path / "research.json"
    config_path.write_text("{}", encoding="utf-8")
    state_dir = tmp_path / "state"
    workdir = tmp_path / "work"
    discovery = {
        "schema_version": "research_discovery.v1",
        "request_id": str(payload.request_id),
        "candidates": [],
    }
    stdout = json.dumps(
        {
            "payloads": [{"text": json.dumps(discovery)}],
            "meta": {
                "durationMs": 10,
                "agentMeta": {
                    "provider": "deepseek",
                    "model": "deepseek-v4-pro",
                    "usage": {},
                },
            },
        }
    ).encode()
    captured: dict[str, object] = {}

    class Process:
        returncode = 0

        def __init__(self, output):
            self.output = output

        async def communicate(self):
            return self.output, b""

    async def create_subprocess_exec(*argv, **kwargs):
        if argv == ("openclaw", "--version"):
            captured["version_kwargs"] = kwargs
            return Process(b"OpenClaw 2026.7.1-2 (0790d9f)\n")
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        prompt_path = Path(argv[argv.index("--message-file") + 1])
        captured["prompt_path"] = prompt_path
        is_file, mode = await asyncio.to_thread(
            lambda: (os.path.isfile(prompt_path), os.stat(prompt_path).st_mode & 0o777)
        )
        assert is_file
        assert mode == 0o600
        return Process(stdout)

    monkeypatch.setattr(
        "infoscope.integrations.research.client.asyncio.create_subprocess_exec",
        create_subprocess_exec,
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")
    monkeypatch.setenv("FORBIDDEN_SECRET", "must-not-leak")
    client = OpenClawResearchClient(
        OpenClawConfig(
            executable="openclaw",
            config_path=config_path,
            state_dir=state_dir,
            model="deepseek/deepseek-v4-pro",
            timeout_seconds=30,
        )
    )
    response = await client.discover(payload, workdir=workdir)

    assert response.payload.candidates == []
    argv = captured["argv"]
    assert argv[:5] == ("openclaw", "agent", "--local", "--agent", OPENCLAW_AGENT_ID)
    assert argv[argv.index("--session-key") + 1] == f"research-{payload.request_id}"
    assert "exec" not in argv
    assert "--deliver" not in argv
    assert "--channel" not in argv
    kwargs = captured["kwargs"]
    environment = kwargs["env"]
    assert environment["DEEPSEEK_API_KEY"] == "secret"
    assert "FORBIDDEN_SECRET" not in environment
    assert set(OPENCLAW_CREDENTIAL_ENV_ALLOWLIST) == {"DEEPSEEK_API_KEY"}
    assert environment["OPENCLAW_CONFIG_PATH"] == str(config_path.resolve())
    assert environment["OPENCLAW_STATE_DIR"] == str(state_dir.resolve())
    assert environment["TMPDIR"] == str(state_dir / "tmp")
    assert kwargs["cwd"] == workdir
    assert kwargs["stdin"] == os.devnull or kwargs["stdin"] == -3
    assert not captured["prompt_path"].exists()


def test_fact_snapshot_rejects_cross_event_relations_and_naive_time() -> None:
    event_id, claim_id, signal_id = uuid4(), uuid4(), uuid4()
    with pytest.raises(ValidationError, match="timeline claims must belong"):
        ResearchEvent.model_validate(
            {
                "event_id": event_id,
                "title": "Event",
                "overview": "Overview",
                "state": "developing",
                "display_time": "2026-08-16T00:00:00Z",
                "claims": [],
                "timeline": [
                    {
                        "timeline_entry_id": uuid4(),
                        "occurred_at": "2026-08-16T00:00:00Z",
                        "summary": "Entry",
                        "claim_ids": [claim_id],
                    }
                ],
                "conflicts": [],
                "evidence_signals": [],
            }
        )
    with pytest.raises(ValidationError, match="display_time must be timezone-aware"):
        ResearchEvent.model_validate(
            {
                "event_id": event_id,
                "title": "Event",
                "overview": "Overview",
                "state": "developing",
                "display_time": "2026-08-16T00:00:00",
                "claims": [],
                "timeline": [],
                "conflicts": [],
                "evidence_signals": [
                    {
                        "signal_id": signal_id,
                        "published_at": None,
                        "sanitized_text": "Evidence",
                        "evidence_visibility": "public",
                        "public_safe_provenance": None,
                    }
                ],
            }
        )


def test_canonical_json_is_stable_and_url_policy_is_exact() -> None:
    snapshot = ResearchFactSnapshot(events=_payload().current_fact_snapshot.events)
    assert canonical_json_bytes(snapshot) == canonical_json_bytes(snapshot)
    canonical, host = canonicalize_url(
        "https://EXAMPLE.com:443/a/./b/../c%7e?q=2&q=1#fragment",
        ResearchSourceKind.WEB_PAGE,
    )
    assert host == "example.com"
    assert canonical == "https://example.com/a/c~?q=2&q=1"
    doubled, _host = canonicalize_url(
        "https://example.com/a//b", ResearchSourceKind.WEB_PAGE
    )
    assert doubled == "https://example.com/a//b"
    with pytest.raises(ResearchURLRejected, match="RESEARCH_URL_REJECTED"):
        canonicalize_url("https://user@example.com/", ResearchSourceKind.WEB_PAGE)
    with pytest.raises(ResearchURLRejected, match="RESEARCH_URL_REJECTED"):
        canonicalize_url("https://example.com/%zz", ResearchSourceKind.WEB_PAGE)
    with pytest.raises(ResearchURLRejected, match="RESEARCH_SOURCE_HOST_REJECTED"):
        canonicalize_url(
            "https://github.com/org/repo/blob/main/README.md",
            ResearchSourceKind.GITHUB_DOCUMENT,
        )


def test_html_extraction_is_deterministic_and_published_time_is_strict() -> None:
    title, published_at, text = _html_document(
        """
        <html><head><title>  Example   Report </title>
        <meta property="ARTICLE:PUBLISHED_TIME" content="2026-08-16T08:00:00+08:00">
        <script>ignore()</script></head>
        <body><nav>Navigation</nav><main><h1>Example Report</h1>
        <p>First\t paragraph.</p><div aria-hidden="true">secret</div></main></body></html>
        """
    )
    assert title == "Example Report"
    assert published_at == datetime(2026, 8, 16, tzinfo=UTC)
    assert text == "Example Report\nFirst paragraph."
    assert normalize_text(" A\r\n\tB  C ") == "A\nB C"


async def test_ssrf_and_connected_peer_are_both_validated(monkeypatch) -> None:
    class Loop:
        async def getaddrinfo(self, *_args, **_kwargs):
            return [(2, 1, 6, "", ("127.0.0.1", 443))]

    monkeypatch.setattr(
        "infoscope.integrations.research.url_policy.asyncio.get_running_loop",
        lambda: Loop(),
    )
    with pytest.raises(ResearchURLRejected, match="RESEARCH_SSRF_REJECTED"):
        await validate_public_url("https://example.com/", ResearchSourceKind.WEB_PAGE)

    validated = ValidatedURL(
        canonical_url="https://example.com/",
        canonical_url_hash="a" * 64,
        hostname="example.com",
        addresses=frozenset({"203.0.113.10"}),
    )

    class Stream:
        def get_extra_info(self, name):
            assert name == "server_addr"
            return ("203.0.113.11", 443)

    response = SimpleNamespace(extensions={"network_stream": Stream()})
    with pytest.raises(ResearchFetchError, match="RESEARCH_DNS_REBINDING_REJECTED"):
        DirectHTTPSResearchFetcher._validate_peer(response, validated)


def test_research_normalization_uses_only_public_provenance() -> None:
    raw = SimpleNamespace(
        source_type="research",
        source_visibility="public",
        content_text="Fetched body",
        provenance={
            "source_kind": "web_page",
            "canonical_url": "https://example.com/report",
            "ignored": "private metadata",
        },
        payload={"title": "Report"},
        published_at=None,
    )
    signal = DeterministicNormalizer().normalize(raw)
    assert signal.title == "Report"
    assert signal.public_provenance == {
        "source_kind": "web_page",
        "canonical_url": "https://example.com/report",
    }


def test_private_provenance_is_blocked_before_research() -> None:
    signal = Signal(
        id=uuid4(),
        raw_information_id=uuid4(),
        signal_index=0,
        title=None,
        normalized_text="Sanitized",
        published_at=None,
        source_type="telegram",
        evidence_visibility="private_sanitized",
        public_provenance={"chat_title": "forbidden"},
        content_hash="a" * 64,
    )
    with pytest.raises(ResearchError, match="RESEARCH_PRIVATE_PROVENANCE_INVALID"):
        ResearchRepository._evidence(signal)


async def test_zero_candidate_research_is_canonical_success() -> None:
    payload = _payload()
    request = SimpleNamespace(
        id=payload.request_id,
        request_payload=payload.model_dump(mode="json"),
        input_hash="a" * 64,
    )
    run = SimpleNamespace(id=uuid4())

    class Repository:
        status = None

        async def start_run(self, request_id):
            assert request_id == request.id
            return request, run

        async def artifact(self, request_id):
            return None

        async def persist_discovery(self, **kwargs):
            return SimpleNamespace(payload=kwargs["response"].payload.model_dump(mode="json"))

        async def sources(self, request_id):
            return []

        async def finish(self, _request, _run, *, status, error_code):
            self.status = (status, error_code)

    class Client:
        async def discover(self, value, *, workdir):
            assert value.request_id == request.id
            assert workdir.exists()
            return ResearchDiscoveryResponse(
                payload=ResearchDiscovery(request_id=request.id, candidates=[]),
                provider="test",
                model="test",
                usage=RuntimeUsage(),
            )

    repository = Repository()
    runner = ResearchRunner(
        repository=repository,  # type: ignore[arg-type]
        acquisition=object(),  # type: ignore[arg-type]
        client=Client(),
        fetcher=object(),  # type: ignore[arg-type]
        max_attempts=3,
    )
    assert await runner.run(request.id, payload=payload) is request
    assert repository.status == (ResearchStatus.SUCCEEDED, None)
