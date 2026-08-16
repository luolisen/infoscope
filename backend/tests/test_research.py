from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import MethodType, SimpleNamespace
from uuid import UUID, uuid4

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
from infoscope.integrations.research.health import AgentReachHealthChecker
from infoscope.integrations.research.schemas import (
    ResearchDiscovery,
    ResearchDiscoveryAudit,
    ResearchDiscoveryResponse,
    ResearchEvent,
    ResearchFactSnapshot,
    ResearchRequestPayload,
    ResearchRequestSpec,
    RuntimeUsage,
    canonical_json_bytes,
    request_input_hash,
)
from infoscope.integrations.research.url_policy import (
    ResearchURLRejected,
    ValidatedURL,
    canonicalize_url,
    validate_public_url,
)
from infoscope.models import (
    ResearchRequest,
    ResearchRequestEvent,
    ResearchSource,
    ResearchSourceKind,
    ResearchSourceStatus,
    ResearchStatus,
    ResearchTrigger,
    Signal,
)
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


def _fact_snapshot(event_ids: list[UUID]) -> ResearchFactSnapshot:
    return ResearchFactSnapshot.model_validate(
        {
            "events": [
                {
                    "event_id": event_id,
                    "title": "Event",
                    "overview": "Known facts",
                    "state": "developing",
                    "display_time": "2026-08-16T00:00:00Z",
                    "claims": [],
                    "timeline": [],
                    "conflicts": [],
                    "evidence_signals": [],
                }
                for event_id in sorted(event_ids)
            ]
        }
    )


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        assert self.value is not None
        return self.value


class _ResearchRequestDatabase:
    def __init__(self) -> None:
        self.request = None
        self.added = []
        self.rollbacks = 0

    async def execute(self, statement):
        if getattr(statement, "is_insert", False):
            values = {
                column.key: bound.value for column, bound in statement._values.items()
            }
            if self.request is not None:
                return _ScalarResult(None)
            self.request = ResearchRequest(**values)
            return _ScalarResult(self.request)
        return _ScalarResult(self.request)

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        return None

    async def rollback(self):
        self.rollbacks += 1


async def test_ask_research_request_persists_and_reuses_selected_event_order() -> None:
    event_ids = [
        UUID("00000000-0000-4000-8000-000000000003"),
        UUID("00000000-0000-4000-8000-000000000001"),
        UUID("00000000-0000-4000-8000-000000000002"),
    ]
    database = _ResearchRequestDatabase()
    repository = ResearchRepository(database)  # type: ignore[arg-type]
    snapshot = _fact_snapshot(event_ids)

    async def fact_snapshot(self, requested_ids):
        assert requested_ids == set(event_ids)
        return snapshot

    repository.fact_snapshot = MethodType(fact_snapshot, repository)  # type: ignore[method-assign]
    idempotency_key = uuid4()
    spec = ResearchRequestSpec(
        idempotency_key=idempotency_key,
        trigger=ResearchTrigger.ASK_MISSING_FACT,
        source_event_ids=event_ids,
        research_questions=["What changed?"],
        missing_fact_descriptions=[],
        allowed_source_kinds=[ResearchSourceKind.WEB_PAGE],
    )

    request, payload, inserted = await repository.create_or_reuse(spec, max_attempts=3)
    assert inserted
    assert payload.source_event_ids == event_ids
    assert ResearchRequestPayload.model_validate(
        request.request_payload
    ).source_event_ids == event_ids
    assert request.input_hash == request_input_hash(payload)
    assert [
        item.event_id
        for item in database.added
        if isinstance(item, ResearchRequestEvent)
    ] == event_ids

    reused, reused_payload, inserted = await repository.create_or_reuse(
        spec, max_attempts=3
    )
    assert not inserted
    assert reused is request
    assert reused_payload.source_event_ids == event_ids

    changed_order = spec.model_copy(
        update={"source_event_ids": list(reversed(event_ids))}
    )
    with pytest.raises(ResearchError, match="RESEARCH_IDEMPOTENCY_CONFLICT"):
        await repository.create_or_reuse(changed_order, max_attempts=3)
    assert database.rollbacks == 1


async def test_non_ask_research_trigger_keeps_deterministic_event_sorting() -> None:
    event_ids = [
        UUID("00000000-0000-4000-8000-000000000003"),
        UUID("00000000-0000-4000-8000-000000000001"),
    ]
    database = _ResearchRequestDatabase()
    repository = ResearchRepository(database)  # type: ignore[arg-type]

    async def fact_snapshot(self, requested_ids):
        return _fact_snapshot(event_ids)

    repository.fact_snapshot = MethodType(fact_snapshot, repository)  # type: ignore[method-assign]
    spec = ResearchRequestSpec(
        idempotency_key=uuid4(),
        trigger=ResearchTrigger.BACKWRITE_ENRICHMENT,
        source_event_ids=event_ids,
        research_questions=["What changed?"],
        missing_fact_descriptions=[],
        allowed_source_kinds=[ResearchSourceKind.WEB_PAGE],
    )

    _, payload, _ = await repository.create_or_reuse(spec, max_attempts=3)
    assert payload.source_event_ids == sorted(event_ids)


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
                    "model": "deepseek-v4-flash",
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
            model="deepseek/deepseek-v4-flash",
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
    assert environment["HOME"] == str(state_dir / "home")
    assert environment["TMPDIR"] == str(state_dir / "tmp")
    assert kwargs["cwd"] == workdir
    assert kwargs["stdin"] == os.devnull or kwargs["stdin"] == -3
    assert not captured["prompt_path"].exists()


async def test_agent_reach_uses_same_isolated_home(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class Process:
        async def wait(self):
            return 0

    async def create_subprocess_exec(*argv, **kwargs):
        captured["argv"] = argv
        captured["env"] = kwargs["env"]
        return Process()

    monkeypatch.setattr(
        "infoscope.integrations.research.health.asyncio.create_subprocess_exec",
        create_subprocess_exec,
    )
    monkeypatch.setenv("HOME", "/Users/alan")
    monkeypatch.setenv("FORBIDDEN_SECRET", "must-not-leak")
    state_dir = tmp_path / "state"
    await AgentReachHealthChecker("agent-reach", state_dir=state_dir).check()

    assert captured["argv"] == ("agent-reach", "doctor")
    environment = captured["env"]
    assert environment["HOME"] == str(state_dir / "home")
    assert environment["TMPDIR"] == str(state_dir / "tmp")
    assert "FORBIDDEN_SECRET" not in environment


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
    escaped, _host = canonicalize_url(
        "https://example.com/a%2fb%25c?q=%2f%25", ResearchSourceKind.WEB_PAGE
    )
    assert escaped == "https://example.com/a%2Fb%25c?q=%2F%25"
    with pytest.raises(ResearchURLRejected, match="RESEARCH_URL_REJECTED"):
        canonicalize_url("https://user@example.com/", ResearchSourceKind.WEB_PAGE)
    with pytest.raises(ResearchURLRejected, match="RESEARCH_URL_REJECTED"):
        canonicalize_url("https://example.com/%zz", ResearchSourceKind.WEB_PAGE)
    with pytest.raises(ResearchURLRejected, match="RESEARCH_URL_REJECTED"):
        canonicalize_url("https://example.com/%2", ResearchSourceKind.WEB_PAGE)
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
            return SimpleNamespace(
                payload=ResearchDiscoveryAudit(
                    request_id=request.id,
                    candidate_count=len(kwargs["candidates"]),
                    candidates=[],
                ).model_dump(mode="json")
            )

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


async def test_invalid_and_duplicate_candidates_have_privacy_safe_audits() -> None:
    request_id = uuid4()
    discovery = ResearchDiscovery.model_validate(
        {
            "request_id": request_id,
            "candidates": [
                {
                    "source_kind": "web_page",
                    "source_url": "https://user:secret@example.com/report",
                    "relevance_summary": "invalid",
                },
                {
                    "source_kind": "web_page",
                    "source_url": "https://example.com/a%2fb",
                    "relevance_summary": "valid",
                },
                {
                    "source_kind": "web_page",
                    "source_url": "https://EXAMPLE.com:443/a%2Fb#fragment",
                    "relevance_summary": "duplicate",
                },
            ],
        }
    )

    async def validator(value, source_kind):
        canonical_url, hostname = canonicalize_url(value, source_kind)
        return ValidatedURL(
            canonical_url=canonical_url,
            canonical_url_hash=sha256(canonical_url.encode()).hexdigest(),
            hostname=hostname,
            addresses=frozenset({"203.0.113.10"}),
        )

    runner = ResearchRunner(
        repository=object(),  # type: ignore[arg-type]
        acquisition=object(),  # type: ignore[arg-type]
        client=object(),  # type: ignore[arg-type]
        fetcher=object(),  # type: ignore[arg-type]
        max_attempts=3,
        url_validator=validator,
    )
    audits = await runner._audit_candidates(discovery)

    assert [audit.status for audit in audits] == [
        ResearchSourceStatus.FAILED,
        ResearchSourceStatus.PENDING,
        ResearchSourceStatus.FAILED,
    ]
    assert audits[0].error_code == "RESEARCH_URL_REJECTED"
    assert audits[0].canonical_url is None
    assert audits[0].candidate_url_hash == sha256(
        discovery.candidates[0].source_url.encode()
    ).hexdigest()
    assert audits[1].canonical_url == "https://example.com/a%2Fb"
    assert audits[2].error_code == "RESEARCH_DUPLICATE_CANDIDATE"
    assert audits[2].canonical_url is None

    class Database:
        def __init__(self):
            self.added = []

        def add(self, value):
            self.added.append(value)

        async def commit(self):
            return None

    database = Database()
    repository = ResearchRepository(database)  # type: ignore[arg-type]
    artifact = await repository.persist_discovery(
        request=SimpleNamespace(id=request_id, input_hash="a" * 64),
        run=SimpleNamespace(id=uuid4()),
        response=ResearchDiscoveryResponse(
            payload=discovery,
            provider="deepseek",
            model="deepseek-v4-flash",
            usage=RuntimeUsage(),
        ),
        candidates=audits,
    )
    assert artifact.payload == {
        "schema_version": "research_discovery_audit.v1",
        "request_id": str(request_id),
        "candidate_count": 3,
        "candidates": [
            {
                "candidate_index": 0,
                "source_kind": "web_page",
                "candidate_url_hash": audits[0].candidate_url_hash,
                "decision": "rejected",
                "canonical_url": None,
                "relevance_summary": None,
                "error_code": "RESEARCH_URL_REJECTED",
            },
            {
                "candidate_index": 1,
                "source_kind": "web_page",
                "candidate_url_hash": audits[1].candidate_url_hash,
                "decision": "accepted",
                "canonical_url": "https://example.com/a%2Fb",
                "relevance_summary": "valid",
                "error_code": None,
            },
            {
                "candidate_index": 2,
                "source_kind": "web_page",
                "candidate_url_hash": audits[2].candidate_url_hash,
                "decision": "rejected",
                "canonical_url": None,
                "relevance_summary": None,
                "error_code": "RESEARCH_DUPLICATE_CANDIDATE",
            },
        ],
    }
    serialized_artifact = json.dumps(artifact.payload)
    assert "source_url" not in serialized_artifact
    assert "user:secret" not in serialized_artifact
    persisted_sources = [item for item in database.added if isinstance(item, ResearchSource)]
    assert len(persisted_sources) == 3
    assert persisted_sources[0].canonical_url is None
    assert persisted_sources[0].candidate_url_hash == audits[0].candidate_url_hash
